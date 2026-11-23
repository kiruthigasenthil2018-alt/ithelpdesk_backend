"""Database operations for incidents, conversations, escalations, reports and analytics.

Used by both the REST API and the MCP server so behaviour stays identical.
"""

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database.models import (
    Conversation, Escalation, Incident, IncidentEvent, Message, Report, Resolution, User,
)
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.schemas.report import IncidentReport
from app.services.cache import get_cache
from app.tools import mock_it

MINUTES_BY_PRIORITY = {"P1": 60, "P2": 45, "P3": 30, "P4": 15}
SLA_HOURS = {"P1": 1, "P2": 4, "P3": 8, "P4": 24}
STAFF_ROLES = ("agent", "admin")


class NotFoundError(Exception):
    pass


class ApprovalRequiredError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat them as UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def invalidate_stats() -> None:
    _touch()


def _touch() -> None:
    get_cache().delete_prefix("stats")


def _get(db: Session, incident_id: str) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} not found")
    return incident


def add_event(db: Session, incident_id: str, kind: str, message: str, actor: str = "system") -> None:
    db.add(IncidentEvent(incident_id=incident_id, kind=kind, message=message, actor=actor))


def _set_due(incident: Incident) -> None:
    if incident.priority in SLA_HOURS:
        base = aware(incident.created_at) or _now()
        incident.due_at = base + timedelta(hours=SLA_HOURS[incident.priority])


# ---------- users / incidents ----------
def get_or_create_user(db: Session, email: str | None, name: str | None) -> User | None:
    if not email:
        return None
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name or email.split("@")[0])
        db.add(user)
        db.flush()
    return user


def create_incident(db: Session, data: IncidentCreate, user: User | None = None,
                    type: str = "incident") -> Incident:
    reporter = user or get_or_create_user(db, data.reporter_email, data.reporter_name)
    incident = Incident(
        id=f"INC-{uuid.uuid4().hex[:8].upper()}",
        title=data.title,
        description=data.description,
        source=data.source,
        type=type,
        category=data.category.value if data.category else None,
        priority=data.priority.value if data.priority else None,
        reporter_id=reporter.id if reporter else None,
        created_at=_now(),
        sources=[],
        actions=[],
    )
    _set_due(incident)
    db.add(incident)
    db.flush()
    add_event(db, incident.id, "created", f"{type.capitalize()} created", reporter.name if reporter else "system")
    db.commit()
    _touch()
    return incident


def get_incident(db: Session, incident_id: str, viewer: User | None = None) -> Incident:
    incident = _get(db, incident_id)
    if viewer is not None and viewer.role not in STAFF_ROLES and incident.reporter_id != viewer.id:
        raise NotFoundError(f"Incident {incident_id} not found")  # don't reveal it exists
    return incident


def list_incidents(
    db: Session, status: str | None = None, category: str | None = None,
    priority: str | None = None, limit: int = 100, reporter_id: int | None = None,
    q: str | None = None,
) -> list[Incident]:
    stmt = select(Incident)
    if status:
        stmt = stmt.where(Incident.status == status)
    if category:
        stmt = stmt.where(Incident.category == category)
    if priority:
        stmt = stmt.where(Incident.priority == priority)
    if reporter_id is not None:
        stmt = stmt.where(Incident.reporter_id == reporter_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Incident.title.ilike(like), Incident.description.ilike(like), Incident.id.ilike(like)))
    stmt = stmt.order_by(Incident.priority.asc(), Incident.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def update_incident(db: Session, incident_id: str, data: IncidentUpdate, actor: str = "system") -> Incident:
    incident = _get(db, incident_id)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    resolution = changes.pop("resolution", None)
    for field, value in changes.items():
        value = value.value if hasattr(value, "value") else value
        if getattr(incident, field) != value:
            add_event(db, incident.id, "assigned" if field == "assigned_to" else "status",
                      f"{field.replace('_', ' ').capitalize()} changed to {value}", actor)
        setattr(incident, field, value)
    if "priority" in changes:
        _set_due(incident)
    if resolution:
        db.add(Resolution(incident_id=incident.id, summary=resolution, confirmed_by_user=False))
        add_event(db, incident.id, "status", f"Resolution recorded: {resolution[:200]}", actor)
        if incident.status not in ("resolved", "escalated"):
            incident.status = "resolved"
    if incident.status == "resolved" and incident.resolved_at is None:
        incident.resolved_at = _now()
    elif incident.status != "resolved":
        incident.resolved_at = None
    db.commit()
    _touch()
    return incident


def add_comment(db: Session, incident_id: str, actor: str, message: str) -> Incident:
    incident = _get(db, incident_id)
    add_event(db, incident.id, "comment", message, actor)
    db.commit()
    return incident


def apply_agent_result(db: Session, incident_id: str, state: dict) -> Incident:
    incident = _get(db, incident_id)
    first_time = incident.priority is None
    incident.category = state.get("category")
    incident.priority = state.get("priority")
    if first_time:
        _set_due(incident)
    incident.status = state.get("status", "in_progress")
    incident.recommendation = state.get("reply")
    incident.sources = [
        {k: d[k] for k in ("citation", "source", "page", "score", "category")}
        for d in state.get("documents", [])
    ]
    incident.actions = state.get("actions", [])
    add_event(db, incident.id, "ai",
              f"AI classified as {incident.category}/{incident.priority} and found {len(incident.sources)} source(s)",
              "AI assistant")
    if state.get("verified"):
        db.add(Resolution(incident_id=incident.id, summary=state.get("reply") or "", verified=True))
    if state.get("escalated"):
        db.add(Escalation(
            incident_id=incident.id,
            reason=state.get("escalation_reason", ""),
            escalated_to=state.get("escalated_to", "IT Service Desk (Tier 2)"),
        ))
        incident.assigned_to = state.get("escalated_to")
        add_event(db, incident.id, "escalated",
                  f"Escalated to {incident.assigned_to}: {state.get('escalation_reason', '')}", "AI assistant")
    db.commit()
    _touch()
    return incident


def escalate_incident(db: Session, incident_id: str, reason: str, team: str | None = None,
                      actor: str = "system") -> Incident:
    incident = _get(db, incident_id)
    team = team or mock_it.team_for(incident.category)
    db.add(Escalation(incident_id=incident.id, reason=reason, escalated_to=team))
    incident.status = "escalated"
    incident.assigned_to = team
    incident.resolved_at = None
    add_event(db, incident.id, "escalated", f"Escalated to {team}: {reason}", actor)
    db.commit()
    _touch()
    return incident


def submit_feedback(db: Session, incident_id: str, resolved: bool, comment: str | None,
                    rating: int | None = None, actor: str = "user") -> Incident:
    incident = _get(db, incident_id)
    if rating:
        incident.satisfaction = rating
    if resolved:
        db.add(Resolution(
            incident_id=incident.id, summary=incident.recommendation or (comment or "Resolved"),
            verified=True, confirmed_by_user=True,
        ))
        incident.status = "resolved"
        incident.resolved_at = _now()
        add_event(db, incident.id, "status", "User confirmed the issue is resolved", actor)
        db.commit()
        _touch()
        return incident
    db.commit()
    return escalate_incident(db, incident_id, comment or "User reported the fix did not work", actor=actor)


def run_action(db: Session, incident_id: str, action: str, approved_by: str | None = None,
               actor: str = "system") -> dict:
    """Execute an allowlisted mock action. Consequential ones need a named approver."""
    incident = _get(db, incident_id)
    if not mock_it.is_allowed(action):
        raise ValueError(f"Action '{action}' is not allowlisted")
    if mock_it.requires_approval(action) and not approved_by:
        raise ApprovalRequiredError(f"Action '{action}' requires human approval")
    result = mock_it.execute_action(action, incident_id)
    actions = [dict(a) for a in incident.actions or []]
    entry = next((a for a in actions if a["name"] == action), None)
    if entry is None:
        entry = {"name": action, "description": mock_it.ALLOWED_ACTIONS[action]["description"],
                 "requires_approval": mock_it.requires_approval(action)}
        actions.append(entry)
    entry.update(status="executed", result=result + (f" (approved by {approved_by})" if approved_by else ""))
    incident.actions = actions  # reassign so SQLAlchemy sees the JSON change
    add_event(db, incident.id, "action", entry["result"], actor)
    db.commit()
    _touch()
    return entry


# ---------- conversations ----------
def get_or_create_conversation(db: Session, conversation_id: str | None, user_id: int | None = None) -> Conversation:
    conv = db.get(Conversation, conversation_id) if conversation_id else None
    if conv is not None and conv.user_id not in (None, user_id):
        raise NotFoundError("Conversation not found")
    if conv is None:
        conv = Conversation(id=conversation_id or str(uuid.uuid4()), user_id=user_id)
        db.add(conv)
        db.flush()
    return conv


def add_message(db: Session, conversation_id: str, role: str, content: str) -> Message:
    msg = Message(conversation_id=conversation_id, role=role, content=content)
    db.add(msg)
    db.commit()
    return msg


def get_history(db: Session, conversation_id: str) -> list[Message]:
    return list(db.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    ))


# ---------- reports ----------
def generate_report(db: Session, incident_id: str, viewer: User | None = None) -> IncidentReport:
    incident = get_incident(db, incident_id, viewer)
    resolution = next((r.summary for r in reversed(incident.resolutions)), None)
    escalation = incident.escalations[-1] if incident.escalations else None
    report = IncidentReport(
        incident_id=incident.id,
        category=incident.category,
        priority=incident.priority,
        problem=incident.description,
        retrieved_sources=[s.get("citation", "") for s in incident.sources or []],
        actions=[a["name"] for a in incident.actions or []],
        resolution=resolution,
        status=incident.status,
        escalation_status=f"escalated to {escalation.escalated_to}" if escalation else "not_escalated",
        generated_at=_now().isoformat(),
    )
    db.add(Report(incident_id=incident.id, content=report.model_dump()))
    db.commit()
    return report


# ---------- dashboard & analytics ----------
def dashboard_stats(db: Session, reporter_id: int | None = None) -> dict:
    cache = get_cache()
    key = f"stats:dashboard:{reporter_id or 'all'}"
    cached = cache.get_json(key)
    if cached:
        return cached

    base = select(Incident)
    if reporter_id is not None:
        base = base.where(Incident.reporter_id == reporter_id)
    rows = list(db.scalars(base))
    cutoff = _now() - timedelta(hours=24)
    outstanding = [i for i in rows if i.status in ("open", "in_progress")]
    seconds = sum(MINUTES_BY_PRIORITY.get(i.priority or "P3", 30) for i in outstanding) * 60
    priority = {p: 0 for p in ("P1", "P2", "P3", "P4")}
    for i in outstanding:
        priority[i.priority or "P3"] += 1
    system = sum(1 for i in rows if i.source == "system")
    now = _now()
    breached = sum(1 for i in outstanding if i.due_at and aware(i.due_at) < now)
    stats = {
        "incoming": sum(1 for i in rows if aware(i.created_at) >= cutoff),
        "outstanding": len(outstanding),
        "total": len(rows),
        "resolved": sum(1 for i in rows if i.status == "resolved"),
        "escalated": sum(1 for i in rows if i.status == "escalated"),
        "sla_breached": breached,
        "estimated_time": f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}",
        "priority": priority,
        "source": {"system": system, "customer": len(rows) - system},
        "system_ratio": round(system / len(rows), 2) if rows else 0,
    }
    cache.set_json(key, stats, ttl=60)
    return stats


def analytics(db: Session, days: int = 7) -> dict:
    cache = get_cache()
    cached = cache.get_json(f"stats:analytics:{days}")
    if cached:
        return cached
    now = _now()
    rows = list(db.scalars(select(Incident).where(Incident.created_at >= now - timedelta(days=90))))
    day_labels = [(now - timedelta(days=d)).date() for d in range(days - 1, -1, -1)]
    created = Counter(aware(i.created_at).date() for i in rows)
    resolved = Counter(aware(i.resolved_at).date() for i in rows if i.resolved_at)
    done = [i for i in rows if i.resolved_at]
    mins = [(aware(i.resolved_at) - aware(i.created_at)).total_seconds() / 60 for i in done]
    closed = [i for i in rows if i.status in ("resolved", "escalated")]
    deflected = [i for i in rows if i.status == "resolved" and not i.escalations]
    sla_total = [i for i in rows if i.due_at]
    sla_ok = [
        i for i in sla_total
        if (i.resolved_at and aware(i.resolved_at) <= aware(i.due_at))
        or (not i.resolved_at and aware(i.due_at) >= now)
    ]
    rated = [i.satisfaction for i in rows if i.satisfaction]
    result = {
        "days": [d.isoformat() for d in day_labels],
        "created_per_day": [created.get(d, 0) for d in day_labels],
        "resolved_per_day": [resolved.get(d, 0) for d in day_labels],
        "by_category": dict(Counter(i.category or "unclassified" for i in rows)),
        "by_status": dict(Counter(i.status for i in rows)),
        "avg_resolution_minutes": round(sum(mins) / len(mins), 1) if mins else None,
        "ai_deflection_rate": round(len(deflected) / len(closed), 2) if closed else None,
        "sla_compliance": round(len(sla_ok) / len(sla_total), 2) if sla_total else None,
        "csat_average": round(sum(rated) / len(rated), 2) if rated else None,
        "total": len(rows),
    }
    cache.set_json(f"stats:analytics:{days}", result, ttl=60)
    return result


def recent_events(db: Session, viewer: User, limit: int = 20) -> list[dict]:
    stmt = select(IncidentEvent, Incident.title).join(Incident, Incident.id == IncidentEvent.incident_id)
    if viewer.role not in STAFF_ROLES:
        stmt = stmt.where(Incident.reporter_id == viewer.id)
    stmt = stmt.order_by(IncidentEvent.id.desc()).limit(limit)
    return [
        {"id": e.id, "incident_id": e.incident_id, "title": title, "kind": e.kind,
         "message": e.message, "actor": e.actor, "created_at": e.created_at.isoformat()}
        for e, title in db.execute(stmt)
    ]


def count_incidents(db: Session) -> int:
    return db.scalar(select(func.count(Incident.id))) or 0
