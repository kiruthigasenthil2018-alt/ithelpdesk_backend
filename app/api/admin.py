from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import UserOut
from app.api.auth_deps import require_roles
from app.api.deps import get_llm_client
from app.database.base import get_db
from app.database.models import User

router = APIRouter(prefix="/admin", tags=["Admin"])


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None


@router.get("/users", response_model=list[UserOut])
def list_users(admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.id)))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, admin: User = Depends(require_roles("admin")),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(400, "You cannot change your own role or disable yourself")
    if data.role is not None:
        if data.role not in ("employee", "agent", "admin"):
            raise HTTPException(422, "Role must be employee, agent or admin")
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    db.commit()
    return user


@router.get("/llm-status")
def llm_status(admin: User = Depends(require_roles("admin")), llm=Depends(get_llm_client)):
    """Which AI providers are configured and whether one is cooling down after a rate limit."""
    return {"providers": llm.status() if hasattr(llm, "status") else [], "last_provider": getattr(llm, "last_provider", None)}
