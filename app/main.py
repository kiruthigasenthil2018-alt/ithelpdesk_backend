import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import admin, attachments, auth, chat, health, incidents, knowledge, reports
from app.api.deps import get_retriever
from app.config import get_settings
from app.database.base import SessionLocal, init_db
from app.database.models import User
from app.services.security import _secret, hash_password

log = logging.getLogger("helpdesk")
settings = get_settings()


def seed_admin() -> None:
    if not (settings.admin_email and settings.admin_password):
        return
    with SessionLocal() as db:
        email = settings.admin_email.strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            db.add(User(email=email, name="Administrator", role="admin",
                        password_hash=hash_password(settings.admin_password)))
            db.commit()
            log.info("Admin account created: %s", email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _secret()  # fail fast if the production secret is missing or weak
    if settings.auto_create_tables:
        init_db()
    seed_admin()
    try:  # load the sample knowledge base the first time
        store = get_retriever().store
        if store.count() == 0 and Path(settings.knowledge_base_dir).exists():
            log.info("Ingesting knowledge base: %s", store.ingest_folder(Path(settings.knowledge_base_dir)))
    except Exception as exc:  # keep the API alive even if embeddings can't load
        log.warning("Knowledge base ingestion skipped: %s", exc)
    yield


app = FastAPI(
    title=settings.app_name,
    description="Autonomous IT Helpdesk & Incident Resolution Agent",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/auth"):
        response.headers["Cache-Control"] = "no-store"
    return response


for r in (health.router, auth.router, chat.router, incidents.router, reports.router,
          knowledge.router, admin.router, attachments.router):
    app.include_router(r)
