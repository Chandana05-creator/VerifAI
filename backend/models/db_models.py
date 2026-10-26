"""VerifAI — backend/models/db_models.py"""
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSON column that is JSONB on PostgreSQL and plain JSON on SQLite
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResearchSession(Base):
    """One run of the pipeline: a question / URL / text / image fact-check, or a plagiarism check."""
    __tablename__ = "research_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    query: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String, default="deep")
    final_report: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # added in v3 (existing databases are upgraded automatically, see session_store.init_db)
    input_kind: Mapped[str | None] = mapped_column(String, nullable=True, default="question")
    metrics: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    share_token: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    claim_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[int] = mapped_column(Integer)          # +1 helpful / -1 not helpful
    comment: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
