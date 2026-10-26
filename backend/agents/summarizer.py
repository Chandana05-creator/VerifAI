
"""VerifAI — backend/agents/summarizer.py — Summarizer Agent."""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from langchain_core.prompts import ChatPromptTemplate

from services.llm_factory import get_llm
from services.json_utils import llm_text, parse_json
from services.similarity import tokens, shingles, containment

logger = logging.getLogger(__name__)

# Use the existing Gemini configuration.
_llm = get_llm(tier="fast", max_tokens=2048)

# Keep the summarizer responsive during a live demonstration.
SUMMARIZER_TIMEOUT_SECONDS = 60

MAX_CLAIMS = 12
MAX_EVIDENCE_PER_CLAIM = 2
MAX_SOURCES = 10
MAX_TEXT_LENGTH = 1200


_SUMMARIZE_PROMPT = ChatPromptTemplate.from_messages([
(
"system",
"""You are a senior research analyst writing a fact-checked report for VerifAI.

Return ONLY one valid JSON object with exactly these keys:
{{
"executive_summary": "3-5 sentences explaining the main findings, overall confidence, and key uncertainties",
"key_findings": [
{{
"finding": "...",
"confidence": 0.0,
"supported_by": ["url"],
"caveat": null
}}
],
"areas_of_uncertainty": [
{{
"topic": "...",
"explanation": "...",
"confidence": 0.0
}}
],
"contradiction_explanations": [
{{
"claim_a": "...",
"claim_b": "...",
"explanation": "...",
"source_url": "..."
}}
]
}}

Rules:

* Key findings must come only from VERIFIED claims with confidence >= 0.75.
* Do not invent claims, sources, URLs, or quotations.
* Explain uncertainty when evidence is disputed or insufficient.
* Do not treat political leaning as proof that a claim is true or false.
* Keep the report concise and factual.
* Confidence must be between 0 and 1.
* Return valid JSON only. Do not use Markdown fences.
  """
  ),
  (
  "human",
  """QUERY:
  {query}

CLAIMS:
{claims_block}

CONTRADICTIONS:
{contradictions_block}

SOURCES:
{sources_block}"""
),
])


def _safe_text(value, limit=MAX_TEXT_LENGTH):
    """Convert a value to bounded display text."""
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _safe_confidence(value):
    """Return confidence between zero and one."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _safe_list(value):
    """Return a list or an empty list."""
    return value if isinstance(value, list) else []


def _format_claims(claims):
    """Prepare claims and evidence for the summarizer."""
    lines = []

    for claim in claims[:MAX_CLAIMS]:
        if not isinstance(claim, dict):
            continue

        verdict = _safe_text(claim.get("verdict", "UNKNOWN"), 40)
        claim_text = _safe_text(claim.get("text", ""))
        confidence = _safe_confidence(claim.get("confidence", 0))

        supporting = _safe_list(claim.get("supporting"))
        refuting = _safe_list(claim.get("refuting"))

        support_urls = [
            _safe_text(item.get("source_url"), 300)
            for item in supporting[:MAX_EVIDENCE_PER_CLAIM]
            if isinstance(item, dict) and item.get("source_url")
        ]

        refute_urls = [
            _safe_text(item.get("source_url"), 300)
            for item in refuting[:MAX_EVIDENCE_PER_CLAIM]
            if isinstance(item, dict) and item.get("source_url")
        ]

        critic = claim.get("critic")
        critic_outcome = (
            _safe_text(critic.get("outcome"), 150)
            if isinstance(critic, dict)
            else ""
        )

        lines.append(
            f"[{verdict} | confidence={confidence:.2f}] {claim_text}\n"
            f"Supporting URLs: {', '.join(support_urls) or 'none'}\n"
            f"Refuting URLs: {', '.join(refute_urls) or 'none'}\n"
            f"Critic result: {critic_outcome or 'none'}"
        )

    if len(claims) > MAX_CLAIMS:
        lines.append(
            f"{len(claims) - MAX_CLAIMS} additional claims omitted."
        )

    return "\n\n".join(lines) or "No claims available."


def _format_contradictions(contradictions):
    """Format conflicting claims without deciding which side is correct."""
    lines = []

    for item in contradictions[:10]:
        if not isinstance(item, dict):
            continue

        lines.append(
            f"Source: {_safe_text(item.get('source_url'), 300) or 'unknown'}\n"
            f"Claim A: {_safe_text(item.get('claim_a_text'), 400)}\n"
            f"Claim B: {_safe_text(item.get('claim_b_text'), 400)}"
        )

    return "\n\n".join(lines) or "No contradictions detected."


def _format_sources(source_scores):
    """Format source credibility information."""
    output = []

    for source in source_scores:
        if not isinstance(source, dict) or "__fleet__" in source:
            continue

        try:
            credibility = float(source.get("credibility", 0))
        except (TypeError, ValueError):
            credibility = 0.0

        try:
            lean = float(source.get("political_lean", 0))
        except (TypeError, ValueError):
            lean = 0.0

        side = (
            "Left-leaning" if lean < -20
            else "Right-leaning" if lean > 20
            else "Centre"
        )

        domain = _safe_text(source.get("domain", "?"), 150)
        output.append(
            f"{domain} — credibility {credibility:.0f}/100, "
            f"{side} (lean {lean:+.0f})"
        )

        if len(output) >= MAX_SOURCES:
            break

    return "\n".join(output) or "No source scores available."


def _collect_citations(sources, claims):
    """Create numbered citations from known research and evidence URLs."""
    year = datetime.now(timezone.utc).year
    items = []
    number = {}

    def add(url, title=""):
        url = _safe_text(url, 2000)

        if not url or url in number:
            return

        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return

        domain = parsed.netloc
        title = _safe_text(title, 300) or domain
        citation_number = len(items) + 1

        number[url] = citation_number
        items.append({
            "n": citation_number,
            "title": title,
            "domain": domain,
            "url": url,
            "apa": f"{domain}. ({year}). {title}. Retrieved from {url}",
        })

    for source in sources:
        if isinstance(source, dict):
            add(source.get("url", ""), source.get("title", ""))

    for claim in claims:
        if not isinstance(claim, dict):
            continue

        for metadata in _safe_list(claim.get("evidence_sources")):
            if isinstance(metadata, dict):
                add(metadata.get("url", ""), metadata.get("title", ""))

        for key in ("supporting", "refuting", "insufficient"):
            for evidence in _safe_list(claim.get(key)):
                if isinstance(evidence, dict):
                    add(evidence.get("source_url", ""))

    return items, number


def _with_evidence_refs(claims, number):
    """Attach citation references to each claim."""
    output = []

    for claim in claims:
        if not isinstance(claim, dict):
            continue

        references = []

        for key, verdict in (
            ("supporting", "SUPPORTS"),
            ("refuting", "REFUTES"),
            ("insufficient", "INSUFFICIENT"),
        ):
            for evidence in _safe_list(claim.get(key)):
                if not isinstance(evidence, dict):
                    continue

                url = evidence.get("source_url", "")

                if url in number:
                    references.append({
                        "n": number[url],
                        "url": url,
                        "verdict": verdict,
                        "quote": _safe_text(
                            evidence.get("key_quote", ""), 200
                        ),
                    })

        output.append({**claim, "evidence_refs": references})

    return output


def _summary_originality(summary, reference):
    """Estimate textual overlap; this is not a plagiarism verdict."""
    reference_tokens = shingles(tokens(reference))

    sentences = [
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", summary or "")
        if len(tokens(sentence)) >= 6
    ]

    if not sentences or not reference_tokens:
        return {
            "max_overlap_pct": 0.0,
            "copied_sentences": 0,
            "checked_sentences": len(sentences),
            "verdict": "Insufficient text for comparison",
        }

    scores = [
        containment(tokens(sentence), reference_tokens)
        for sentence in sentences
    ]

    copied = sum(score >= 0.5 for score in scores)
    top = round(100 * max(scores), 1)

    verdict = (
        "Potential substantial overlap" if copied
        else "Some phrases may be reused" if top >= 30
        else "No substantial overlap detected"
    )

    return {
        "max_overlap_pct": top,
        "copied_sentences": copied,
        "checked_sentences": len(sentences),
        "verdict": verdict,
    }


def _reliability(claims, source_scores, contradictions):
    """Calculate a simple heuristic reliability score."""
    valid_claims = [
        claim for claim in claims if isinstance(claim, dict)
    ]

    if not valid_claims:
        return {
            "score": 0.0,
            "label": "Insufficient data",
            "breakdown": {},
        }

    scored_sources = [
        source for source in source_scores
        if isinstance(source, dict) and "__fleet__" not in source
    ]

    average_confidence = sum(
        _safe_confidence(claim.get("confidence", 0))
        for claim in valid_claims
    ) / len(valid_claims)

    credibility_values = []

    for source in scored_sources:
        try:
            value = float(source.get("credibility", 50))
            credibility_values.append(max(0.0, min(100.0, value)))
        except (TypeError, ValueError):
            continue

    average_credibility = (
        sum(credibility_values) / len(credibility_values) / 100
        if credibility_values else 0.5
    )

    penalty = min(len(contradictions) * 0.05, 0.25)
    score = round(
        average_confidence * average_credibility * (1 - penalty), 3
    )

    label = (
        "High reliability" if score >= 0.75
        else "Moderate reliability" if score >= 0.50
        else "Low reliability" if score >= 0.25
        else "Unreliable / insufficient evidence"
    )

    return {
        "score": score,
        "label": label,
        "breakdown": {
            "avg_claim_confidence": round(average_confidence, 3),
            "avg_source_credibility": round(average_credibility, 3),
            "contradiction_penalty": round(penalty, 3),
        },
    }


def _fallback_synthesis(claims, error=""):
    """Create a useful report when Gemini cannot generate a summary."""
    findings = []
    uncertainties = []

    for claim in claims:
        if not isinstance(claim, dict):
            continue

        confidence = _safe_confidence(claim.get("confidence", 0))
        verdict = str(claim.get("verdict", "")).upper()
        text = _safe_text(claim.get("text", ""))

        if verdict == "VERIFIED" and confidence >= 0.75:
            supported_by = [
                ref.get("url", "")
                for ref in _safe_list(claim.get("evidence_refs"))
                if isinstance(ref, dict)
                and ref.get("verdict") == "SUPPORTS"
                and ref.get("url")
            ]

            findings.append({
                "finding": text,
                "confidence": confidence,
                "supported_by": supported_by,
                "caveat": (
                    "Automatically checked; review the cited evidence."
                ),
            })
        else:
            uncertainties.append({
                "topic": text or "Claim without text",
                "explanation": (
                    f"Verdict: {verdict or 'UNKNOWN'}. "
                    "The claim did not meet the verified-finding threshold."
                ),
                "confidence": confidence,
            })

    summary = (
        f"VerifAI assessed {len(claims)} claims for this research question. "
        f"{len(findings)} claims met the verified-claim threshold "
        "of 75% confidence. Other claims require further review because "
        "their evidence may be disputed or insufficient. "
        "The automated AI synthesis was unavailable, so this report "
        "was assembled from the available claim-verification results."
    )

    if error:
        logger.warning("Fallback summary used: %s", error)

    return {
        "executive_summary": summary,
        "key_findings": findings,
        "areas_of_uncertainty": uncertainties,
        "contradiction_explanations": [],
    }


async def run_summarizer(
    query: str,
    claims: list[dict],
    sources: list[dict],
    source_scores: list[dict],
    contradictions: list[dict],
    context: str,
) -> dict:
    """Generate a report while preserving the existing frontend structure."""
    started_at = time.perf_counter()

    claims = _safe_list(claims)
    sources = _safe_list(sources)
    source_scores = _safe_list(source_scores)
    contradictions = _safe_list(contradictions)

    items, number = _collect_citations(sources, claims)
    claims = _with_evidence_refs(claims, number)
    citations = [item["apa"] for item in items]

    base = {
        "all_claims": claims,
        "source_scores": source_scores,
        "citations": citations,
        "citation_items": items,
        "query": query,
        "claim_count": len(claims),
        "source_count": len(items),
        "contradiction_count": len(contradictions),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not claims:
        report = {
            **base,
            "executive_summary": (
                "VerifAI could not verify any claims for this input. "
                "Check the research results and agent logs, then try again."
            ),
            "key_findings": [],
            "areas_of_uncertainty": [{
                "topic": "Insufficient research results",
                "explanation": (
                    "No claims were available for the summarizer to assess."
                ),
                "confidence": 0.0,
            }],
            "contradiction_explanations": [],
            "reliability": _reliability(
                [], source_scores, contradictions
            ),
            "summary_originality": _summary_originality(
                "", context or ""
            ),
        }

        return {"report": report, "citations": citations}

    synthesis = None
    synthesis_error = None

    try:
        chain = _SUMMARIZE_PROMPT | _llm

        response = await asyncio.wait_for(
            chain.ainvoke({
                "query": _safe_text(query, 2000),
                "claims_block": _format_claims(claims),
                "contradictions_block": _format_contradictions(
                    contradictions
                ),
                "sources_block": _format_sources(source_scores),
            }),
            timeout=SUMMARIZER_TIMEOUT_SECONDS,
        )

        synthesis = parse_json(llm_text(response))

        if not isinstance(synthesis, dict):
            raise ValueError("Model did not return a JSON object.")

        required_keys = (
            "executive_summary",
            "key_findings",
            "areas_of_uncertainty",
            "contradiction_explanations",
        )

        for key in required_keys:
            if key not in synthesis:
                raise ValueError(f"Missing field: {key}")

        if not isinstance(synthesis["executive_summary"], str):
            raise ValueError("executive_summary must be a string.")

        for key in required_keys[1:]:
            if not isinstance(synthesis[key], list):
                raise ValueError(f"{key} must be a list.")

        logger.info(
            "Gemini summarizer completed in %.2f seconds",
            time.perf_counter() - started_at,
        )

    except asyncio.TimeoutError:
        synthesis_error = (
            f"Gemini summarizer exceeded {SUMMARIZER_TIMEOUT_SECONDS}s."
        )
        logger.warning("%s", synthesis_error)

    except Exception as exc:
        synthesis_error = f"{type(exc).__name__}: {exc}"
        logger.warning("Gemini summarizer failed: %s", synthesis_error)

    if synthesis is None:
        synthesis = _fallback_synthesis(claims, synthesis_error)

    # Only accept findings that match verified claims.
    verified_claim_texts = [
        _safe_text(claim.get("text", "")).casefold()
        for claim in claims
        if isinstance(claim, dict)
        and str(claim.get("verdict", "")).upper() == "VERIFIED"
        and _safe_confidence(claim.get("confidence", 0)) >= 0.75
        and _safe_text(claim.get("text", ""))
    ]

    safe_findings = []

    for finding in _safe_list(synthesis.get("key_findings")):
        if not isinstance(finding, dict):
            continue

        finding_text = _safe_text(finding.get("finding", ""))
        normalized = finding_text.casefold()

        matches_claim = any(
            normalized in claim_text or claim_text in normalized
            for claim_text in verified_claim_texts
            if normalized and claim_text
        )

        if not matches_claim:
            continue

        safe_findings.append({
            **finding,
            "finding": finding_text,
            "confidence": _safe_confidence(
                finding.get("confidence", 0)
            ),
            "supported_by": [
                url for url in _safe_list(finding.get("supported_by"))
                if isinstance(url, str) and url.startswith(("http://", "https://"))
            ],
        })

    summary = _safe_text(synthesis.get("executive_summary", ""), 5000)

    if not summary:
        summary = _fallback_synthesis(claims)["executive_summary"]

    reference = (
        (context or "")
        + "\n"
        + "\n".join(
            ref.get("quote", "")
            for claim in claims
            for ref in _safe_list(claim.get("evidence_refs"))
            if isinstance(ref, dict)
        )
    )

    report = {
        **base,
        "executive_summary": summary,
        "key_findings": safe_findings,
        "areas_of_uncertainty": [
            item for item in _safe_list(
                synthesis.get("areas_of_uncertainty")
            )
            if isinstance(item, dict)
        ],
        "contradiction_explanations": [
            item for item in _safe_list(
                synthesis.get("contradiction_explanations")
            )
            if isinstance(item, dict)
        ],
        "reliability": _reliability(
            claims, source_scores, contradictions
        ),
        "summary_originality": _summary_originality(
            summary, reference
        ),
    }

    logger.info(
        "Summarizer finished in %.2fs; claims=%d, citations=%d",
        time.perf_counter() - started_at,
        len(claims),
        len(items),
    )

    return {"report": report, "citations": citations}
