"""VerifAI — backend/routers/plagiarism.py"""
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from dependencies import get_optional_user
from models.db_models import User
from models.schemas import PlagiarismRequest, ResearchResponse
from services.rate_limit import rate_limit
from services.ws_manager import manager
from services.session_store import create_session
from agents.plagiarism import run_plagiarism_streaming

router = APIRouter(tags=["plagiarism"])


@router.post("/plagiarism", response_model=ResearchResponse, dependencies=[Depends(rate_limit)])
async def start_plagiarism_check(payload: PlagiarismRequest, background_tasks: BackgroundTasks,
                                 user: User | None = Depends(get_optional_user)):
    """Starts a check and returns a session id. Progress and the result arrive on the same WebSocket
    as research runs: /api/v1/ws/research/{session_id}"""
    text = payload.text.strip()
    if len(text.split()) < 15:
        raise HTTPException(status_code=422, detail="Please paste at least about 15 words to check.")
    session_id = str(uuid.uuid4())
    await create_session(session_id=session_id, user_id=user.id if user else None, query=text[:200],
                         mode="plagiarism", input_kind="plagiarism")
    background_tasks.add_task(run_plagiarism_streaming, session_id, text, manager)
    return ResearchResponse(session_id=session_id, status="started", estimated_seconds=30)
