from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Category(str, Enum):
    NETWORK = "network"
    HARDWARE = "hardware"
    SOFTWARE = "software"
    ACCOUNT = "account"
    SECURITY = "security"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class IncidentStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=4000)
    reporter_email: str | None = Field(default=None, max_length=200)
    reporter_name: str | None = Field(default=None, max_length=100)
    source: str = Field(default="customer", pattern="^(customer|system)$")
    category: Category | None = None
    priority: Priority | None = None


class IncidentUpdate(BaseModel):
    status: IncidentStatus | None = None
    category: Category | None = None
    priority: Priority | None = None
    assigned_to: str | None = Field(default=None, max_length=100)
    resolution: str | None = Field(default=None, max_length=4000)


class Feedback(BaseModel):
    resolved: bool
    comment: str | None = Field(default=None, max_length=1000)
    rating: int | None = Field(default=None, ge=1, le=5)


class CommentCreate(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    actor: str
    message: str
    created_at: datetime


class ActionItem(BaseModel):
    name: str
    description: str
    requires_approval: bool
    status: str = "proposed"  # proposed | executed | pending_approval | rejected
    result: str | None = None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    category: str | None
    priority: str | None
    status: str
    source: str
    type: str = "incident"
    assigned_to: str | None
    reporter_name: str | None = None
    due_at: datetime | None = None
    resolved_at: datetime | None = None
    satisfaction: int | None = None
    sla_breached: bool = False
    recommendation: str | None
    sources: list = []
    actions: list = []
    created_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentOut):
    events: list[EventOut] = []
