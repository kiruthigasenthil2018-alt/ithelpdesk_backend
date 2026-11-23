from tests.conftest import make_user

CHAT = {"message": "VPN will not connect"}


def test_health_is_public(anon):
    body = anon.get("/health").json()
    assert body["status"] == "ok" and body["knowledge_chunks"] > 0


def test_chat_flow_creates_incident_history_and_timeline(client):
    r = client.post("/chat", json=CHAT)
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "network" and body["priority"] == "P2" and body["sources"] and body["actions"]
    follow = client.post("/chat", json={"message": "still failing", "conversation_id": body["conversation_id"]})
    assert follow.json()["incident_id"] == body["incident_id"]
    msgs = client.get(f"/conversations/{body['conversation_id']}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    detail = client.get(f"/incidents/{body['incident_id']}").json()
    assert {e["kind"] for e in detail["events"]} >= {"created", "ai"}
    assert detail["due_at"] is not None and detail["sla_breached"] is False


def test_chat_validation(client):
    assert client.post("/chat", json={"message": ""}).status_code == 422


def test_chat_rate_limit(client):
    from app.config import get_settings
    codes = [client.post("/chat", json=CHAT).status_code for _ in range(get_settings().rate_limit_chat_per_min + 1)]
    assert codes[-1] == 429


def test_employees_only_see_their_own_data(client):
    alice, bob = make_user("employee", "alice@test.com"), make_user("employee", "bob@test.com")
    chat = client.post("/chat", json=CHAT, headers=alice).json()
    iid, cid = chat["incident_id"], chat["conversation_id"]
    assert [i["id"] for i in client.get("/incidents", headers=alice).json()] == [iid]
    assert client.get("/incidents", headers=bob).json() == []
    assert client.get(f"/incidents/{iid}", headers=bob).status_code == 404
    assert client.get(f"/reports/{iid}", headers=bob).status_code == 404
    assert client.post(f"/incidents/{iid}/comments", json={"message": "hi"}, headers=bob).status_code == 404
    assert client.get(f"/conversations/{cid}/messages", headers=bob).status_code == 404
    assert client.post("/chat", json={**CHAT, "conversation_id": cid}, headers=bob).status_code == 404
    assert client.get(f"/incidents/{iid}", headers=alice).status_code == 200
    assert client.get("/dashboard/stats", headers=bob).json()["total"] == 0
    assert client.get("/dashboard/stats", headers=alice).json()["total"] == 1


def test_role_restrictions(client):
    emp, agent = make_user("employee", "e@test.com"), make_user("agent", "a@test.com")
    iid = client.post("/chat", json=CHAT, headers=emp).json()["incident_id"]
    assert client.patch(f"/incidents/{iid}", json={"priority": "P1"}, headers=emp).status_code == 403
    assert client.post(f"/incidents/{iid}/actions/flush_dns/execute", json={}, headers=emp).status_code == 403
    assert client.get("/analytics", headers=emp).status_code == 403
    assert client.get("/admin/users", headers=agent).status_code == 403
    assert client.post("/knowledge/reindex", headers=agent).status_code == 403
    assert client.patch(f"/incidents/{iid}", json={"priority": "P1"}, headers=agent).status_code == 200
    assert client.get("/analytics", headers=agent).status_code == 200
    assert client.post(f"/incidents/{iid}/comments", json={"message": "working on it"}, headers=emp).status_code == 200


def test_consequential_actions_need_an_admin(client):
    agent = make_user("agent", "a@test.com")
    iid = client.post("/chat", json=CHAT).json()["incident_id"]
    run = lambda action, h=None: client.post(f"/incidents/{iid}/actions/{action}/execute", json={"approved_by": "fake"}, headers=h or {})
    assert run("flush_dns", agent).status_code == 200
    assert run("reset_password", agent).status_code == 403  # agents cannot approve; body 'approved_by' is ignored
    ok = run("reset_password")  # admin (default client)
    assert ok.status_code == 200 and "approved by Admin" in ok.json()["result"]
    assert run("rm_rf").status_code == 400


def test_feedback_resolves_or_escalates(client):
    a = client.post("/chat", json=CHAT).json()["incident_id"]
    r = client.post(f"/incidents/{a}/feedback", json={"resolved": True, "rating": 5}).json()
    assert r["status"] == "resolved" and r["satisfaction"] == 5 and r["resolved_at"]
    b = client.post("/chat", json=CHAT).json()["incident_id"]
    assert client.post(f"/incidents/{b}/feedback", json={"resolved": False}).json()["status"] == "escalated"
    assert client.post(f"/incidents/{a}/feedback", json={"resolved": True, "rating": 9}).status_code == 422


def test_incident_crud_search_stats_report(client):
    created = client.post("/incidents", json={"title": "Printer", "description": "printer is offline", "source": "system"})
    assert created.status_code == 201 and created.json()["source"] == "customer"  # source can't be forged
    iid = created.json()["id"]
    assert client.patch(f"/incidents/{iid}", json={"priority": "P1", "assigned_to": "Sam"}).json()["priority"] == "P1"
    assert len(client.get("/incidents?priority=P1").json()) == 1
    assert len(client.get("/incidents?q=printer").json()) == 1 and client.get("/incidents?q=zzz").json() == []
    stats = client.get("/dashboard/stats").json()
    assert stats["total"] == 1 and stats["priority"]["P1"] == 1
    assert client.get(f"/reports/{iid}").json()["incident_id"] == iid
    assert client.get("/incidents/INC-NOPE").status_code == 404


def test_catalog_request_and_notifications(client):
    items = client.get("/catalog").json()
    assert len(items) >= 5
    r = client.post("/catalog/vpn-access/request", json={"details": "Need VPN for contractor"})
    assert r.status_code == 201 and r.json()["type"] == "request" and r.json()["category"] == "network"
    assert client.post("/catalog/nope/request", json={}).status_code == 404
    assert client.get("/notifications").json()[0]["kind"] == "created"


def test_analytics_numbers(client):
    iid = client.post("/chat", json=CHAT).json()["incident_id"]
    client.post(f"/incidents/{iid}/feedback", json={"resolved": True, "rating": 4})
    a = client.get("/analytics").json()
    assert a["total"] == 1 and sum(a["created_per_day"]) == 1 and sum(a["resolved_per_day"]) == 1
    assert a["ai_deflection_rate"] == 1.0 and a["csat_average"] == 4 and a["sla_compliance"] == 1.0
    assert a["by_category"] == {"network": 1}


def test_knowledge_endpoints(client):
    first = client.get("/knowledge/search", params={"q": "printer offline"}).json()
    second = client.get("/knowledge/search", params={"q": "printer offline"}).json()
    assert first["cached"] is False and second["cached"] is True
    assert first["results"][0]["source"] == "printer_and_hardware.txt"
    arts = client.get("/knowledge/articles").json()
    assert any(a["source"] == "vpn_troubleshooting.txt" for a in arts)
    assert "VPN" in client.get("/knowledge/articles/vpn_troubleshooting.txt").json()["content"]
    assert client.get("/knowledge/articles/..%2F..%2F.env").status_code == 404
    assert client.get("/knowledge/articles/missing.txt").status_code == 404
    assert client.post("/knowledge/ingest", files={"file": ("evil.exe", b"x")}).status_code == 400


def test_admin_user_management(client):
    make_user("employee", "x@test.com")
    users = client.get("/admin/users").json()
    uid = next(u["id"] for u in users if u["email"] == "x@test.com")
    assert client.patch(f"/admin/users/{uid}", json={"role": "agent"}).json()["role"] == "agent"
    assert client.patch(f"/admin/users/{uid}", json={"role": "superuser"}).status_code == 422
    me = next(u["id"] for u in users if u["role"] == "admin")
    assert client.patch(f"/admin/users/{me}", json={"role": "employee"}).status_code == 400
    assert "providers" in client.get("/admin/llm-status").json()
