"""VerifAI — backend/agents/plagiarism.py — web-based plagiarism / originality checker

How it works
  1. The text is split into passages (groups of 1-3 sentences, ~18-45 words).
  2. Up to PLAGIARISM_MAX_QUERIES passages (spread evenly through the text) are searched on the web with Tavily.
  3. Each passage is compared with the full text of every result using word 5-gram "shingles":
         overlap = share of the passage's 5-word sequences that also appear in the page   (0..1)
  4. overlap >= 0.60 -> "verbatim" (copied), >= 0.30 -> "partial"; the similarity index is the share of the
     checked words covered by such passages (verbatim counts 1.0, partial 0.5).
Limits: it only sees what the search engine returns, only checks sampled passages, and detects copied or
lightly edited wording rather than deep paraphrase. A clean result is not proof of originality.
"""
import asyncio
from urllib.parse import urlparse

from config import settings
from services.similarity import tokens, shingles, containment, make_chunks


def _query_for(chunk_text: str) -> str:
    """Tavily rejects queries over 400 characters; use the start of the passage."""
    q = " ".join(chunk_text.split())
    if len(q) > 300:
        q = q[:300].rsplit(" ", 1)[0]
    return q


async def _search(query: str) -> list[dict]:
    """Search the web and return results WITH the full page text when available."""
    if not settings.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY is empty. Add it to the .env file and restart.")
    from tavily import TavilyClient
    client = TavilyClient(api_key=settings.tavily_api_key)

    def _call():
        return client.search(query=query, search_depth="basic", max_results=5, include_raw_content=True)

    resp = await asyncio.to_thread(_call)
    return resp.get("results", []) if isinstance(resp, dict) else []


def _select(chunks: list[dict], limit: int) -> list[int]:
    """Indexes of the passages to search: all of them, or an even spread across the text."""
    n = len(chunks)
    if n <= limit:
        return list(range(n))
    if limit == 1:
        return [0]
    return sorted({round(i * (n - 1) / (limit - 1)) for i in range(limit)})


async def check_text(text: str, progress=None) -> dict:
    chunks = make_chunks(text)
    if not chunks:
        raise ValueError("No checkable text found.")
    chosen = _select(chunks, max(1, settings.plagiarism_max_queries))
    sem = asyncio.Semaphore(settings.plagiarism_concurrency)
    done = 0

    async def check_one(idx: int) -> dict:
        nonlocal done
        chunk = chunks[idx]
        ctoks = tokens(chunk["text"])
        out = {"idx": idx, "score": 0.0, "source": None, "failed": False}
        try:
            async with sem:
                results = await _search(_query_for(chunk["text"]))
            for r in results:
                page = r.get("raw_content") or r.get("content") or ""
                score = containment(ctoks, shingles(tokens(page)))
                if score > out["score"]:
                    out["score"], out["source"] = score, {"url": r.get("url", ""), "title": r.get("title", "")}
        except Exception as e:
            print(f"[plagiarism] search failed for passage {idx + 1}: {str(e)[:150]}")
            out["failed"] = True
        done += 1
        if progress:
            await progress(done, len(chosen))
        return out

    outcomes = {o["idx"]: o for o in await asyncio.gather(*[check_one(i) for i in chosen])}
    failed = sum(1 for o in outcomes.values() if o["failed"])
    if failed == len(chosen):
        raise RuntimeError("Web search failed for every passage — check TAVILY_API_KEY and your internet connection.")

    # ── classify passages, build segments for highlighting ──
    sources: dict[str, dict] = {}
    segments, pos = [], 0
    checked_words = flagged_weight = total_words = 0
    for i, ch in enumerate(chunks):
        total_words += ch["words"]
        o = outcomes.get(i)
        status, score, src_no = "not_checked", 0.0, None
        if o is not None and not o["failed"]:
            checked_words += ch["words"]
            score = round(o["score"], 3)
            if score >= settings.plagiarism_verbatim:
                status, w = "verbatim", 1.0
            elif score >= settings.plagiarism_partial:
                status, w = "partial", 0.5
            else:
                status, w = "original", 0.0
            flagged_weight += ch["words"] * w
            if w > 0 and o["source"] and o["source"]["url"]:
                url = o["source"]["url"]
                s = sources.setdefault(url, {"url": url, "title": o["source"]["title"],
                                             "domain": urlparse(url).netloc.removeprefix("www."),
                                             "passages": 0, "max_overlap": 0.0})
                s["passages"] += 1
                s["max_overlap"] = max(s["max_overlap"], score)
        elif o is not None and o["failed"]:
            status = "search_failed"
        if ch["start"] > pos:
            segments.append({"text": text[pos:ch["start"]], "status": "gap"})
        segments.append({"text": ch["text"], "status": status, "score": score, "url": (o or {}).get("source", {}) and (o["source"] or {}).get("url") if status in ("verbatim", "partial") else None})
        pos = ch["end"]
    if pos < len(text):
        segments.append({"text": text[pos:], "status": "gap"})

    ranked = sorted(sources.values(), key=lambda s: s["max_overlap"], reverse=True)
    for n, s in enumerate(ranked, 1):
        s["n"] = n
        s["max_overlap"] = round(s["max_overlap"], 3)
    number_of = {s["url"]: s["n"] for s in ranked}
    for seg in segments:
        seg["source_n"] = number_of.get(seg.get("url")) if seg.get("url") else None
        seg.pop("url", None)

    similarity = round(100.0 * flagged_weight / checked_words, 1) if checked_words else 0.0
    risk = "Low" if similarity < 15 else "Moderate" if similarity < 40 else "High"
    return {
        "similarity_percent": similarity,
        "originality_percent": round(100.0 - similarity, 1),
        "risk": risk,
        "passages_total": len(chunks),
        "passages_checked": len(chosen) - failed,
        "passages_failed": failed,
        "coverage_percent": round(100.0 * checked_words / total_words, 1) if total_words else 0.0,
        "verbatim_passages": sum(1 for s in segments if s["status"] == "verbatim"),
        "partial_passages": sum(1 for s in segments if s["status"] == "partial"),
        "segments": segments,
        "sources": ranked,
        "word_count": total_words,
        "disclaimer": ("This check compares sampled passages with pages found by a web search. It detects copied or "
                       "lightly edited wording, not deep paraphrasing, and a low score does not prove originality."),
    }


async def run_plagiarism_streaming(session_id: str, text: str, ws_manager) -> None:
    """Run the check and stream progress / the result to the browser."""
    from services import session_store

    await ws_manager.wait_for_connection(session_id)

    async def say(status, msg, etype="agent_update", payload=None):
        await ws_manager.broadcast(session_id, {"type": etype, "agent": "plagiarism", "status": status,
                                                "message": msg, "payload": payload})

    async def progress(done, total):
        await say("running", f"Checked {done} of {total} passages…")

    await say("running", "Splitting the text into passages…")
    try:
        result = await check_text(text, progress)
        await say("done", f"Similarity {result['similarity_percent']}% ({result['risk']} risk)",
                  etype="plagiarism_report", payload=result)
        try:
            await session_store.update_session(session_id=session_id, final_report=result,
                                               claim_count=len(result["sources"]),
                                               avg_confidence=result["similarity_percent"] / 100.0)
        except Exception as e:
            print(f"[plagiarism] could not save session {session_id}: {e}")
    except Exception as e:
        print(f"[plagiarism] failed: {e}")
        await say("error", str(e)[:300], etype="error")
    await ws_manager.broadcast(session_id, {"type": "pipeline_complete", "agent": "system", "status": "done",
                                            "message": "Check finished", "payload": None})
