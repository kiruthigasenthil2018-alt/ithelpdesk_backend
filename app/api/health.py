from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_llm_client, get_retriever
from app.config import get_settings
from app.database.base import get_db
from app.services.cache import get_cache

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check(
    db: Session = Depends(get_db), llm=Depends(get_llm_client), retriever=Depends(get_retriever)
) -> dict:
    s = get_settings()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    cache = get_cache()
    try:
        kb_chunks = retriever.store.count()
    except Exception:
        kb_chunks = -1
    ok = db_ok and cache.ping()
    return {
        "status": "ok" if ok else "degraded",
        "app": s.app_name,
        "database": "up" if db_ok else "down",
        "cache": {"backend": cache.backend, "up": cache.ping()},
        "knowledge_chunks": kb_chunks,
        "llm_configured": llm.available,
        "llm_providers": [p["provider"] for p in llm.status() if p["configured"]] if hasattr(llm, "status") else [],
    }
