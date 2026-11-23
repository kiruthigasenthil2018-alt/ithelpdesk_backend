"""File attachments for chat and tickets.

Any file type is accepted, but safely:
- stored on disk under a random name (the user's file name is never used as a path)
- served as a download (octet-stream) unless the bytes really are a PNG/JPEG/GIF/WEBP image
- size and count limited; text is extracted only for AI context and treated as untrusted data
"""

import re
import uuid
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import Attachment, Incident, User
from app.services.incident_service import NotFoundError, add_event

TEXT_EXT = {".txt", ".log", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".ini", ".conf", ".cfg"}
MAX_EXTRACT_CHARS = 2500
SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


def _folder() -> Path:
    folder = Path(get_settings().upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def clean_name(name: str | None) -> str:
    name = Path((name or "file").replace("\\", "/")).name  # drop any directory part
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).strip(". ") or "file"
    return name[:150]


def sniff_image(data: bytes) -> str | None:
    for sig, mime in SIGNATURES:
        if data.startswith(sig):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def save_upload(db: Session, user: User, filename: str | None, data: bytes) -> Attachment:
    stored = uuid.uuid4().hex
    (_folder() / stored).write_bytes(data)
    att = Attachment(
        uploaded_by=user.id, filename=clean_name(filename), stored_name=stored,
        content_type=sniff_image(data) or "application/octet-stream", size=len(data),
    )
    db.add(att)
    db.commit()
    return att


def path_of(att: Attachment) -> Path:
    return _folder() / att.stored_name


def _can_see(db: Session, att: Attachment, user: User) -> bool:
    if user.role in ("agent", "admin") or att.uploaded_by == user.id:
        return True
    if att.incident_id:
        inc = db.get(Incident, att.incident_id)
        return bool(inc and inc.reporter_id == user.id)
    return False


def get_for_user(db: Session, attachment_id: int, user: User) -> Attachment:
    att = db.get(Attachment, attachment_id)
    if att is None or not _can_see(db, att, user):
        raise NotFoundError("Attachment not found")
    return att


def link_to_incident(db: Session, ids: list[int], user: User, incident_id: str) -> list[Attachment]:
    """Attach staged uploads (owned by this user, not yet linked) to a ticket."""
    if not ids:
        return []
    rows = list(db.scalars(select(Attachment).where(
        Attachment.id.in_(ids), Attachment.uploaded_by == user.id, Attachment.incident_id.is_(None))))
    for att in rows:
        att.incident_id = incident_id
        add_event(db, incident_id, "comment", f"Attached file: {att.filename}", user.name)
    db.commit()
    return rows


def list_for_incident(db: Session, incident_id: str) -> list[Attachment]:
    return list(db.scalars(select(Attachment).where(Attachment.incident_id == incident_id).order_by(Attachment.id)))


def delete(db: Session, attachment_id: int, user: User) -> None:
    att = get_for_user(db, attachment_id, user)
    if att.uploaded_by != user.id and user.role not in ("agent", "admin"):
        raise NotFoundError("Attachment not found")
    path_of(att).unlink(missing_ok=True)
    db.delete(att)
    db.commit()


def extract_text(atts: list[Attachment]) -> str:
    """Short excerpts of text/PDF files so the AI can read logs and error files."""
    parts = []
    for att in atts:
        ext = Path(att.filename).suffix.lower()
        try:
            if ext in TEXT_EXT:
                text = path_of(att).read_text(encoding="utf-8", errors="ignore")
            elif ext == ".pdf":
                reader = PdfReader(str(path_of(att)))
                text = "\n".join((p.extract_text() or "") for p in reader.pages[:3])
            else:
                continue
        except Exception:
            continue
        text = text.strip()[:MAX_EXTRACT_CHARS]
        if text:
            parts.append(f"--- {att.filename} ---\n{text}")
    return "\n\n".join(parts)


def to_dict(att: Attachment) -> dict:
    return {"id": att.id, "filename": att.filename, "size": att.size, "content_type": att.content_type,
            "is_image": att.content_type.startswith("image/"), "incident_id": att.incident_id, "uploaded_by": att.uploaded_by,
            "created_at": att.created_at.isoformat() if att.created_at else None}
