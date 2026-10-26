"""VerifAI — backend/services/tavily_client.py"""
from functools import lru_cache
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from config import settings
from services import metrics


@lru_cache(maxsize=4)
def get_tavily(max_results: int = 8, search_depth: str = "advanced"):
    # The key MUST go through the wrapper; passing api_key= to TavilySearchResults is ignored.
    if not settings.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY is empty. Add it to the .env file and restart.")
    wrapper = TavilySearchAPIWrapper(tavily_api_key=settings.tavily_api_key)
    return TavilySearchResults(api_wrapper=wrapper, max_results=max_results, search_depth=search_depth,
                               include_raw_content=False, include_images=False, include_answer=False)


def as_results(raw, label: str = "tavily") -> list[dict]:
    """TavilySearchResults returns an error *string* on failure instead of raising.
    Normalise to a list of dicts and print a clear message when something went wrong."""
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if raw:
        print(f"[{label}] Tavily returned an error instead of results: {str(raw)[:200]}")
    return []


async def search(tool, query: str, label: str = "tavily") -> list[dict]:
    """Run one web search (counted in the run's usage metrics) and always return a list of result dicts."""
    metrics.add_search()
    return as_results(await tool.ainvoke(query), label)


tavily_deep = get_tavily(max_results=8, search_depth="advanced")
