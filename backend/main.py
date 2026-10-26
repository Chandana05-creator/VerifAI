"""
VerifAI — backend/main.py
An Integrated Multi-Agent System for Real-Time Research, Fact-Checking, and Bias Detection.
"""
import os
# quieten harmless warnings from third-party libraries (must be set before they are imported)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from routers import research, auth, history, health, plagiarism, reports, feedback, analytics
from services.vector_store import init_chroma
from services.session_store import init_db

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[VerifAI] Starting up…")
    await init_db()
    await init_chroma()
    print("[VerifAI] Ready — open http://localhost:8000/ in your browser")
    yield
    print("[VerifAI] Shutting down")


app = FastAPI(title="VerifAI", version="1.0.0", lifespan=lifespan,
              description="An Integrated Multi-Agent System for Real-Time Research, Fact-Checking, and Bias Detection")

app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(research.router, prefix="/api/v1")
app.include_router(plagiarism.router, prefix="/api/v1")
app.include_router(history.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")

if FRONTEND_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/ui/" if FRONTEND_DIR.exists() else "/docs")
