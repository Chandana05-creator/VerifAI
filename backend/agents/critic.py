"""VerifAI — backend/agents/critic.py — Critic Agent (devil's advocate)

After the Fact-Check Agent has verified the claims, the Critic tries to PROVE THEM WRONG:
  1. for the strongest claims it asks the model for a web search aimed at evidence AGAINST the claim,
  2. searches, and has every new source classified (supports / refutes / insufficient) like any other evidence,
  3. adds that evidence to the claim and recomputes the confidence with the same formula.
So a claim only keeps a high score if it survives a deliberate attempt to refute it.
Outcome per challenged claim:  upheld  |  weakened (confidence fell by 0.10 or more)  |  downgraded (verdict got worse)
"""
import asyncio
from langchain_core.prompts import ChatPromptTemplate
from services.llm_factory import get_llm
from services.tavily_client import get_tavily, search
from services.json_utils import llm_text, parse_json
from agents.factcheck import (_classify_evidence, _compute_confidence, _detect_contradictions,
                              build_contradiction, split_evidence)
from config import settings

_llm = get_llm(tier="fast", max_tokens=512)
_tavily = get_tavily(max_results=5, search_depth="advanced")

_CHALLENGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a sceptical fact-checker playing devil's advocate. Given a CLAIM that appears to be
supported, write ONE web-search query that is most likely to surface credible evidence AGAINST it
(counter-examples, retractions, studies that found the opposite, corrections).
Return ONLY JSON: {{"query": "..."}}"""),
    ("human", "CLAIM: {claim}"),
])

_RANK = {"VERIFIED": 2, "DISPUTED": 1, "UNVERIFIED": 0}


def _outcome(before: tuple[float, str], after: tuple[float, str]) -> str:
    (c0, v0), (c1, v1) = before, after
    if _RANK.get(v1, 0) < _RANK.get(v0, 0):
        return "downgraded"
    if c1 <= c0 - 0.10:
        return "weakened"
    return "upheld"


def _all_classifications(claim: dict) -> list[dict]:
    return list(claim.get("supporting", [])) + list(claim.get("refuting", [])) + list(claim.get("insufficient", []))


async def _challenge(claim: dict) -> dict:
    try:
        data = parse_json(llm_text(await (_CHALLENGE_PROMPT | _llm).ainvoke({"claim": claim["text"]})))
        query = (data.get("query") if isinstance(data, dict) else "") or ""
    except ValueError:
        query = ""
    query = query.strip() or f"evidence against: {claim['text']}"

    evidence = await search(_tavily, query, "critic")
    classification = await _classify_evidence(claim["text"], evidence)
    new_cls = [c for c in classification.get("classifications", []) if isinstance(c, dict)]

    old_cls = _all_classifications(claim)
    seen = {(c.get("source_url"), c.get("verdict")) for c in old_cls}
    merged = old_cls + [c for c in new_cls if (c.get("source_url"), c.get("verdict")) not in seen]

    before = (claim["confidence"], claim["verdict"])
    confidence, verdict = _compute_confidence(merged)
    supporting, refuting, insufficient = split_evidence(merged)
    new_sup = sum(1 for c in new_cls if c.get("verdict") == "SUPPORTS")
    new_ref = sum(1 for c in new_cls if c.get("verdict") == "REFUTES")

    updated = dict(claim)
    updated.update({
        "confidence": confidence, "verdict": verdict,
        "supporting": supporting, "refuting": refuting, "insufficient": insufficient,
        "contradiction": build_contradiction(supporting, refuting),
        "evidence_sources": list(claim.get("evidence_sources", [])) +
                            [{"url": e["url"], "title": e["title"]} for e in evidence],
        "critic": {"query": query, "sources_checked": len(evidence), "counter_supporting": new_sup,
                   "counter_refuting": new_ref, "confidence_before": before[0], "confidence_after": confidence,
                   "verdict_before": before[1], "verdict_after": verdict,
                   "outcome": _outcome(before, (confidence, verdict)),
                   "note": (classification.get("reasoning") or "")[:300]},
    })
    return updated


async def run_critic(claims: list[dict], max_claims: int | None = None) -> dict:
    """Challenge the strongest claims. Returns the updated claims, average confidence and contradictions."""
    limit = max_claims or settings.critic_max_claims
    ranked = sorted((c for c in claims if c.get("verdict") in ("VERIFIED", "DISPUTED")),
                    key=lambda c: c["confidence"], reverse=True)[:limit]
    targets = {c["idx"] for c in ranked}
    sem = asyncio.Semaphore(settings.factcheck_concurrency)

    async def guarded(c):
        async with sem:
            return await _challenge(c)

    results = await asyncio.gather(*[guarded(c) for c in claims if c["idx"] in targets], return_exceptions=True)
    replaced, failed = {}, 0
    for c, res in zip([c for c in claims if c["idx"] in targets], results):
        if isinstance(res, Exception):
            failed += 1
            print(f"[critic] challenge failed for claim {c['idx']}: {res}")
        else:
            replaced[c["idx"]] = res
    updated = [replaced.get(c["idx"], c) for c in claims]
    avg = round(sum(c["confidence"] for c in updated) / len(updated), 3) if updated else 0.0
    counts = {k: sum(1 for c in replaced.values() if c["critic"]["outcome"] == k) for k in ("upheld", "weakened", "downgraded")}
    return {"claims": updated, "avg_confidence": avg, "contradictions": _detect_contradictions(updated),
            "challenged": len(replaced), "failed": failed, "outcomes": counts}
