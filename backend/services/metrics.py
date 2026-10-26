"""VerifAI — backend/services/metrics.py
Per-run usage tracking (time per agent, model calls, tokens, searches) used by the analytics dashboard.
A ContextVar remembers which run the current task belongs to, so agents do not need to pass ids around."""
import contextvars
import time
from langchain_core.callbacks import AsyncCallbackHandler

current_session: contextvars.ContextVar = contextvars.ContextVar("verifai_session", default=None)
_runs: dict[str, dict] = {}


def start(session_id: str) -> None:
    _runs[session_id] = {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "searches": 0,
                         "agent_seconds": {}, "errors": [], "_t0": time.perf_counter()}
    current_session.set(session_id)


def _run():
    sid = current_session.get()
    return _runs.get(sid) if sid else None


def add_llm(tokens_in: int = 0, tokens_out: int = 0) -> None:
    r = _run()
    if r is not None:
        r["llm_calls"] += 1
        r["tokens_in"] += int(tokens_in or 0)
        r["tokens_out"] += int(tokens_out or 0)


def add_search(n: int = 1) -> None:
    r = _run()
    if r is not None:
        r["searches"] += n


def add_agent_time(agent: str, seconds: float) -> None:
    r = _run()
    if r is not None:
        r["agent_seconds"][agent] = round(r["agent_seconds"].get(agent, 0.0) + seconds, 2)


def add_error(agent: str, message: str) -> None:
    r = _run()
    if r is not None and len(r["errors"]) < 10:
        r["errors"].append({"agent": agent, "message": str(message)[:200]})


def finish(session_id: str) -> dict:
    r = _runs.pop(session_id, None) or {}
    t0 = r.pop("_t0", None)
    r["total_seconds"] = round(time.perf_counter() - t0, 2) if t0 is not None else 0.0
    return r


class UsageCallback(AsyncCallbackHandler):
    """Attached to every Gemini model: counts calls and tokens for the run that triggered them."""

    async def on_llm_end(self, response, **kwargs) -> None:
        tin = tout = 0
        try:
            for gens in response.generations:
                for g in gens:
                    um = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                    tin += um.get("input_tokens", 0) or 0
                    tout += um.get("output_tokens", 0) or 0
        except Exception:
            pass
        add_llm(tin, tout)
