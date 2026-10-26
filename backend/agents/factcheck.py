"""VerifAI — backend/agents/factcheck.py — Fact-Check Agent"""
import asyncio
from langchain_core.prompts import ChatPromptTemplate
from services.llm_factory import get_llm
from services.tavily_client import get_tavily, search
from services.json_utils import llm_text, parse_json
from config import settings

_llm = get_llm(tier="strong", max_tokens=2048)
_tavily = get_tavily(max_results=5, search_depth="advanced")

_EXTRACT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a precise fact-checking analyst. Extract the individual, verifiable factual
claims from the research context provided.
Rules: atomic claims only (one fact each); skip opinions and predictions; each claim must be
self-contained and understandable without the surrounding text.
Return ONLY a JSON array, no other text:
[{{"idx": 0, "text": "...", "source_passage": "..."}}]"""),
    ("human", "Research context:\n\n{context}"),
])

_VERIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a strict fact-checking engine doing natural language inference.
Given a CLAIM and numbered EVIDENCE passages, classify each passage as SUPPORTS, REFUTES or
INSUFFICIENT for the claim, and explain briefly.
Return ONLY JSON:
{{"reasoning": "...", "classifications": [{{"source_url": "...", "verdict": "SUPPORTS", "key_quote": "..."}}]}}"""),
    ("human", "CLAIM: {claim}\n\nEVIDENCE:\n{evidence}"),
])


async def _extract_claims(context: str) -> list[dict]:
    response = await (_EXTRACT_PROMPT | _llm).ainvoke({"context": context})
    try:
        claims = parse_json(llm_text(response))
    except ValueError:
        print("[factcheck] claim extraction returned no valid JSON")
        return []
    if not isinstance(claims, list):
        return []
    return [{"idx": c.get("idx", i), "text": c.get("text", ""), "source_passage": c.get("source_passage", "")}
            for i, c in enumerate(claims) if isinstance(c, dict) and c.get("text", "").strip()]


async def _retrieve_evidence(claim: str) -> list[dict]:
    results = await search(_tavily, f"fact check: {claim}", "factcheck")
    return [{"url": r.get("url", ""), "title": r.get("title", ""), "content": r.get("content", "")[:600]}
            for r in results]


async def _classify_evidence(claim: str, evidence: list[dict]) -> dict:
    if not evidence:
        return {"reasoning": "No evidence retrieved.", "classifications": []}
    evidence_str = "\n\n".join(f"[Source {i+1}] {e['title']}\nURL: {e['url']}\n{e['content']}"
                               for i, e in enumerate(evidence))
    response = await (_VERIFY_PROMPT | _llm).ainvoke({"claim": claim, "evidence": evidence_str})
    text = llm_text(response)
    try:
        data = parse_json(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    return {"reasoning": text[:500], "classifications": []}


def _compute_confidence(classifications: list[dict]) -> tuple[float, str]:
    supports = sum(1 for c in classifications if c.get("verdict") == "SUPPORTS")
    refutes = sum(1 for c in classifications if c.get("verdict") == "REFUTES")
    insuff = sum(1 for c in classifications if c.get("verdict") == "INSUFFICIENT")
    total = supports + refutes + insuff
    if total == 0:
        return 0.0, "UNVERIFIED"
    contested = supports + refutes
    base = supports / contested if contested else 0.0
    confidence = round(base * min(total / 3.0, 1.0), 3)
    if confidence >= 0.75:
        verdict = "VERIFIED"
    elif confidence >= 0.40 or (supports > 0 and refutes > 0):
        verdict = "DISPUTED"
    else:
        verdict = "UNVERIFIED"
    return confidence, verdict


def build_contradiction(supporting: list[dict], refuting: list[dict]):
    """Per-claim conflict: the claim has both supporting and refuting evidence."""
    if not (supporting and refuting):
        return None
    return {"supporting_source": {"url": supporting[0].get("source_url", ""), "quote": supporting[0].get("key_quote", "")},
            "refuting_source": {"url": refuting[0].get("source_url", ""), "quote": refuting[0].get("key_quote", "")},
            "explanation": ""}


def split_evidence(classifications: list[dict]) -> tuple[list, list, list]:
    return ([c for c in classifications if c.get("verdict") == "SUPPORTS"],
            [c for c in classifications if c.get("verdict") == "REFUTES"],
            [c for c in classifications if c.get("verdict") == "INSUFFICIENT"])


async def _verify_claim(claim: dict) -> dict:
    evidence = await _retrieve_evidence(claim["text"])
    classification = await _classify_evidence(claim["text"], evidence)
    cls = [c for c in classification.get("classifications", []) if isinstance(c, dict)]
    confidence, verdict = _compute_confidence(cls)
    supporting, refuting, insufficient = split_evidence(cls)
    return {"idx": claim["idx"], "text": claim["text"], "verdict": verdict, "confidence": confidence,
            "supporting": supporting, "refuting": refuting, "insufficient": insufficient,
            "reasoning": classification.get("reasoning", ""), "source_passage": claim.get("source_passage", ""),
            "evidence_sources": [{"url": e["url"], "title": e["title"]} for e in evidence],
            "contradiction": build_contradiction(supporting, refuting), "critic": None}


def _detect_contradictions(claims: list[dict]) -> list[dict]:
    """Flag a source that SUPPORTS one claim but REFUTES another."""
    index: dict[str, list] = {}
    for claim in claims:
        for ev in claim.get("supporting", []):
            if ev.get("source_url"):
                index.setdefault(ev["source_url"], []).append((claim["idx"], claim["text"], "SUPPORTS"))
        for ev in claim.get("refuting", []):
            if ev.get("source_url"):
                index.setdefault(ev["source_url"], []).append((claim["idx"], claim["text"], "REFUTES"))
    alerts, seen = [], set()
    for url, entries in index.items():
        sup = [(i, t) for i, t, v in entries if v == "SUPPORTS"]
        ref = [(i, t) for i, t, v in entries if v == "REFUTES"]
        for s_idx, s_text in sup:
            for r_idx, r_text in ref:
                pair = (min(s_idx, r_idx), max(s_idx, r_idx))
                if pair not in seen and s_idx != r_idx:
                    seen.add(pair)
                    alerts.append({"claim_a_idx": s_idx, "claim_a_text": s_text, "claim_b_idx": r_idx,
                                   "claim_b_text": r_text, "source_url": url,
                                   "verdict_a": "SUPPORTS", "verdict_b": "REFUTES"})
    return alerts


async def run_factcheck(context: str, sources: list[dict], max_claims: int | None = None,
                        require_sources: bool = True) -> dict:
    """require_sources=False is used for link / text / image inputs, where the claims come from the
    submitted text itself and only the evidence comes from the web."""
    limit = max_claims or settings.max_claims
    if (require_sources and not sources) or (not require_sources and len(context.strip()) < 40):
        print("[factcheck] nothing to fact-check — skipping claim extraction")
        return {"claims": [], "contradictions": [], "avg_confidence": 0.0}
    raw_claims = (await _extract_claims(context))[:limit]
    if not raw_claims:
        return {"claims": [], "contradictions": [], "avg_confidence": 0.0}

    sem = asyncio.Semaphore(settings.factcheck_concurrency)

    async def guarded(c):
        async with sem:
            return await _verify_claim(c)

    results = await asyncio.gather(*[guarded(c) for c in raw_claims], return_exceptions=True)
    claims = []
    for res in results:
        if isinstance(res, Exception):
            print(f"[factcheck] claim verification failed: {res}")
        else:
            claims.append(res)

    avg = sum(c["confidence"] for c in claims) / len(claims) if claims else 0.0
    return {"claims": claims, "contradictions": _detect_contradictions(claims), "avg_confidence": round(avg, 3)}
