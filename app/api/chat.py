from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.graph import run_agent
from app.api.auth_deps import chat_rate_limit, get_current_user
from app.api.deps import get_llm_client, get_retriever
from app.database.base import get_db
from app.database.models import Conversation, User
from app.schemas.chat import ChatRequest, ChatResponse, MessageOut
from app.schemas.incident import IncidentCreate
from app.services import attachments as att_svc
from app.services import incident_service as svc

router = APIRouter(tags=["Chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    user: User = Depends(chat_rate_limit),  # requires login + rate limit
    db: Session = Depends(get_db),
    llm=Depends(get_llm_client),
    retriever=Depends(get_retriever),
) -> ChatResponse:
    try:
        conv = svc.get_or_create_conversation(db, req.conversation_id, user.id)
    except svc.NotFoundError:
        raise HTTPException(404, "Conversation not found")
    history = [{"role": m.role, "content": m.content} for m in svc.get_history(db, conv.id)]

    if conv.incident_id:  # follow-up message in an existing conversation
        incident = svc.get_incident(db, conv.incident_id)
    else:
        incident = svc.create_incident(
            db,
            IncidentCreate(
                title=req.message[:80] if len(req.message) >= 3 else req.message.ljust(3, "."),
                description=req.message.ljust(5, "."),
            ),
            user=user,
        )
        conv.incident_id = incident.id
        db.commit()

    svc.add_message(db, conv.id, "user", req.message)
    attached = att_svc.link_to_incident(db, req.attachment_ids, user, incident.id)
    state = run_agent(
        llm, retriever,
        {
            "incident_id": incident.id,
            "query": req.message,
            "history": history,
            "attachment_text": att_svc.extract_text(attached),
            "preset_category": incident.category,
            "preset_priority": incident.priority,
        },
    )
    incident = svc.apply_agent_result(db, incident.id, state)
    svc.add_message(db, conv.id, "assistant", state["reply"])

    return ChatResponse(
        conversation_id=conv.id,
        incident_id=incident.id,
        reply=state["reply"],
        category=incident.category,
        priority=incident.priority,
        status=incident.status,
        escalated=bool(state.get("escalated")),
        sources=incident.sources,
        actions=incident.actions,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def conversation_messages(
    conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    conv = db.get(Conversation, conversation_id)
    if conv is None or (conv.user_id != user.id and user.role == "employee"):
        raise HTTPException(404, "Conversation not found")
    return svc.get_history(db, conversation_id)
