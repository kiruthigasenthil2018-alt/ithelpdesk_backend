from fastapi.testclient import TestClient

from app.api.deps import get_llm_client
from app.config import get_settings
from app.main import app
from tests.conftest import FakeLLM, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def _upload(c, files, **data):
    return c.post("/attachments", files=[("files", f) for f in files], data=data)


def test_any_format_and_image_upload_and_safe_download(client):
    r = _upload(client, [("report.exe", b"MZ-binary", "application/x-msdownload"),
                         ("shot.png", PNG, "image/png"),
                         ("evil.svg", b"<svg onload=alert(1)>", "image/svg+xml")])
    assert r.status_code == 200
    exe, png, svg = r.json()
    assert png["is_image"] and not exe["is_image"] and not svg["is_image"]  # SVG is never treated as an image
    assert client.get(f"/attachments/{png['id']}/download?inline=1").headers["content-disposition"].startswith("inline")
    for a in (exe, svg):
        resp = client.get(f"/attachments/{a['id']}/download?inline=1")
        assert resp.headers["content-disposition"].startswith("attachment")
        assert resp.headers["content-type"].startswith("application/octet-stream")
    assert client.get(f"/attachments/{exe['id']}/download").content == b"MZ-binary"


def test_path_traversal_in_filename_is_neutralised(client):
    r = _upload(client, [("../../etc/passwd", b"x", "text/plain")])
    assert r.json()[0]["filename"] == "passwd"


def test_limits(client, monkeypatch):
    assert _upload(client, [(f"f{i}.txt", b"x", "text/plain") for i in range(6)]).status_code == 400
    assert _upload(client, [("empty.txt", b"", "text/plain")]).status_code == 400
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    assert _upload(client, [("big.txt", b"xx", "text/plain")]).status_code == 413


def test_other_employee_cannot_download_or_delete(retriever):
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    a, b = TestClient(app), TestClient(app)
    a.headers.update(make_user("employee", "a@test.com"))
    b.headers.update(make_user("employee", "b@test.com"))
    att = _upload(a, [("log.txt", b"hello", "text/plain")]).json()[0]
    assert b.get(f"/attachments/{att['id']}/download").status_code == 404
    assert b.delete(f"/attachments/{att['id']}").status_code == 404
    assert a.delete(f"/attachments/{att['id']}").status_code == 200
    assert _upload(TestClient(app), [("x.txt", b"x", "text/plain")]).status_code == 401
    app.dependency_overrides.clear()


def test_chat_with_attachment_links_file_and_gives_ai_the_text(retriever):
    prompts = []

    class Spy(FakeLLM):
        def generate_json(self, prompt, model_cls, system=None):
            prompts.append(prompt)
            return super().generate_json(prompt, model_cls, system)

    app.dependency_overrides[get_llm_client] = lambda: Spy()
    c = TestClient(app)
    c.headers.update(make_user("employee", "e@test.com"))
    att = _upload(c, [("vpn.log", b"ERROR 809 tunnel failed", "text/plain")]).json()[0]
    r = c.post("/chat", json={"message": "VPN will not connect", "attachment_ids": [att["id"]]})
    assert r.status_code == 200
    inc = r.json()["incident_id"]
    assert [a["filename"] for a in c.get(f"/incidents/{inc}/attachments").json()] == ["vpn.log"]
    assert any("ERROR 809 tunnel failed" in p for p in prompts)
    # a second chat cannot steal an already-linked file
    other = TestClient(app)
    other.headers.update(make_user("employee", "o@test.com"))
    assert other.get(f"/incidents/{inc}/attachments").status_code == 404
    app.dependency_overrides.clear()
