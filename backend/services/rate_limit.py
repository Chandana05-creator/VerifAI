"""VerifAI — backend/services/rate_limit.py
Tiny in-memory per-IP limiter for the endpoints that start a pipeline run (each run spends API quota)."""
import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request
from config import settings

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    now, window = time.monotonic(), _hits[key]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.runs_per_minute:
        raise HTTPException(status_code=429, detail=f"Too many requests — limit is {settings.runs_per_minute} runs per minute. Please wait a moment.")
    window.append(now)
