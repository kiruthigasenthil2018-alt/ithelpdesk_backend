"""Incident classification: Gemini first, keyword fallback if the LLM is unavailable."""

import logging

from app.rag.ingestion import infer_category
from app.schemas.incident import Category, Priority
from app.schemas.llm import Classification
from app.services.llm_service import GeminiClient, LLMError

log = logging.getLogger(__name__)

P1_WORDS = ["outage", "all users", "everyone", "ransomware", "breach", "production down", "server down"]
P2_WORDS = ["cannot work", "can't work", "locked", "not working", "down", "urgent", "crash", "fails"]
P4_WORDS = ["how do i", "how to", "question", "request", "would like"]

SYSTEM = (
    "You are an IT incident triage assistant. Categories: network, hardware, software, account, "
    "security. Priorities: P1 (critical outage/security breach), P2 (high, user cannot work), "
    "P3 (medium), P4 (low/how-to)."
)


def heuristic_classify(text: str) -> Classification:
    t = text.lower()
    cat = infer_category(t)
    category = Category(cat) if cat in Category._value2member_map_ else Category.SOFTWARE
    if any(w in t for w in P1_WORDS):
        priority = Priority.P1
    elif any(w in t for w in P2_WORDS):
        priority = Priority.P2
    elif any(w in t for w in P4_WORDS):
        priority = Priority.P4
    else:
        priority = Priority.P3
    return Classification(
        category=category, priority=priority, confidence=0.4, summary=text[:120]
    )


def classify(llm: GeminiClient, text: str) -> Classification:
    if llm.available:
        try:
            return llm.generate_json(f"Classify this IT support request:\n{text}", Classification, SYSTEM)
        except LLMError as exc:
            log.warning("LLM classification failed, using heuristic: %s", exc)
    return heuristic_classify(text)
