from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth_deps import client_ip, get_current_user
from app.config import get_settings
from app.database.base import get_db
from app.database.models import User
from app.services.security import (
    check_password_policy, create_token, hash_password, limiter, valid_email, verify_password,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=200)
    password: str = Field(max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: str
    is_active: bool = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


@router.post("/register", response_model=TokenOut, status_code=201)
def register(data: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    if not limiter.allow(f"register:{client_ip(request)}", s.rate_limit_register_per_min):
        raise HTTPException(429, "Too many attempts. Try again later.")
    email = data.email.strip().lower()
    if not valid_email(email):
        raise HTTPException(422, "Invalid email address")
    if (msg := check_password_policy(data.password)):
        raise HTTPException(422, msg)
    existing = db.scalar(select(User).where(User.email == email))
    if existing and existing.password_hash:
        raise HTTPException(409, "An account with this email already exists")
    user = existing or User(email=email, name=data.name.strip())  # adopt tickets created by email
    user.name, user.role = data.name.strip(), user.role or "employee"
    user.password_hash = hash_password(data.password)
    db.add(user)
    db.commit()
    return TokenOut(access_token=create_token(user.id, user.role), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    if not limiter.allow(f"login:{client_ip(request)}", s.rate_limit_login_per_min):
        raise HTTPException(429, "Too many login attempts. Try again in a minute.")
    generic = HTTPException(401, "Invalid email or password")  # same message for every failure
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if user is None or not user.is_active or not user.password_hash:
        verify_password(data.password, None)
        raise generic
    now = datetime.now(timezone.utc)
    locked = _aware(user.locked_until)
    if locked and locked > now:
        raise HTTPException(423, "Account temporarily locked. Try again later.")
    if not verify_password(data.password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= s.login_max_attempts:
            user.locked_until = now + timedelta(minutes=s.lockout_minutes)
            user.failed_attempts = 0
        db.commit()
        raise generic
    user.failed_attempts, user.locked_until = 0, None
    db.commit()
    return TokenOut(access_token=create_token(user.id, user.role), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
