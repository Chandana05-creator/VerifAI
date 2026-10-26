"""VerifAI — backend/models/schemas.py"""
from pydantic import BaseModel, EmailStr, Field


class ResearchRequest(BaseModel):
    query: str
    mode: str = "deep"   # deep | quick | factcheck


class ResearchResponse(BaseModel):
    session_id: str
    status: str
    estimated_seconds: int = 60


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PlagiarismRequest(BaseModel):
    text: str = Field(min_length=100, max_length=8000)


class UrlRequest(BaseModel):
    url: str
    mode: str = "deep"


class TextRequest(BaseModel):
    text: str
    mode: str = "deep"


class FeedbackRequest(BaseModel):
    session_id: str
    rating: int                      # +1 helpful, -1 not helpful
    claim_idx: int | None = None     # set to rate one claim's verdict instead of the whole report
    comment: str | None = None
