"""Password hashing, JWT tokens, password policy and a simple rate limiter."""

import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt

from app.config import get_settings

log = logging.getLogger(__name__)
ALGORITHM = "HS256"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- passwords (scrypt from the standard library) ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def check_password_policy(password: str) -> str | None:
    """Return an error message, or None if the password is acceptable."""
    if len(password) < 10:
        return "Password must be at least 10 characters"
    if len(password) > 128:
        return "Password is too long"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain letters and digits"
    return None


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email)) and len(email) <= 200


# ---------- JWT ----------
@lru_cache
def _secret() -> str:
    s = get_settings()
    if s.secret_key:
        if len(s.secret_key) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 characters")
        return s.secret_key
    if s.app_env == "production":
        raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
    log.warning("SECRET_KEY not set: using a temporary key. Logins will reset on every restart.")
    return secrets.token_urlsafe(48)


def create_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=get_settings().access_token_minutes)
    return jwt.encode({"sub": str(user_id), "role": role, "exp": exp}, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------- rate limiter (in-memory, per process) ----------
class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: int = 60) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
