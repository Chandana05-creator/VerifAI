"""VerifAI — backend/config.py
Settings are read from environment variables or from a .env file placed either in the
project root (verifai/.env) or in backend/. Both locations work, wherever you start from.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "VerifAI"

    # API keys
    gemini_api_key: str = ""
    tavily_api_key: str = ""

    # Gemini model names (run `python list_models.py` to see what your key can use)
    gemini_model_strong: str = "gemini-2.5-flash"
    gemini_model_fast: str = "gemini-2.5-flash-lite"

    # Database: SQLite file by default (no setup needed). For PostgreSQL use e.g.
    # postgresql+asyncpg://verifai:verifai@localhost:5432/verifai
    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'verifai.db').as_posix()}"
    chroma_path: str = str(BACKEND_DIR / "chroma_db")

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # Pipeline behaviour
    confidence_threshold: float = 0.60
    max_research_loops: int = 2
    max_claims: int = 5               # claims verified per run (keep low on free API tiers)
    factcheck_concurrency: int = 3    # simultaneous claim verifications
    top_k_results: int = 6

    # Plagiarism checker
    plagiarism_max_queries: int = 8       # web searches per check (one per passage); keeps API usage low
    plagiarism_concurrency: int = 3
    plagiarism_verbatim: float = 0.60     # overlap at/above this = copied (near word-for-word)
    plagiarism_partial: float = 0.30      # overlap at/above this = partial overlap
    plagiarism_min_chars: int = 100
    plagiarism_max_chars: int = 8000

    # Critic agent, extra input types, limits
    enable_critic: bool = True            # the Critic agent runs in "deep" mode
    critic_max_claims: int = 3            # claims challenged per run (keeps API usage low)
    max_article_chars: int = 8000         # text sent to the fact-checker for URL / text / image inputs
    max_upload_mb: int = 5
    allow_private_urls: bool = False      # keep False: blocks fetching localhost / private network addresses
    runs_per_minute: int = 8              # per-IP limit on endpoints that start a run (protects API quota)

    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    embed_model: str = "BAAI/bge-small-en-v1.5"

    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000"


settings = Settings()
