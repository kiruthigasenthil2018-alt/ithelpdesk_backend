from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    role: Mapped[str] = mapped_column(String(30), default="employee")  # employee|agent|admin
    password_hash: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incidents: Mapped[list["Incident"]] = relationship(back_populates="reporter")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. INC-1A2B3C4D
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(30))
    priority: Mapped[str | None] = mapped_column(String(4))  # P1..P4
    status: Mapped[str] = mapped_column(String(20), default="open")
    source: Mapped[str] = mapped_column(String(20), default="customer")  # customer|system
    assigned_to: Mapped[str | None] = mapped_column(String(100))
    recommendation: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # RAG citations
    actions: Mapped[list] = mapped_column(JSON, default=list)  # proposed mock actions
    type: Mapped[str] = mapped_column(String(20), default="incident")  # incident|request
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # SLA deadline
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    satisfaction: Mapped[int | None] = mapped_column(Integer)  # CSAT 1-5
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    reporter: Mapped[User | None] = relationship(back_populates="incidents")

    @property
    def reporter_name(self) -> str | None:
        return self.reporter.name if self.reporter else None

    @property
    def sla_breached(self) -> bool:
        if not self.due_at or self.status in ("resolved",):
            return False
        due = self.due_at if self.due_at.tzinfo else self.due_at.replace(tzinfo=timezone.utc)
        return due < datetime.now(timezone.utc)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="incident")
    resolutions: Mapped[list["Resolution"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    escalations: Mapped[list["Escalation"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    events: Mapped[list["IncidentEvent"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="IncidentEvent.id"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incident: Mapped[Incident | None] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(20))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Resolution(Base):
    __tablename__ = "resolutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    summary: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(default=False)
    confirmed_by_user: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incident: Mapped[Incident] = relationship(back_populates="resolutions")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    reason: Mapped[str] = mapped_column(Text)
    escalated_to: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incident: Mapped[Incident] = relationship(back_populates="escalations")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incident: Mapped[Incident] = relationship(back_populates="reports")



class IncidentEvent(Base):
    """Activity timeline entry: created, status change, comment, action, escalation..."""

    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    actor: Mapped[str] = mapped_column(String(100), default="system")
    kind: Mapped[str] = mapped_column(String(20))  # created|status|assigned|comment|action|escalated|ai
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incident: Mapped[Incident] = relationship(back_populates="events")


class Attachment(Base):
    """A file uploaded in chat or on a ticket. Bytes live on disk under a random name."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))  # null until linked
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(150))  # display name only, never used as a path
    stored_name: Mapped[str] = mapped_column(String(40), unique=True)
    content_type: Mapped[str] = mapped_column(String(60))  # sniffed image type or octet-stream
    size: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
