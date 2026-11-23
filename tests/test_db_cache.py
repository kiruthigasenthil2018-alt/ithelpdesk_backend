from app.database.base import SessionLocal
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.services import incident_service as svc
from app.services.cache import Cache


def test_incident_relationships_and_crud():
    db = SessionLocal()
    inc = svc.create_incident(db, IncidentCreate(
        title="VPN down", description="cannot connect to vpn", reporter_email="a@b.com"))
    assert inc.reporter.email == "a@b.com"
    svc.update_incident(db, inc.id, IncidentUpdate(resolution="Re-issued profile"))
    svc.escalate_incident(db, inc.id, "needs network team")
    inc = svc.get_incident(db, inc.id)
    assert inc.status == "escalated" and len(inc.resolutions) == 1 and len(inc.escalations) == 1
    conv = svc.get_or_create_conversation(db, None)
    svc.add_message(db, conv.id, "user", "hi")
    assert [m.content for m in svc.get_history(db, conv.id)] == ["hi"]
    report = svc.generate_report(db, inc.id)
    assert report.escalation_status.startswith("escalated to")
    db.close()


def test_stats_cache_is_invalidated_on_write():
    db = SessionLocal()
    assert svc.dashboard_stats(db)["total"] == 0
    svc.create_incident(db, IncidentCreate(title="abc", description="some issue"))
    assert svc.dashboard_stats(db)["total"] == 1
    db.close()


def test_memory_cache_roundtrip_and_ttl():
    c = Cache(ttl=300)
    assert c.backend == "memory"
    c.set_json("k", {"a": 1})
    assert c.get_json("k") == {"a": 1}
    c.set_json("k2", 1, ttl=-1)
    assert c.get_json("k2") is None
    c.delete_prefix("k")
    assert c.get_json("k") is None


def test_cache_survives_redis_failure():
    class Broken:
        def get(self, *_): raise ConnectionError()
        def setex(self, *_): raise ConnectionError()
        def ping(self): raise ConnectionError()

    c = Cache(client=Broken())
    c.set_json("x", 1)
    assert c.get_json("x") is None and c.ping() is False
