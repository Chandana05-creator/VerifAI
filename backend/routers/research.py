"""VerifAI — backend/routers/research.py"""

import asyncio
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

from dependencies import get_optional_user
from models.db_models import User
from models.schemas import ResearchRequest, ResearchResponse, TextRequest, UrlRequest
from services.inputs import put
from services.session_store import create_session
from services.ws_manager import manager
from agents.pipeline import run_pipeline_streaming


router = APIRouter(tags=["research"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}


async def _start_input(
    query: str,
    mode: str,
    input_kind: str,
    input_value: str,
    background_tasks: BackgroundTasks,
    current_user: User | None,
) -> ResearchResponse:
    session_id = str(uuid.uuid4())

    await create_session(
        session_id=session_id,
        user_id=str(current_user.id) if current_user else None,
        query=query,
        mode=mode,
        input_kind=input_kind,
    )

    background_tasks.add_task(
        run_pipeline_streaming,
        session_id,
        query,
        mode,
        manager,
        input_kind,
        input_value,
    )

    return ResearchResponse(session_id=session_id, status="started")


@router.post("/research", response_model=ResearchResponse)
async def start_research(
    payload: ResearchRequest,
    background_tasks: BackgroundTasks,
    current_user: User | None = Depends(get_optional_user),
):
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Please enter a question to research.")

    return await _start_input(
        query, payload.mode, "question", query, background_tasks, current_user
    )


@router.post("/research/url", response_model=ResearchResponse)
async def start_url_research(
    payload: UrlRequest,
    background_tasks: BackgroundTasks,
    current_user: User | None = Depends(get_optional_user),
):
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Please enter a valid HTTP or HTTPS URL.")

    return await _start_input(
        url, payload.mode, "url", url, background_tasks, current_user
    )


@router.post("/research/text", response_model=ResearchResponse)
async def start_text_research(
    payload: TextRequest,
    background_tasks: BackgroundTasks,
    current_user: User | None = Depends(get_optional_user),
):
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Please enter text to verify.")

    text = text[:8000]
    return await _start_input(
        text, payload.mode, "text", text, background_tasks, current_user
    )


@router.post("/research/image", response_model=ResearchResponse)
async def start_image_research(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = Form("deep"),
    current_user: User | None = Depends(get_optional_user),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Upload a JPG, PNG, WEBP, or GIF image.",
        )

    data = await file.read(MAX_IMAGE_BYTES + 1)
    await file.close()

    if not data:
        raise HTTPException(status_code=422, detail="The uploaded image is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="The image must be 10 MB or smaller.")

    session_id = str(uuid.uuid4())
    filename = file.filename or "Uploaded image"
    query = f"Verify claims in uploaded image: {filename}"

    await create_session(
        session_id=session_id,
        user_id=str(current_user.id) if current_user else None,
        query=query,
        mode=mode,
        input_kind="image",
    )

    put(
        session_id,
        {
            "data": data,
            "mime": file.content_type,
            "filename": filename,
        },
    )

    background_tasks.add_task(
        run_pipeline_streaming,
        session_id,
        query,
        mode,
        manager,
        "image",
        "",
    )

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
