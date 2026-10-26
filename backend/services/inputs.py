"""VerifAI — backend/services/inputs.py
Holds uploaded images between the upload request and the pipeline run (kept in memory, removed once read)."""
import time

_PENDING: dict[str, tuple[float, dict]] = {}
_TTL = 600  # seconds


def put(session_id: str, payload: dict) -> None:
    now = time.time()
    for k in [k for k, (t, _) in _PENDING.items() if now - t > _TTL]:
        _PENDING.pop(k, None)
    _PENDING[session_id] = (now, payload)


def pop(session_id: str) -> dict | None:
    item = _PENDING.pop(session_id, None)
    return item[1] if item else None
