from datetime import timedelta

import pyotp
import pytest
from sqlalchemy import select, update

from app.config import get_settings
from app.db import sessionmaker
from app.models import AuditLog, Session, User
from app.models.base import utcnow
from tests.integration.conftest import csrf, login_full

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_login_success_sets_secure_cookies(client, users):
    username, password, _ = await users.create(["Viewer"])
    r = await client.post("/api/v1/auth/login", json={"username": username.upper(), "password": password})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "full"
    assert "logs.view" in body["permissions"] and "users.manage" not in body["permissions"]
    cookies = r.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith(get_settings().session_cookie))
    assert "HttpOnly" in session_cookie and "Secure" in session_cookie and "SameSite=strict" in session_cookie
    csrf_cookie = next(c for c in cookies if c.startswith(get_settings().csrf_cookie))
    assert "HttpOnly" not in csrf_cookie


async def test_login_by_email(client, users):
    username, password, _ = await users.create(["Viewer"])
    r = await client.post("/api/v1/auth/login", json={"username": f"{username}@example.test", "password": password})
    assert r.status_code == 200 and r.json()["state"] == "full"


async def test_wrong_password_is_generic_and_audited(client, users):
    username, _, _ = await users.create(["Viewer"])
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": "nope-nope-nope"})
    assert r.status_code == 401
    r2 = await client.post("/api/v1/auth/login", json={"username": "no-such-user", "password": "nope-nope-nope"})
    assert r2.status_code == 401 and r2.json() == r.json()
    async with sessionmaker()() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.actor_name == username,
                                                       AuditLog.action == "auth.login"))).scalars().all()
    assert [(a.result, a.detail) for a in rows] == [("failure", "wrong password")]


async def test_lockout_after_threshold_then_admin_unlock(client, users):
    username, password, _ = await users.create(["Viewer"])
    for _ in range(5):
        r = await client.post("/api/v1/auth/login", json={"username": username, "password": "wrong-password-x"})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 401, "correct password must not work while locked"

    from httpx import ASGITransport, AsyncClient

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as admin:
        await login_full(admin, users, ["Admin"])
        uid = (await admin.get("/api/v1/users")).json()
        target = next(u for u in uid if u["username"] == username)
        assert target["locked_until"] is not None
        assert (await admin.post(f"/api/v1/users/{target['id']}/unlock")).status_code == 200
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200


async def test_ip_rate_limit(client, users, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_ip_limit", 2)
    from app.redis_client import get_redis
    await get_redis().delete("opsbrain:login:ip:127.0.0.1")
    codes = [(await client.post("/api/v1/auth/login", json={"username": "x", "password": "y"})).status_code
             for _ in range(3)]
    await get_redis().delete("opsbrain:login:ip:127.0.0.1")
    assert codes == [401, 401, 429]


async def test_csrf_required_for_mutations(client, users):
    username, password, _ = await users.create(["Viewer"])
    await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 403
    client.headers["X-CSRF-Token"] = "forged"
    assert (await client.post("/api/v1/auth/logout")).status_code == 403
    csrf(client)
    assert (await client.post("/api/v1/auth/logout")).status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_admin_must_enrol_mfa(client, users):
    username, password, _ = await users.create(["Admin"])
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.json()["state"] == "mfa_enrollment_required"
    csrf(client)
    assert (await client.get("/api/v1/users")).status_code == 401
    setup = (await client.post("/api/v1/auth/mfa/setup")).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    bad = await client.post("/api/v1/auth/mfa/enable", json={"code": "000000"})
    assert bad.status_code == 400
    r = await client.post("/api/v1/auth/mfa/enable", json={"code": pyotp.TOTP(setup["secret"]).now()})
    assert r.status_code == 200 and r.json()["state"] == "full"
    assert (await client.get("/api/v1/users")).status_code == 200
    # Policy requires MFA for admins, so it cannot be switched off.
    assert (await client.post("/api/v1/auth/mfa/disable", json={"password": password})).status_code == 409


async def test_mfa_login_rejects_wrong_and_replayed_codes(client, users):
    username, password, secret = await users.create(["Viewer"], mfa=True)
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.json()["state"] == "mfa_required"
    csrf(client)
    assert (await client.get("/api/v1/auth/sessions")).status_code == 401
    assert (await client.post("/api/v1/auth/mfa/verify", json={"code": "123456"})).status_code == 401
    code = pyotp.TOTP(secret).now()
    r = await client.post("/api/v1/auth/mfa/verify", json={"code": code})
    assert r.status_code == 200 and r.json()["state"] == "full"
    await client.post("/api/v1/auth/logout")
    client.cookies.clear()
    await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    csrf(client)
    assert (await client.post("/api/v1/auth/mfa/verify", json={"code": code})).status_code == 401


async def test_forced_password_change(client, users):
    username, password, _ = await users.create(["Viewer"], must_change=True)
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.json()["state"] == "password_change_required"
    csrf(client)
    assert (await client.get("/api/v1/auth/sessions")).status_code == 401
    weak = await client.post("/api/v1/auth/password", json={"current_password": password, "new_password": "short"})
    assert weak.status_code == 400 and "at least" in weak.json()["detail"]
    r = await client.post("/api/v1/auth/password",
                          json={"current_password": password, "new_password": "amber glacier fox lantern"})
    assert r.status_code == 200 and r.json()["state"] == "full"
    client.cookies.clear()
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": "amber glacier fox lantern"})
    assert r.json()["state"] == "full"


async def test_idle_session_expires(client, users):
    username, password, _ = await users.create(["Viewer"])
    await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    async with sessionmaker()() as s:
        uid = (await s.execute(select(User.id).where(User.username == username))).scalar_one()
        await s.execute(update(Session).where(Session.user_id == uid)
                        .values(last_seen_at=utcnow() - timedelta(minutes=31)))
        await s.commit()
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_password_change_signs_out_other_sessions(client, users):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    username, password, _ = await users.create(["Viewer"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as other:
        await other.post("/api/v1/auth/login", json={"username": username, "password": password})
        await client.post("/api/v1/auth/login", json={"username": username, "password": password})
        csrf(client)
        sessions = (await client.get("/api/v1/auth/sessions")).json()
        assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
        r = await client.post("/api/v1/auth/password",
                              json={"current_password": password, "new_password": "quiet harbour seven kites"})
        assert r.status_code == 200
        assert (await other.get("/api/v1/auth/me")).status_code == 401
        assert (await client.get("/api/v1/auth/me")).status_code == 200
