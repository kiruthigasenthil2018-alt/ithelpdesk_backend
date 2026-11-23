from app.agents.graph import run_agent
from tests.conftest import FakeLLM


def _run(retriever, llm, query):
    return run_agent(llm, retriever, {"incident_id": "INC-T", "query": query, "history": []})


def test_good_path_is_verified_and_filters_invented_actions(retriever):
    s = _run(retriever, FakeLLM(), "VPN will not connect, what should I do")
    assert s["verified"] and not s["escalated"] and s["status"] == "in_progress"
    names = [a["name"] for a in s["actions"]]
    assert names == ["flush_dns", "reset_password"]  # 'format_hard_drive' dropped
    assert s["actions"][1]["requires_approval"] is True
    assert s["report"]["retrieved_sources"]


def test_unverified_answer_escalates(retriever):
    s = _run(retriever, FakeLLM(grounded=False), "VPN will not connect")
    assert s["escalated"] and s["status"] == "escalated"
    assert s["escalated_to"] == "Network Operations"


def test_no_relevant_docs_retries_then_escalates(retriever):
    s = _run(retriever, FakeLLM(), "zebra quantum banana xylophone")
    assert s["attempts"] == 2 and s["escalated"]
    assert "No sufficiently relevant" in s["escalation_reason"]


def test_works_without_llm_using_fallbacks(retriever):
    s = _run(retriever, FakeLLM(available=False), "my printer is offline")
    assert s["degraded"] and s["category"] == "hardware" and s["reply"].startswith("Based on [1]")
