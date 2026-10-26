"""VerifAI — backend/services/session_store.py"""
from datetime import datetime
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from models.db_models import Base, ResearchSession, Feedback
from config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


def _upgrade_schema(conn) -> None:
    """Add columns introduced in newer versions to tables that already exist (no data is lost)."""
    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in existing:
                ddl = col.type.compile(dialect=conn.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}'))
                print(f"[VerifAI] Database upgraded: added {table.name}.{col.name}")
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_research_sessions_share_token "
                      "ON research_sessions (share_token)"))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_upgrade_schema)
    print(f"[VerifAI] Database ready ({engine.url.get_backend_name()})")


def kind_of(s: ResearchSession) -> str:
    return s.input_kind or ("plagiarism" if s.mode == "plagiarism" else "question")


async def create_session(session_id: str, user_id: str | None, query: str, mode: str,
                         input_kind: str = "question") -> None:
    async with async_session() as db:
        db.add(ResearchSession(id=session_id, user_id=user_id, query=query, mode=mode, input_kind=input_kind))
        await db.commit()


async def update_session(session_id: str, final_report: dict | None = None, claim_count: int | None = None,
                         avg_confidence: float | None = None, metrics: dict | None = None) -> None:
    async with async_session() as db:
        row = await db.get(ResearchSession, session_id)
        if not row:
            return
        if final_report is not None:
            row.final_report = final_report
        if claim_count is not None:
            row.claim_count = claim_count
        if avg_confidence is not None:
            row.avg_confidence = avg_confidence
        if metrics is not None:
            row.metrics = metrics
        await db.commit()


async def get_sessions(user_id: str, page: int = 1, limit: int = 20) -> list[ResearchSession]:
    async with async_session() as db:
        result = await db.execute(
            select(ResearchSession).where(ResearchSession.user_id == user_id)
            .order_by(ResearchSession.created_at.desc()).offset((page - 1) * limit).limit(limit))
        return list(result.scalars().all())


async def get_session(session_id: str) -> ResearchSession | None:
    async with async_session() as db:
        return await db.get(ResearchSession, session_id)


async def set_share_token(session_id: str, token: str | None) -> None:
    async with async_session() as db:
        row = await db.get(ResearchSession, session_id)
        if row:
            row.share_token = token
            await db.commit()


async def get_by_share_token(token: str) -> ResearchSession | None:
    async with async_session() as db:
        result = await db.execute(select(ResearchSession).where(ResearchSession.share_token == token))
        return result.scalar_one_or_none()


async def add_feedback(session_id: str, rating: int, claim_idx: int | None, comment: str | None,
                       user_id: str | None) -> int:
    async with async_session() as db:
        fb = Feedback(session_id=session_id, rating=rating, claim_idx=claim_idx,
                      comment=(comment or "")[:500] or None, user_id=user_id)
        db.add(fb)
        await db.commit()
        return fb.id


async def recent_sessions(limit: int = 500) -> list[ResearchSession]:
    async with async_session() as db:
        result = await db.execute(select(ResearchSession).order_by(ResearchSession.created_at.desc()).limit(limit))
        return list(result.scalars().all())


async def recent_feedback(limit: int = 500) -> list[Feedback]:
    async with async_session() as db:
        result = await db.execute(select(Feedback).order_by(Feedback.created_at.desc()).limit(limit))
        return list(result.scalars().all())


async def delete_session(session_id: str) -> None:
    from sqlalchemy import delete
    async with async_session() as db:
        await db.execute(delete(Feedback).where(Feedback.session_id == session_id))
        await db.execute(delete(ResearchSession).where(ResearchSession.id == session_id))
        await db.commit()
