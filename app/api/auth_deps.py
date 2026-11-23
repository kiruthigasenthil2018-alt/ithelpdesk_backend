from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.base import get_db
from app.database.models import User
from app.services.security import decode_token, limiter

bearer = HTTPBearer(auto_error=False)
STAFF = ("agent", "admin")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    unauthorized = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    payload = decode_token(creds.credentials)
    if not payload:
        raise unauthorized
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have permission to do this")
        return user

    return checker


def is_staff(user: User) -> bool:
    return user.role in STAFF


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def chat_rate_limit(request: Request, user: User = Depends(get_current_user)) -> User:
    if not limiter.allow(f"chat:{user.id}", get_settings().rate_limit_chat_per_min):
        raise HTTPException(429, "Too many messages. Please wait a minute.")
    return user
