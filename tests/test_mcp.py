import asyncio

from app.tools import mcp_server as m


def test_all_six_tools_registered():
    names = {t.name for t in asyncio.run(m.mcp.list_tools())}
    assert names == {"search_knowledge", "create_ticket", "get_ticket", "update_ticket",
                     "escalate_ticket", "generate_report"}


def test_ticket_lifecycle_with_approval(retriever):
    t = m.create_ticket("Locked out", "my account is locked", "a@b.com")
    tid = t["id"]
    assert m.get_ticket(tid)["title"] == "Locked out"
    pending = m.update_ticket(tid, action="unlock_account")
    assert pending["status"] == "pending_approval"
    done = m.update_ticket(tid, action="unlock_account", approved_by="admin")
    assert done["action"]["status"] == "executed"
    assert m.update_ticket(tid, action="delete_everything")["error"]
    assert m.escalate_ticket(tid, "needs IAM")["status"] == "escalated"
    assert m.generate_report(tid)["incident_id"] == tid
    assert m.get_ticket("INC-NOPE")["error"]
    assert m.search_knowledge("account locked")[0]["source"] == "password_reset_and_lockout.txt"
