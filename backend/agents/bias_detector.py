"""VerifAI — backend/agents/bias_detector.py — Bias Detector Agent"""
import asyncio
from urllib.parse import urlparse
from langchain_core.prompts import ChatPromptTemplate
from services.llm_factory import get_llm
from services.json_utils import llm_text, parse_json

_llm = get_llm(tier="fast", max_tokens=512)

# Hand-compiled starter ratings in the style of MBFC / NewsGuard: (credibility 0-100, lean -100..+100, label).
# These are illustrative values; replace with a licensed dataset for production use.
SEED_DB: dict[str, tuple[int, int, str]] = {
    "reuters.com": (96, 0, "High credibility · Factual reporting"),
    "apnews.com": (95, 0, "High credibility · Factual reporting"),
    "bbc.com": (90, -8, "High credibility · Centre-left"),
    "theguardian.com": (82, -30, "High credibility · Left-centre"),
    "economist.com": (88, 5, "High credibility · Centre-right"),
    "ft.com": (87, 8, "High credibility · Centre-right"),
    "nature.com": (97, 0, "Peer-reviewed · Scientific"),
    "science.org": (97, 0, "Peer-reviewed · Scientific"),
    "who.int": (91, 0, "Intergovernmental · Scientific"),
    "ourworldindata.org": (92, -5, "High credibility · Data journalism"),
    "nytimes.com": (80, -25, "High credibility · Left-centre"),
    "washingtonpost.com": (79, -28, "High credibility · Left-centre"),
    "wsj.com": (82, 22, "High credibility · Centre-right"),
    "npr.org": (84, -18, "High credibility · Centre-left"),
    "nasa.gov": (98, 0, "Government · Scientific"),
    "cdc.gov": (95, 0, "Government · Health"),
    "nih.gov": (96, 0, "Government · Medical"),
    "foxnews.com": (55, 72, "Mixed credibility · Right"),
    "msnbc.com": (60, -55, "Mixed credibility · Left"),
    "breitbart.com": (22, 92, "Low credibility · Far-right"),
    "dailymail.co.uk": (42, 35, "Mixed credibility · Right"),
    "huffpost.com": (62, -48, "Mixed credibility · Left"),
    "vox.com": (70, -38, "Mostly factual · Left"),
    "wikipedia.org": (68, 0, "Community-edited · Variable"),
}
_score_cache: dict[str, dict] = {}


def _extract_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        return host or "unknown"
    except Exception:
        return "unknown"


def _seed_lookup(domain: str):
    """Match a domain or any of its sub-domains (e.g. en.wikipedia.org -> wikipedia.org)."""
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        key = ".".join(parts[i:])
        if key in SEED_DB:
            return SEED_DB[key]
    return None


def _lean_label(lean: float) -> str:
    if lean <= -60: return "Far-left"
    if lean <= -30: return "Left"
    if lean <= -10: return "Left-centre"
    if lean < 10: return "Centre"
    if lean < 30: return "Right-centre"
    if lean < 60: return "Right"
    return "Far-right"


def _cred_label(cred: float) -> str:
    if cred >= 85: return "High credibility"
    if cred >= 65: return "Mostly credible"
    if cred >= 45: return "Mixed credibility"
    if cred >= 25: return "Low credibility"
    return "Very low credibility"


_SCORE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a media credibility analyst. Estimate credibility (0-100) and political lean
(-100 far left ... 0 centre ... +100 far right) for the given domain, URL and content snippet.
Return ONLY JSON: {{"credibility": 50, "political_lean": 0, "reasoning": "...", "signals_detected": ["..."]}}"""),
    ("human", "Domain: {domain}\nURL: {url}\nSnippet: {snippet}"),
])


async def _llm_score(domain: str, url: str, content: str) -> dict:
    try:
        response = await (_SCORE_PROMPT | _llm).ainvoke({"domain": domain, "url": url, "snippet": content[:400]})
        data = parse_json(llm_text(response))
        return {"credibility": max(0.0, min(100.0, float(data.get("credibility", 50)))),
                "political_lean": max(-100.0, min(100.0, float(data.get("political_lean", 0)))),
                "reasoning": data.get("reasoning", ""), "signals": data.get("signals_detected", []),
                "method": "llm_heuristic"}
    except Exception as e:
        print(f"[bias_detector] LLM scoring failed for {domain}: {e}")
        return {"credibility": 50.0, "political_lean": 0.0, "reasoning": "Could not be rated automatically.",
                "signals": [], "method": "fallback"}


async def _score_source(source: dict) -> dict:
    url, content = source.get("url", ""), source.get("content", "")
    domain = _extract_domain(url)
    seed = _seed_lookup(domain)
    if seed:
        cred, lean, label = seed
        return {"url": url, "domain": domain, "credibility": float(cred), "political_lean": float(lean),
                "lean_label": _lean_label(lean), "label": label, "method": "seed_db", "signals": [],
                "reasoning": "Starter rating from the built-in source list."}
    if domain in _score_cache:
        return _score_cache[domain]
    scored = await _llm_score(domain, url, content)
    cred, lean = scored["credibility"], scored["political_lean"]
    result = {"url": url, "domain": domain, "credibility": cred, "political_lean": lean,
              "lean_label": _lean_label(lean), "label": f"{_cred_label(cred)} · {_lean_label(lean)}",
              "method": scored["method"], "signals": scored.get("signals", []), "reasoning": scored.get("reasoning", "")}
    if scored["method"] != "fallback":
        _score_cache[domain] = result
    return result


def _aggregate(scores: list[dict]) -> dict:
    if not scores:
        return {}
    creds = [s["credibility"] for s in scores]
    leans = [s["political_lean"] for s in scores]
    spread = round(max(leans) - min(leans), 1)
    avg_lean = round(sum(leans) / len(leans), 1)
    return {"avg_credibility": round(sum(creds) / len(creds), 1), "avg_political_lean": avg_lean,
            "avg_lean_label": _lean_label(avg_lean), "lean_spread": spread, "diverse_sourcing": spread > 60,
            "source_count": len(scores), "high_cred_count": sum(1 for c in creds if c >= 75),
            "low_cred_count": sum(1 for c in creds if c < 45)}


async def run_bias_detector(sources: list[dict]) -> list[dict]:
    if not sources:
        return []
    seen, unique = set(), []
    for s in sources:
        d = _extract_domain(s.get("url", ""))
        if d not in seen:
            seen.add(d)
            unique.append(s)
    results = await asyncio.gather(*[_score_source(s) for s in unique], return_exceptions=True)
    clean = [r for r in results if not isinstance(r, Exception)]
    clean.sort(key=lambda x: x["credibility"], reverse=True)
    return clean + [{"__fleet__": _aggregate(clean)}]
