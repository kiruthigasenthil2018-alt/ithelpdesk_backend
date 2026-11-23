import os
import tempfile

# Must be set BEFORE the app is imported.
_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL="sqlite://",  # in-memory
    EMBEDDING_BACKEND="hash",
    CHROMA_PATH=os.path.join(_tmp, "chroma"),
    KNOWLEDGE_BASE_DIR=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge_base"),
    REDIS_URL="",
    GEMINI_API_KEY="",
    LLM_BACKOFF_SECONDS="0",
    SECRET_KEY="test-secret-key-that-is-at-least-32-chars-long",
    ADMIN_EMAIL="",
    UPLOAD_DIR=os.path.join(_tmp, "uploads"),
)

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import get_llm_client, get_retriever  # noqa: E402
from app.database.base import Base, SessionLocal, engine, init_db  # noqa: E402
from app.database.models import User  # noqa: E402
from app.services.cache import get_cache  # noqa: E402
from app.services.security import create_token, hash_password, limiter  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.llm import Troubleshooting, Verification  # noqa: E402

KB = Path(__file__).resolve().parents[1] / "knowledge_base"


class FakeLLM:
    """Stands in for Gemini so tests never call the network."""

    def __init__(self, grounded=True, available=True):
        self.available = available
        self.grounded = grounded

    def generate_json(self, prompt, model_cls, system=None):
        if model_cls is Troubleshooting:
            return Troubleshooting(
                answer="1. Restart the VPN client [1]. 2. Flush DNS.",
                suggested_actions=["flush_dns", "reset_password", "format_hard_drive"],
            )
        if model_cls is Verification:
            return Verification(grounded=self.grounded)
        from app.schemas.llm import Classification
        return Classification(category="network", priority="P2", confidence=0.9, summary="vpn")

    def generate_text(self, prompt, system=None):
        return "ok"


@pytest.fixture(scope="session")
def retriever():
    r = get_retriever()
    r.store.ingest_folder(KB)
    return r


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    init_db()
    limiter.reset()
    get_cache().delete_prefix("stats")
    yield


def make_user(role: str, email: str | None = None) -> dict:
    """Create a user directly in the DB and return Authorization headers for them."""
    with SessionLocal() as db:
        u = User(name=role.capitalize(), email=email or f"{role}@test.com", role=role,
                 password_hash=hash_password("Password123"))
        db.add(u)
        db.commit()
        return {"Authorization": f"Bearer {create_token(u.id, u.role)}"}


@pytest.fixture
def client(retriever):
    """Test client logged in as an admin."""
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    c = TestClient(app)
    c.headers.update(make_user("admin"))
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def anon(retriever):
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    yield TestClient(app)
    app.dependency_overrides.clear()
