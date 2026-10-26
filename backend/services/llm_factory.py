"""VerifAI — backend/services/llm_factory.py"""
from functools import lru_cache

from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI

from config import settings
from services.metrics import UsageCallback

# Free tier allows 15 requests/minute per model. Stay under it by making
# calls wait their turn (shared by every agent that uses the same model).
REQUESTS_PER_MINUTE = 12
_limiters: dict = {}


def _limiter_for(model: str) -> InMemoryRateLimiter:
    if model not in _limiters:
        _limiters[model] = InMemoryRateLimiter(
            requests_per_second=REQUESTS_PER_MINUTE / 60,
            check_every_n_seconds=0.1,
            max_bucket_size=2,
        )
    return _limiters[model]


@lru_cache(maxsize=8)
def get_llm(tier: str = "strong", max_tokens: int = 2048):
    """tier='strong' -> GEMINI_MODEL_STRONG, tier='fast' -> GEMINI_MODEL_FAST (from .env)."""
    model = settings.gemini_model_strong if tier == "strong" else settings.gemini_model_fast
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is empty. Add it to the .env file and restart.")

    fast = tier == "fast"
    kwargs = dict(
        model=model,
        google_api_key=settings.gemini_api_key,
        max_output_tokens=max(max_tokens, 4096),
        temperature=0.2,
        max_retries=2,
        timeout=45 if fast else 60,
        rate_limiter=_limiter_for(model),
        callbacks=[UsageCallback()],
    )
    if fast and "pro" not in model.lower():
        kwargs["thinking_budget"] = 0

    try:
        return ChatGoogleGenerativeAI(**kwargs)
    except Exception:
        kwargs.pop("thinking_budget", None)
        return ChatGoogleGenerativeAI(**kwargs)