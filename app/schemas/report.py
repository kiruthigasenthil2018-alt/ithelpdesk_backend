from pydantic import BaseModel, Field


class IncidentReport(BaseModel):
    incident_id: str
    category: str | None = None
    priority: str | None = None
    problem: str
    retrieved_sources: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    resolution: str | None = None
    status: str = "open"
    escalation_status: str = "not_escalated"
    generated_at: str
