"""Load PDF/TXT files, extract metadata and split them into chunks."""

from datetime import datetime, timezone
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.config import get_settings

SUPPORTED = {".pdf", ".txt", ".md"}

CATEGORY_KEYWORDS = {
    "network": ["vpn", "wifi", "wi-fi", "network", "dns", "internet", "ethernet", "router"],
    "hardware": ["printer", "laptop", "monitor", "keyboard", "battery", "hardware", "usb"],
    "software": ["install", "software", "application", "crash", "update", "office", "outlook"],
    "account": ["password", "account", "login", "locked", "mfa", "access", "sso"],
    "security": ["phishing", "malware", "virus", "ransomware", "security", "suspicious"],
}


class IngestionError(Exception):
    pass


def infer_category(text: str, filename: str = "") -> str:
    """Count keyword hits per category (filename counts triple). Falls back to 'general'."""
    haystack = text.lower()
    best, best_score = "general", 0
    for cat, words in CATEGORY_KEYWORDS.items():
        score = sum(haystack.count(w) for w in words) + 3 * sum(
            filename.lower().count(w) for w in words
        )
        if score > best_score:
            best, best_score = cat, score
    return best


def load_pages(path: Path) -> list[tuple[int, str]]:
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise IngestionError(f"Unsupported file type: {ext}. Use PDF, TXT or MD.")
    try:
        if ext == ".pdf":
            reader = PdfReader(str(path))
            pages = [(i + 1, (p.extract_text() or "")) for i, p in enumerate(reader.pages)]
        else:
            pages = [(1, path.read_text(encoding="utf-8", errors="ignore"))]
    except Exception as exc:
        raise IngestionError(f"Could not read {path.name}: {exc}") from exc
    pages = [(n, t) for n, t in pages if t.strip()]
    if not pages:
        raise IngestionError(f"No readable text found in {path.name}")
    return pages


def build_chunks(path: Path) -> list[dict]:
    """Return [{id, text, metadata}] for one file."""
    s = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=s.chunk_size, chunk_overlap=s.chunk_overlap
    )
    pages = load_pages(path)
    full_text = "\n".join(t for _, t in pages)
    category = infer_category(full_text, path.name)
    title = next((ln.strip("# ").strip() for ln in full_text.splitlines() if ln.strip()), path.stem)
    ingested_at = datetime.now(timezone.utc).isoformat()

    chunks: list[dict] = []
    idx = 0
    for page_no, text in pages:
        for piece in splitter.split_text(text):
            chunks.append(
                {
                    "id": f"{path.name}:{idx}",
                    "text": piece,
                    "metadata": {
                        "source": path.name,
                        "title": title[:150],
                        "page": page_no,
                        "chunk_index": idx,
                        "category": category,
                        "doc_type": path.suffix.lower().lstrip("."),
                        "ingested_at": ingested_at,
                    },
                }
            )
            idx += 1
    return chunks
