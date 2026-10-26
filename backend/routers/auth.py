"""VerifAI — backend/routers/auth.py"""
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, delete

from models.schemas import RegisterRequest, LoginRequest, TokenResponse
from models.db_models import User
from services.session_store import async_session
from dependencies import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)
from config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
@router.post("/register")
async def register(payload: RegisterRequest):
    email = str(payload.email).strip().lower()

    async with async_session() as db:
        existing_user = (
            await db.execute(
                select(User).where(User.email == email)
            )
        ).scalar_one_or_none()

        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="Email already registered."
            )

        user = User(
            email=email,
            hashed_password=hash_password(payload.password),
            name=payload.name
        )

        db.add(user)
        await db.commit()
        await db.refresh(user)

        return {
            "id": user.id,
            "email": user.email,
            "name": user.name
        }


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    email = str(payload.email).strip().lower()

    async with async_session() as db:
        user = (
            await db.execute(
                select(User).where(User.email == email)
            )
        ).scalar_one_or_none()

        if not user or not verify_password(
            payload.password,
            user.hashed_password
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password."
            )

        return TokenResponse(
            access_token=create_access_token(str(user.id)),
            expires_in=settings.jwt_expire_minutes * 60
        )


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name
    }


# Development-only reset-token storage.
# Reset tokens expire after 15 minutes.
# For production, use a persistent database table or Redis.
_reset_tokens = {}


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20)
    new_password: str = Field(min_length=8, max_length=128)


# Temporary storage for local development only.
# Reset tokens disappear when the server restarts.
reset_tokens = {}


@router.post("/forgot-password")
async def forgot_password(payload: dict):
    email = str(payload.get("email", "")).strip().lower()

    if not email:
        raise HTTPException(
            status_code=400,
            detail="Please enter your email address."
        )

    async with async_session() as db:
        user = (
            await db.execute(
                select(User).where(User.email == email)
            )
        ).scalar_one_or_none()

    # Return a generic response so the endpoint does not
    # reveal whether an email is registered.
    message = (
        "If an account exists for this email, "
        "password-reset instructions have been generated."
    )

    if user is None:
        return {"message": message}

    # Generate a secure, temporary reset token.
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    reset_tokens[token_hash] = {
        "user_id": str(user.id),
        "expires_at": datetime.now(timezone.utc)
        + timedelta(minutes=15)
    }

    # LOCAL DEVELOPMENT ONLY:
    # Return the token so you can test the reset process.
    # In production, send a reset link to the user's email.
    return {
        "message": message,
        "reset_token": token
    }


@router.post("/reset-password")
async def reset_password(payload: dict):
    token = str(payload.get("token", "")).strip()
    new_password = str(payload.get("new_password", ""))

    if not token:
        raise HTTPException(
            status_code=400,
            detail="Reset token is required."
        )

    if len(new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least 8 characters."
        )

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    reset_data = reset_tokens.get(token_hash)

    if not reset_data:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired reset token."
        )

    if datetime.now(timezone.utc) >= reset_data["expires_at"]:
        reset_tokens.pop(token_hash, None)

        raise HTTPException(
            status_code=400,
            detail="Reset token has expired. Request a new one."
        )

    async with async_session() as db:
        user = await db.get(User, reset_data["user_id"])

        if user is None:
            reset_tokens.pop(token_hash, None)

            raise HTTPException(
                status_code=400,
                detail="User account was not found."
            )

        # Use your existing password-hashing function.
        user.hashed_password = hash_password(new_password)

        await db.commit()

    # A reset token can only be used once.
    reset_tokens.pop(token_hash, None)

    return {
        "message": "Password reset successfully. Please log in with your new password."
    }