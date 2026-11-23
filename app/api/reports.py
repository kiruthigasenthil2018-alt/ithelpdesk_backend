from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth_deps import get_current_user
from app.database.base import get_db
from app.database.models import User
from app.schemas.report import IncidentReport
from app.services import incident_service as svc

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/{incident_id}", response_model=IncidentReport)
def get_report(incident_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return svc.generate_report(db, incident_id, user)
    except svc.NotFoundError as exc:
        raise HTTPException(404, str(exc))
