from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    user_email: str | None = Field(default=None, max_length=200)
    user_name: str | None = Field(default=None, max_length=100)
    attachment_ids: list[int] = Field(default_factory=list, max_length=5)


class ChatResponse(BaseModel):
    conversation_id: str
    incident_id: str
    reply: str
    category: str | None = None
    priority: str | None = None
    status: str
    escalated: bool = False
    sources: list[dict] = []
    actions: list[dict] = []


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime
