"""Structured outputs we ask Gemini to produce (validated with Pydantic)."""

from pydantic import BaseModel, Field

from app.schemas.incident import Category, Priority


class Classification(BaseModel):
    category: Category
    priority: Priority
    confidence: float = Field(default=0.5, ge=0, le=1)
    summary: str = Field(default="", max_length=300)


class Troubleshooting(BaseModel):
    answer: str = Field(description="Step-by-step guidance for the user")
    suggested_actions: list[str] = Field(
        default_factory=list, description="Names chosen ONLY from the allowed actions list"
    )


class Verification(BaseModel):
    grounded: bool = Field(description="True if the answer is supported by the sources")
    reason: str = ""
