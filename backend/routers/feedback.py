"""VerifAI — backend/routers/feedback.py — 👍 / 👎 on a whole report or on one claim's verdict."""
from fastapi import APIRouter, Depends, HTTPException
from dependencies import get_optional_user
from models.db_models import User
from models.schemas import FeedbackRequest
from services.session_store import add_feedback, get_session

router = APIRouter(tags=["feedback"])


@router.post("/feedback")
async def send_feedback(payload: FeedbackRequest, user: User | None = Depends(get_optional_user)):
    if payload.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="rating must be 1 (helpful) or -1 (not helpful)")
    if not await get_session(payload.session_id):
        raise HTTPException(status_code=404, detail="Unknown session")
    fid = await add_feedback(payload.session_id, payload.rating, payload.claim_idx, payload.comment,
                             user.id if user else None)
    return {"id": fid, "saved": True}
