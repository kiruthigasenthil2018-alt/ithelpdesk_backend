from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.auth_deps import get_current_user
from app.config import get_settings
from app.database.base import get_db
from app.database.models import User
from app.services import attachments as att_svc
from app.services import incident_service as svc

router = APIRouter(tags=["Attachments"])


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{file.filename}: file too large (max {limit // (1024 * 1024)} MB)")
    if not data:
        raise HTTPException(400, f"{file.filename}: file is empty")
    return data


@router.post("/attachments")
async def upload(
    files: list[UploadFile] = File(...),
    incident_id: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = get_settings()
    if len(files) > s.max_files_per_request:
        raise HTTPException(400, f"Upload at most {s.max_files_per_request} files at a time")
    try:
        if incident_id:
            svc.get_incident(db, incident_id, user)  # access check
        saved = []
        for f in files:
            data = await _read_limited(f, s.max_upload_mb * 1024 * 1024)
            saved.append(att_svc.save_upload(db, user, f.filename, data))
        if incident_id:
            att_svc.link_to_incident(db, [a.id for a in saved], user, incident_id)
            svc.invalidate_stats()
    except svc.NotFoundError as exc:
        raise HTTPException(404, str(exc))
    return [att_svc.to_dict(a) for a in saved]


@router.get("/incidents/{incident_id}/attachments")
def list_attachments(incident_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        svc.get_incident(db, incident_id, user)
    except svc.NotFoundError as exc:
        raise HTTPException(404, str(exc))
    return [att_svc.to_dict(a) for a in att_svc.list_for_incident(db, incident_id)]


@router.get("/attachments/{attachment_id}/download")
def download(attachment_id: int, inline: bool = False, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    try:
        att = att_svc.get_for_user(db, attachment_id, user)
    except svc.NotFoundError as exc:
        raise HTTPException(404, str(exc))
    show = inline and att.content_type.startswith("image/")  # only verified images may display inline
    return FileResponse(
        att_svc.path_of(att), media_type=att.content_type, filename=att.filename,
        content_disposition_type="inline" if show else "attachment",
    )


@router.delete("/attachments/{attachment_id}")
def delete_attachment(attachment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        att_svc.delete(db, attachment_id, user)
    except svc.NotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {"deleted": attachment_id}
