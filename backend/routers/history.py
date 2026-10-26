"""VerifAI — backend/routers/history.py"""
from fastapi import APIRouter, Depends, HTTPException
from models.db_models import User
from services.session_store import get_sessions, get_session, delete_session, kind_of
from dependencies import get_current_user

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
async def list_history(page: int = 1, limit: int = 20, current_user: User = Depends(get_current_user)):
    sessions = await get_sessions(current_user.id, page, limit)
    return {"page": page, "sessions": [
        {"id": s.id, "query": s.query, "kind": kind_of(s), "mode": s.mode, "claim_count": s.claim_count,
         "avg_confidence": s.avg_confidence, "has_report": bool(s.final_report), "shared": bool(s.share_token),
         "created_at": s.created_at.isoformat()} for s in sessions]}


@router.get("/{session_id}")
async def get_history_item(session_id: str, current_user: User = Depends(get_current_user)):
    s = await get_session(session_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": s.id, "query": s.query, "kind": kind_of(s), "final_report": s.final_report,
            "created_at": s.created_at.isoformat()}


@router.delete("/{session_id}")
async def delete_history_item(session_id: str, current_user: User = Depends(get_current_user)):
    s = await get_session(session_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    await delete_session(session_id)
    return {"deleted": True}
