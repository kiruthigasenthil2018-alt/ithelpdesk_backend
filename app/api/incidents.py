from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth_deps import get_current_user, is_staff, require_roles
from app.database.base import get_db
from app.database.models import User
from app.schemas.incident import (
    CommentCreate, Feedback, IncidentCreate, IncidentDetail, IncidentOut, IncidentUpdate,
)
from app.services import catalog
from app.services import incident_service as svc
from app.tools import mock_it

router = APIRouter(tags=["Incidents"])


def _guard(fn):
    """Translate service errors to HTTP errors."""
    try:
        return fn()
    except svc.NotFoundError as exc:
        raise HTTPException(404, str(exc))
    except svc.ApprovalRequiredError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class ActionRequest(BaseModel):
    approved_by: str | None = Field(default=None, max_length=100)  # ignored: approver is the logged-in admin


class EscalateRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    team: str | None = Field(default=None, max_length=100)


class CatalogRequest(BaseModel):
    details: str = Field(default="", max_length=3000)


@router.post("/incidents", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
def create_incident(data: IncidentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data.source = "customer"  # only the system itself may create system-sourced tickets
    return svc.create_incident(db, data, user=user)


@router.get("/incidents", response_model=list[IncidentOut])
def list_incidents(
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reporter = None if is_staff(user) else user.id  # employees only see their own tickets
    return svc.list_incidents(db, status, category, priority, limit, reporter, q)


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _guard(lambda: svc.get_incident(db, incident_id, user))


@router.patch("/incidents/{incident_id}", response_model=IncidentOut)
def update_incident(
    incident_id: str, data: IncidentUpdate,
    user: User = Depends(require_roles("agent", "admin")), db: Session = Depends(get_db),
):
    return _guard(lambda: svc.update_incident(db, incident_id, data, actor=user.name))


@router.post("/incidents/{incident_id}/comments", response_model=IncidentDetail)
def comment(incident_id: str, data: CommentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    def work():
        svc.get_incident(db, incident_id, user)  # access check
        return svc.add_comment(db, incident_id, user.name, data.message)
    return _guard(work)


@router.post("/incidents/{incident_id}/feedback", response_model=IncidentOut)
def feedback(incident_id: str, data: Feedback, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    def work():
        svc.get_incident(db, incident_id, user)
        return svc.submit_feedback(db, incident_id, data.resolved, data.comment, data.rating, user.name)
    return _guard(work)


@router.post("/incidents/{incident_id}/escalate", response_model=IncidentOut)
def escalate(incident_id: str, data: EscalateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    def work():
        svc.get_incident(db, incident_id, user)
        return svc.escalate_incident(db, incident_id, data.reason, data.team, user.name)
    return _guard(work)


@router.post("/incidents/{incident_id}/actions/{action}/execute")
def execute_action(
    incident_id: str, action: str, data: ActionRequest,
    user: User = Depends(require_roles("agent", "admin")), db: Session = Depends(get_db),
):
    # Consequential actions: only an admin can approve. The approver is the authenticated admin.
    approver = user.name if user.role == "admin" else None
    if action in mock_it.ALLOWED_ACTIONS and mock_it.requires_approval(action) and approver is None:
        raise HTTPException(403, f"Action '{action}' requires approval from an admin")
    return _guard(lambda: svc.run_action(db, incident_id, action, approver, actor=user.name))


@router.get("/catalog")
def list_catalog(user: User = Depends(get_current_user)):
    return catalog.CATALOG


@router.post("/catalog/{item_id}/request", response_model=IncidentOut, status_code=201)
def request_item(item_id: str, data: CatalogRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = catalog.get_item(item_id)
    if item is None:
        raise HTTPException(404, "Catalog item not found")
    details = data.details.strip() or "No extra details provided."
    return svc.create_incident(
        db,
        IncidentCreate(title=item["name"], description=details.ljust(5, "."),
                       category=item["category"], priority=item["priority"]),
        user=user, type="request",
    )


@router.get("/dashboard/stats")
def dashboard_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.dashboard_stats(db, None if is_staff(user) else user.id)


@router.get("/analytics")
def analytics(days: int = Query(7, ge=3, le=30), user: User = Depends(require_roles("agent", "admin")),
              db: Session = Depends(get_db)):
    return svc.analytics(db, days)


@router.get("/notifications")
def notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.recent_events(db, user)
