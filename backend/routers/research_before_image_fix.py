"""VerifAI — backend/routers/research.py"""
import uuid
import asyncio

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    BackgroundTasks,
    UploadFile,
    File,
    Form,
    HTTPException,
)

from models.schemas import ResearchRequest, ResearchResponse
from services.ws_manager import manager
from services.session_store import create_session
from services.inputs import inputs
from agents.pipeline import run_pipeline_streaming


@router.post("/research", response_model=ResearchResponse)
async def start_research(payload: ResearchRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    await create_session(session_id=session_id, user_id=None, query=payload.query, mode=payload.mode)
    background_tasks.add_task(run_pipeline_streaming, session_id, payload.query, payload.mode, manager)
    return ResearchResponse(session_id=session_id, status="started")


@router.websocket("/ws/research/{session_id}")
async def research_ws(websocket: WebSocket, session_id: str):
    await manager.connect(session_id, websocket)
    keep_alive_task = asyncio.create_task(manager.keep_alive(session_id))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        keep_alive_task.cancel()
        manager.disconnect(session_id)
