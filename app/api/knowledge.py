import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.api.auth_deps import get_current_user, require_roles
from app.api.deps import get_retriever
from app.config import get_settings
from app.database.models import User
from app.rag.ingestion import SUPPORTED, IngestionError, load_pages
from app.services.cache import get_cache

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])
MAX_UPLOAD = 10 * 1024 * 1024
CATEGORY_PATTERN = "^(network|hardware|software|account|security|general)$"


def _kb_dir() -> Path:
    return Path(get_settings().knowledge_base_dir)


@router.get("/search")
def search(
    q: str = Query(min_length=2, max_length=500),
    category: str | None = Query(None, pattern=CATEGORY_PATTERN),
    strategy: str = Query("mmr", pattern="^(mmr|similarity)$"),
    rerank: bool = True,
    k: int = Query(4, ge=1, le=10),
    user: User = Depends(get_current_user),
    retriever=Depends(get_retriever),
):
    cache = get_cache()
    key = "rag:" + hashlib.sha1(f"{q}|{category}|{strategy}|{rerank}|{k}".encode()).hexdigest()
    cached = cache.get_json(key)
    if cached is not None:
        return {"cached": True, "results": cached}
    results = retriever.search(q, k=k, category=category, strategy=strategy, rerank=rerank)
    cache.set_json(key, results)
    return {"cached": False, "results": results}


@router.get("/articles")
def list_articles(user: User = Depends(get_current_user), retriever=Depends(get_retriever)):
    """One entry per ingested document (title, category, chunk count)."""
    data = retriever.store.collection.get(include=["metadatas"])
    docs: dict[str, dict] = {}
    for m in data["metadatas"] or []:
        d = docs.setdefault(m["source"], {"source": m["source"], "title": m.get("title", m["source"]),
                                          "category": m["category"], "doc_type": m["doc_type"], "chunks": 0})
        d["chunks"] += 1
    return sorted(docs.values(), key=lambda d: d["title"].lower())


@router.get("/articles/{source}")
def get_article(source: str, user: User = Depends(get_current_user)):
    path = _kb_dir() / Path(source).name  # strip directories: blocks path traversal
    if not path.is_file() or path.suffix.lower() not in SUPPORTED:
        raise HTTPException(404, "Article not found")
    try:
        pages = load_pages(path)
    except IngestionError as exc:
        raise HTTPException(422, str(exc))
    return {"source": path.name, "content": "\n\n".join(t for _, t in pages)}


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    user: User = Depends(require_roles("admin")),
    retriever=Depends(get_retriever),
):
    name = Path(file.filename or "").name  # strip any directory parts
    if Path(name).suffix.lower() not in SUPPORTED:
        raise HTTPException(400, "Only PDF, TXT or MD files are supported")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 10 MB)")
    folder = _kb_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_bytes(data)
    try:
        chunks = retriever.store.ingest_file(target)
    except IngestionError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(422, str(exc))
    get_cache().delete_prefix("rag:")
    return {"file": name, "chunks": chunks}


@router.post("/reindex")
def reindex(user: User = Depends(require_roles("admin")), retriever=Depends(get_retriever)):
    report = retriever.store.ingest_folder(_kb_dir())
    get_cache().delete_prefix("rag:")
    return report
