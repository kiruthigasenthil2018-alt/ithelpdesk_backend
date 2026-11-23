from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings
from app.services.security import ALGORITHM, _secret, check_password_policy, verify_password, hash_password
from tests.conftest import make_user

GOOD = {"name": "Jane", "email": "Jane@Example.com", "password": "Sup3rSecret99"}


def test_register_login_me(anon):
    r = anon.post("/auth/register", json=GOOD)
    assert r.status_code == 201 and r.json()["user"]["role"] == "employee"
    login = anon.post("/auth/login", json={"email": "jane@example.com", "password": GOOD["password"]})
    assert login.status_code == 200
    me = anon.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.json()["email"] == "jane@example.com"


def test_registration_validation(anon):
    assert anon.post("/auth/register", json={**GOOD, "password": "short1"}).status_code == 422
    assert anon.post("/auth/register", json={**GOOD, "password": "onlyletterspassword"}).status_code == 422
    assert anon.post("/auth/register", json={**GOOD, "email": "not-an-email"}).status_code == 422
    assert anon.post("/auth/register", json=GOOD).status_code == 201
    assert anon.post("/auth/register", json=GOOD).status_code == 409


def test_users_cannot_self_assign_role(anon):
    r = anon.post("/auth/register", json={**GOOD, "role": "admin"})
    assert r.json()["user"]["role"] == "employee"


def test_login_failure_is_generic_and_account_locks(anon):
    anon.post("/auth/register", json=GOOD)
    unknown = anon.post("/auth/login", json={"email": "nobody@x.com", "password": "whatever12345"})
    wrong = anon.post("/auth/login", json={"email": "jane@example.com", "password": "wrong-password1"})
    assert unknown.status_code == wrong.status_code == 401 and unknown.json() == wrong.json()
    for _ in range(get_settings().login_max_attempts - 1):
        anon.post("/auth/login", json={"email": "jane@example.com", "password": "wrong-password1"})
    locked = anon.post("/auth/login", json={"email": "jane@example.com", "password": GOOD["password"]})
    assert locked.status_code == 423  # correct password is rejected while locked


def test_login_rate_limit(anon):
    codes = [anon.post("/auth/login", json={"email": "a@b.com", "password": "x" * 12}).status_code
             for _ in range(get_settings().rate_limit_login_per_min + 2)]
    assert codes[-1] == 429


def test_protected_routes_need_a_valid_token(anon):
    for method, url in [("get", "/incidents"), ("post", "/chat"), ("get", "/dashboard/stats"),
                        ("get", "/knowledge/search?q=vpn"), ("get", "/admin/users")]:
        assert getattr(anon, method)(url).status_code == 401
    assert anon.get("/incidents", headers={"Authorization": "Bearer garbage"}).status_code == 401
    expired = jwt.encode({"sub": "1", "role": "admin", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
                         _secret(), algorithm=ALGORITHM)
    assert anon.get("/incidents", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = jwt.encode({"sub": "1", "role": "admin"}, "wrong-key-wrong-key-wrong-key-wrong-key", algorithm=ALGORITHM)
    assert anon.get("/incidents", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_disabled_user_token_stops_working(client):
    h = make_user("employee", "temp@test.com")
    assert client.get("/incidents", headers=h).status_code == 200
    users = client.get("/admin/users").json()
    uid = next(u["id"] for u in users if u["email"] == "temp@test.com")
    assert client.patch(f"/admin/users/{uid}", json={"is_active": False}).status_code == 200
    assert client.get("/incidents", headers=h).status_code == 401


def test_password_helpers_and_security_headers(anon):
    h = hash_password("Password123")
    assert h != "Password123" and verify_password("Password123", h) and not verify_password("nope", h)
    assert check_password_policy("Password123") is None
    r = anon.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
