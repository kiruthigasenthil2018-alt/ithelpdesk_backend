"""MCP server exposing the helpdesk as tools for AI clients.

Run (stdio):  python -m app.tools.mcp_server
All IT operations are mocked. Consequential actions need a named human approver.
"""

from contextlib import contextmanager
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from app.api.deps import get_retriever
from app.database.base import SessionLocal, init_db
from app.schemas.incident import Category, IncidentCreate, IncidentStatus, IncidentUpdate, Priority
from app.services import incident_service as svc
from app.tools import mock_it

mcp = FastMCP("it-helpdesk")


@contextmanager
def _db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ticket(i) -> dict:
    return {
        "id": i.id, "title": i.title, "category": i.category, "priority": i.priority,
        "status": i.status, "assigned_to": i.assigned_to, "recommendation": i.recommendation,
        "sources": i.sources, "actions": i.actions,
    }


def _safe(fn):
    try:
        return fn()
    except svc.NotFoundError as exc:
        return {"error": str(exc)}
    except svc.ApprovalRequiredError as exc:
        return {"status": "pending_approval", "error": str(exc)}
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def search_knowledge(
    query: Annotated[str, Field(min_length=2, max_length=500)],
    category: Category | None = None,
    k: Annotated[int, Field(ge=1, le=10)] = 4,
) -> list[dict]:
    """Search the IT knowledge base and return cited passages."""
    return get_retriever().search(query, k=k, category=category.value if category else None)


@mcp.tool()
def create_ticket(
    title: Annotated[str, Field(min_length=3, max_length=200)],
    description: Annotated[str, Field(min_length=5, max_length=4000)],
    reporter_email: str | None = None,
    priority: Priority | None = None,
    category: Category | None = None,
) -> dict:
    """Create a new incident ticket."""
    with _db() as db:
        return _ticket(svc.create_incident(db, IncidentCreate(
            title=title, description=description, reporter_email=reporter_email,
            priority=priority, category=category,
        )))


@mcp.tool()
def get_ticket(ticket_id: str) -> dict:
    """Fetch a ticket by ID (e.g. INC-1A2B3C4D)."""
    with _db() as db:
        return _safe(lambda: _ticket(svc.get_incident(db, ticket_id)))


@mcp.tool()
def update_ticket(
    ticket_id: str,
    status: IncidentStatus | None = None,
    priority: Priority | None = None,
    assigned_to: Annotated[str | None, Field(max_length=100)] = None,
    action: Annotated[str | None, Field(description=f"Allowlisted action: {', '.join(mock_it.ALLOWED_ACTIONS)}")] = None,
    approved_by: Annotated[str | None, Field(description="Human approver; required for consequential actions")] = None,
) -> dict:
    """Update a ticket and/or run an allowlisted mock action."""
    with _db() as db:
        def work():
            result: dict = {}
            if action:
                result["action"] = svc.run_action(db, ticket_id, action, approved_by)
            svc.update_incident(db, ticket_id, IncidentUpdate(
                status=status, priority=priority, assigned_to=assigned_to))
            result["ticket"] = _ticket(svc.get_incident(db, ticket_id))
            return result
        return _safe(work)


@mcp.tool()
def escalate_ticket(
    ticket_id: str,
    reason: Annotated[str, Field(min_length=3, max_length=1000)],
    team: Annotated[str | None, Field(max_length=100)] = None,
) -> dict:
    """Escalate a ticket to a human team."""
    with _db() as db:
        return _safe(lambda: _ticket(svc.escalate_incident(db, ticket_id, reason, team)))


@mcp.tool()
def generate_report(ticket_id: str) -> dict:
    """Generate a structured incident report."""
    with _db() as db:
        return _safe(lambda: svc.generate_report(db, ticket_id).model_dump())


if __name__ == "__main__":
    init_db()
    mcp.run()
