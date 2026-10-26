"""VerifAI — backend/routers/analytics.py — usage, speed, cost and quality statistics for the dashboard."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median
from fastapi import APIRouter, Depends
from config import settings
from dependencies import get_current_user
from models.db_models import User
from services.session_store import recent_sessions, recent_feedback, kind_of

router = APIRouter(tags=["analytics"])


def _avg(xs):
    xs = list(xs)
    return round(sum(xs) / len(xs), 2) if xs else 0


@router.get("/analytics/summary")
async def analytics_summary(user: User = Depends(get_current_user)):
    sessions = await recent_sessions(500)
    feedback = await recent_feedback(500)

    kinds = Counter(kind_of(s) for s in sessions)
    fact_runs = [s for s in sessions if kind_of(s) != "plagiarism"]
    with_metrics = [s for s in sessions if s.metrics]
    seconds = [s.metrics.get("total_seconds", 0) for s in with_metrics if s.metrics.get("total_seconds")]

    agent_secs: dict[str, list] = defaultdict(list)
    for s in with_metrics:
        for agent, sec in (s.metrics.get("agent_seconds") or {}).items():
            agent_secs[agent].append(sec)

    verdicts, critic, confs = Counter(), Counter(), []
    for s in fact_runs:
        for c in (s.final_report or {}).get("all_claims", []) or []:
            verdicts[c.get("verdict", "?")] += 1
            confs.append(c.get("confidence", 0))
            if c.get("critic"):
                critic[c["critic"].get("outcome", "?")] += 1

    today = datetime.utcnow().date()
    per_day = Counter(s.created_at.date() for s in sessions)
    days = [{"date": (today - timedelta(days=i)).isoformat(), "runs": per_day.get(today - timedelta(days=i), 0)}
            for i in range(13, -1, -1)]

    up = sum(1 for f in feedback if f.rating > 0)
    down = sum(1 for f in feedback if f.rating < 0)
    errors = sum(1 for s in with_metrics if (s.metrics.get("errors") or []))
    return {
        "totals": {"runs": len(sessions), "fact_checks": len(fact_runs), "plagiarism_checks": kinds.get("plagiarism", 0),
                   "by_input": dict(kinds)},
        "speed": {"avg_seconds": _avg(seconds), "median_seconds": round(median(seconds), 2) if seconds else 0,
                  "agent_avg_seconds": {a: _avg(v) for a, v in agent_secs.items()}},
        "usage": {"avg_model_calls": _avg(s.metrics.get("llm_calls", 0) for s in with_metrics),
                  "avg_tokens": _avg(s.metrics.get("tokens_in", 0) + s.metrics.get("tokens_out", 0) for s in with_metrics),
                  "total_tokens": sum(s.metrics.get("tokens_in", 0) + s.metrics.get("tokens_out", 0) for s in with_metrics),
                  "avg_searches": _avg(s.metrics.get("searches", 0) for s in with_metrics)},
        "quality": {"verdicts": dict(verdicts), "avg_claim_confidence": _avg(confs), "critic_outcomes": dict(critic),
                    "error_rate_percent": round(100 * errors / len(with_metrics), 1) if with_metrics else 0},
        "feedback": {"up": up, "down": down,
                     "helpful_percent": round(100 * up / (up + down), 1) if (up + down) else None,
                     "recent_comments": [{"rating": f.rating, "comment": f.comment, "claim_idx": f.claim_idx,
                                          "created_at": f.created_at.isoformat()} for f in feedback if f.comment][:8]},
        "runs_per_day": days,
        "models": {"strong": settings.gemini_model_strong, "fast": settings.gemini_model_fast},
    }
