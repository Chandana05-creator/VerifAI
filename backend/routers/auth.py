"""VerifAI — backend/routers/auth.py"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from models.schemas import RegisterRequest, LoginRequest, TokenResponse
from models.db_models import User
from services.session_store import async_session
from dependencies import hash_password, verify_password, create_access_token, get_current_user
from config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
async def register(payload: RegisterRequest):
    async with async_session() as db:
        if (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")
        user = User(email=payload.email, hashed_password=hash_password(payload.password), name=payload.name)
        db.add(user)
        await db.commit()
        return {"id": user.id, "email": user.email, "name": user.name}


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
        if not user or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return TokenResponse(access_token=create_access_token(user.id), expires_in=settings.jwt_expire_minutes * 60)


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email, "name": current_user.name}
