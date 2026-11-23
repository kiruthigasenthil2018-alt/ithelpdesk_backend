from typing import TypedDict


class AgentState(TypedDict, total=False):
    # inputs
    incident_id: str
    query: str
    attachment_text: str  # text extracted from files the user attached
    history: list[dict]  # [{"role": "user"|"assistant", "content": str}]
    preset_category: str | None
    preset_priority: str | None
    # classification
    category: str
    priority: str
    # retrieval
    documents: list[dict]
    attempts: int
    use_category_filter: bool
    retrieval_ok: bool
    # troubleshooting
    reply: str
    actions: list[dict]
    degraded: bool  # True when the LLM failed and a fallback was used
    # verification / escalation
    verified: bool
    escalated: bool
    escalation_reason: str
    escalated_to: str
    status: str
    report: dict
