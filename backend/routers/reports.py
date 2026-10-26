"""VerifAI — backend/routers/reports.py — view, export and share saved reports.

Access rule: a run made while logged in belongs to that user. A run made anonymously can be opened by
anyone who knows its (random, unguessable) id. Shared links work for everyone but are read-only."""
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from dependencies import get_optional_user
from models.db_models import User
from services import export_service
from services.session_store import get_session, get_by_share_token, set_share_token, kind_of

router = APIRouter(tags=["reports"])


def _owner(s, user) -> bool:
    return s.user_id is None or (user is not None and user.id == s.user_id)


async def _load(session_id: str, user: User | None):
    s = await get_session(session_id)
    if not s or not _owner(s, user):
        raise HTTPException(status_code=404, detail="Report not found")
    return s


def _view(s, owner: bool) -> dict:
    return {"id": s.id, "query": s.query, "kind": kind_of(s), "created_at": s.created_at.isoformat(),
            "report": s.final_report, "metrics": s.metrics if owner else None, "is_owner": owner,
            "share_token": s.share_token if owner else None}


@router.get("/reports/{session_id}")
async def get_report(session_id: str, user: User | None = Depends(get_optional_user)):
    return _view(await _load(session_id, user), True)


@router.get("/reports/{session_id}/export")
async def export_report(session_id: str, format: str = Query("md", pattern="^(md|pdf)$"),
                        user: User | None = Depends(get_optional_user)):
    s = await _load(session_id, user)
    if not s.final_report:
        raise HTTPException(status_code=409, detail="This run has no report to export.")
    kind, created = kind_of(s), s.created_at.strftime("%d %b %Y, %H:%M UTC")
    if format == "pdf":
        data = export_service.to_pdf(kind, s.query, created, s.final_report, s.metrics)
        media, ext = "application/pdf", "pdf"
    else:
        data = export_service.to_markdown(kind, s.query, created, s.final_report, s.metrics).encode("utf-8")
        media, ext = "text/markdown; charset=utf-8", "md"
    name = export_service.filename(kind, s.query, ext)
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/reports/{session_id}/share")
async def create_share_link(session_id: str, user: User | None = Depends(get_optional_user)):
    s = await _load(session_id, user)
    if not s.final_report:
        raise HTTPException(status_code=409, detail="This run has no report to share yet.")
    token = s.share_token or secrets.token_urlsafe(12)
    await set_share_token(s.id, token)
    return {"token": token, "path": f"/ui/report.html?share={token}"}


@router.delete("/reports/{session_id}/share")
async def revoke_share_link(session_id: str, user: User | None = Depends(get_optional_user)):
    s = await _load(session_id, user)
    await set_share_token(s.id, None)
    return {"revoked": True}


@router.get("/share/{token}")
async def get_shared_report(token: str):
    s = await get_by_share_token(token)
    if not s or not s.final_report:
        raise HTTPException(status_code=404, detail="This shared link is not valid any more.")
    return _view(s, False)
