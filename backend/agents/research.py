"""VerifAI — backend/agents/research.py — Research Agent"""
import asyncio
import hashlib
from langchain_core.prompts import ChatPromptTemplate
from services.llm_factory import get_llm
from services.tavily_client import tavily_deep, search
from services.vector_store import retrieve, ingest_tavily_results
from services.json_utils import llm_text, parse_json

_llm = get_llm(tier="strong", max_tokens=1024)

_EXPAND_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "You are a search query optimizer. Given a research question, generate exactly 3 "
               "alternative phrasings that approach the topic from different angles. "
               'Return ONLY a JSON array of 3 strings, for example ["query1","query2","query3"].'),
    ("human", "{query}"),
])


async def _expand_query(query: str) -> list[str]:
    try:
        response = await (_EXPAND_PROMPT | _llm).ainvoke({"query": query})
        variants = parse_json(llm_text(response))
        if isinstance(variants, list):
            return [query] + [str(v) for v in variants[:3]]
    except ValueError:
        print("[research] query expansion returned no valid JSON; using the original query only")
    return [query]


def _dedup(results: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for res in results:
        h = hashlib.md5((res.get("url", "") + res.get("content", "")[:200]).encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(res)
    return unique


async def _tavily_search(queries: list[str]) -> list[dict]:
    batches = await asyncio.gather(*[search(tavily_deep, q, "research") for q in queries], return_exceptions=True)
    results = []
    for batch in batches:
        if isinstance(batch, Exception):
            print(f"[research] Tavily call failed: {batch}")
            continue
        for item in batch:
            results.append({"content": item.get("content", ""), "url": item.get("url", ""),
                            "title": item.get("title", ""), "source": "tavily"})
    return results


async def _chroma_search(queries: list[str], loop: int) -> list[dict]:
    search_queries = queries if loop == 0 else queries[:2]
    batches = await asyncio.gather(*[retrieve(q, top_k=10, candidate_k=25) for q in search_queries],
                                    return_exceptions=True)
    results = []
    for batch in batches:
        if isinstance(batch, Exception):
            print(f"[research] vector search failed: {batch}")
            continue
        for node in batch or []:
            results.append({"content": node["content"], "url": node["metadata"].get("url", "local-doc"),
                            "title": node["metadata"].get("title", "Indexed document"), "source": "chroma",
                            "score": node.get("rerank_score", 0.0)})
    return results


def _build_context(results: list[dict], query: str) -> str:
    parts = [f"Research context for: '{query}'\n{'=' * 60}"]
    for i, res in enumerate(results, 1):
        parts.append(f"\n[Source {i}] {res['title']}\nURL: {res['url']}\n---\n{res['content'][:800]}\n")
    return "\n".join(parts)


async def run_research(query: str, existing_claims: list[dict] | None = None, loop: int = 0) -> dict:
    effective_query = query
    if loop > 0 and existing_claims:
        low = [c for c in existing_claims if c.get("confidence", 1.0) < 0.6]
        if low:
            effective_query = f"{query} — specifically: " + "; ".join(c["text"] for c in low[:3])

    queries = await _expand_query(effective_query)
    tavily_results, chroma_results = await asyncio.gather(_tavily_search(queries), _chroma_search(queries, loop))

    try:
        await ingest_tavily_results(tavily_results)
    except Exception as e:
        print(f"[research] auto-indexing failed (non-fatal): {e}")

    pooled = _dedup(tavily_results + chroma_results)
    top = pooled[:6]
    return {"sources": top, "context": _build_context(top, effective_query), "query_variants": queries}
