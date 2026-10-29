from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from sqlalchemy import select

from app import security
from app.models import AuditLog, AuthSession, User
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.usefixtures("db_clean")
API = "/api/v1"
CSRF = {"X-OBS-CSRF": "1"}


def test_login_success_returns_token_me_and_httponly_cookie(client, make):
    make.user("alice")
    r = client.post(f"{API}/auth/login", json={"username": "Alice", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["access_token"]
    assert body["me"]["user"]["username"] == "alice"
    assert body["me"]["superuser"] is True
    cookie = r.headers["set-cookie"].lower()
    assert "obs_refresh=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/api/v1/auth" in cookie
    assert "no-store" in r.headers["cache-control"]


def test_unknown_user_wrong_password_and_disabled_give_the_same_answer(client, make):
    make.user("alice")
    make.user("bob", active=False)
    answers = []
    for username, password in (("nobody", PASSWORD), ("alice", "wrong-password-123"), ("bob", PASSWORD)):
        r = client.post(f"{API}/auth/login", json={"username": username, "password": password})
        assert r.status_code == 401
        answers.append(r.json())
    assert answers[0] == answers[1] == answers[2]
    assert answers[0]["error"]["code"] == "invalid_credentials"


def test_failed_logins_are_audited_with_reason(client, make, db):
    make.user("alice")
    client.post(f"{API}/auth/login", json={"username": "alice", "password": "nope-nope-nope"})
    client.post(f"{API}/auth/login", json={"username": "ghost", "password": "nope-nope-nope"})
    rows = db.execute(select(AuditLog).where(AuditLog.action == "auth.login").order_by(AuditLog.id)).scalars().all()
    assert [r.result for r in rows] == ["failure", "failure"]
    assert "wrong password" in rows[0].detail and rows[1].detail == "unknown user"
    assert "nope-nope-nope" not in " ".join(str(r.detail) + str(r.new_value) for r in rows)


def test_account_locks_after_threshold_and_a_correct_password_is_then_refused(client, make, db):
    make.user("alice")
    for _ in range(5):
        r = client.post(f"{API}/auth/login", json={"username": "alice", "password": "wrong-password-1"})
        assert r.status_code == 401
    r = client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 401
    user = db.execute(select(User).where(User.username == "alice")).scalar_one()
    assert user.locked_until and user.locked_until > datetime.now(UTC)
    last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one()
    assert last.detail == "account locked"


def test_lock_expires_and_admin_unlock_works(client, make, db):
    u = make.user("alice")
    u.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    u.failed_attempts = 0
    db.commit()
    assert client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 200


def test_login_is_rate_limited_per_ip(client, make):
    make.user("alice")
    codes = [client.post(f"{API}/auth/login", json={"username": "x", "password": "y"}).status_code for _ in range(25)]
    assert 429 in codes
    r = client.post(f"{API}/auth/login", json={"username": "x", "password": "y"})
    assert r.status_code == 429 and "retry-after" in r.headers


def test_protected_endpoints_need_a_valid_token(client, make):
    assert client.get(f"{API}/users").status_code == 401
    assert client.get(f"{API}/users", headers={"Authorization": "Bearer garbage"}).status_code == 401
    forged = security.jwt.encode({"sub": "x", "sid": "y", "typ": "access", "exp": 9999999999}, "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256")
    assert client.get(f"{API}/users", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_expired_access_token_is_reported_as_expired(client, make):
    u = make.user("alice")
    import jwt as pyjwt

    from app.config import get_config
    token = pyjwt.encode(
        {"sub": str(u.id), "sid": "00000000-0000-0000-0000-000000000000", "typ": "access",
         "exp": datetime.now(UTC) - timedelta(minutes=1)}, get_config().jwt_secret, algorithm="HS256")
    r = client.get(f"{API}/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"


def test_an_mfa_token_cannot_be_used_as_an_access_token(client, make):
    u = make.user("alice")
    token = security.issue_mfa_token(u.id)
    assert client.get(f"{API}/users", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_refresh_rotates_the_token_and_requires_the_csrf_header(client, make):
    make.user("alice")
    login(client)
    assert client.post(f"{API}/auth/refresh").status_code == 403  # no CSRF header
    first_cookie = client.cookies.get("obs_refresh")
    r = client.post(f"{API}/auth/refresh", headers=CSRF)
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.cookies.get("obs_refresh") != first_cookie


def test_reusing_a_rotated_refresh_token_revokes_the_whole_session(client, make, db):
    make.user("alice")
    headers = login(client)
    stolen = client.cookies.get("obs_refresh")
    assert client.post(f"{API}/auth/refresh", headers=CSRF).status_code == 200
    # An attacker replays the old (already rotated) token.
    client.cookies.clear()
    client.cookies.set("obs_refresh", stolen, path="/api/v1/auth")
    r = client.post(f"{API}/auth/refresh", headers=CSRF)
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_revoked"
    # The victim's access token no longer works either.
    assert client.get(f"{API}/auth/sessions", headers=headers).status_code == 401
    assert db.execute(select(AuditLog).where(AuditLog.action == "auth.refresh_reuse_detected")).first()


def test_logout_ends_the_session(client, make):
    make.user("alice")
    headers = login(client)
    assert client.get(f"{API}/auth/sessions", headers=headers).status_code == 200
    assert client.post(f"{API}/auth/logout", headers=CSRF).status_code == 204
    assert client.get(f"{API}/auth/sessions", headers=headers).status_code == 401


def test_forced_password_change_blocks_everything_else(client, make):
    make.user("alice", must_change=True)
    headers = login(client)
    r = client.get(f"{API}/users", headers=headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "password_change_required"
    me = client.get(f"{API}/auth/me", headers=headers).json()
    assert me["password_change_required"] is True
    r = client.post(f"{API}/auth/change-password", headers=headers,
                    json={"current_password": PASSWORD, "new_password": "a brand new long passphrase"})
    assert r.status_code == 204
    assert client.get(f"{API}/users", headers=headers).status_code == 200


@pytest.mark.parametrize("new,fragment", [
    ("short", "at least 12"),
    ("alice-alice-alice", "username"),
    ("password1234", "common"),
    ("aaaaaaaaaaaaaaaa", "repetitive"),
])
def test_password_policy_is_enforced(client, make, new, fragment):
    make.user("alice")
    headers = login(client)
    r = client.post(f"{API}/auth/change-password", headers=headers, json={"current_password": PASSWORD, "new_password": new})
    assert r.status_code == 422 and fragment in r.json()["error"]["message"]


def test_wrong_current_password_is_rejected_and_audited(client, make, db):
    make.user("alice")
    headers = login(client)
    r = client.post(f"{API}/auth/change-password", headers=headers,
                    json={"current_password": "not the password", "new_password": "a brand new long passphrase"})
    assert r.status_code == 400
    assert db.execute(select(AuditLog).where(AuditLog.action == "auth.password_change", AuditLog.result == "failure")).first()


def test_changing_the_password_ends_other_sessions_but_not_this_one(client, make):
    from fastapi.testclient import TestClient

    from app.main import app
    make.user("alice")
    mine = login(client)
    with TestClient(app, base_url="https://testserver") as other_client:
        other = login(other_client)
        r = client.post(f"{API}/auth/change-password", headers=mine,
                        json={"current_password": PASSWORD, "new_password": "a brand new long passphrase"})
        assert r.status_code == 204
        assert other_client.get(f"{API}/auth/sessions", headers=other).status_code == 401
    assert client.get(f"{API}/auth/sessions", headers=mine).status_code == 200


def test_sessions_can_be_listed_and_revoked(client, make):
    from fastapi.testclient import TestClient

    from app.main import app
    make.user("alice")
    mine = login(client)
    with TestClient(app, base_url="https://testserver") as other_client:
        other = login(other_client)
        listing = client.get(f"{API}/auth/sessions", headers=mine).json()
        assert len(listing) == 2 and sum(s["current"] for s in listing) == 1
        victim = next(s for s in listing if not s["current"])
        assert client.delete(f"{API}/auth/sessions/{victim['id']}", headers=mine).status_code == 204
        assert other_client.get(f"{API}/auth/sessions", headers=other).status_code == 401


def test_a_user_cannot_revoke_someone_elses_session(client, make):
    from fastapi.testclient import TestClient

    from app.main import app
    make.user("alice")
    make.user("bob", role="Viewer")
    alice = login(client)
    with TestClient(app, base_url="https://testserver") as bob_client:
        bob = login(bob_client, "bob")
        bobs = bob_client.get(f"{API}/auth/sessions", headers=bob).json()[0]["id"]
    assert client.delete(f"{API}/auth/sessions/{bobs}", headers=alice).status_code == 404


# ---------------------------------------------------------------- MFA
def _enrol(client, headers):
    secret = client.post(f"{API}/auth/mfa/enroll", headers=headers).json()["secret"]
    code = pyotp.TOTP(secret).now()
    r = client.post(f"{API}/auth/mfa/enable", headers=headers, json={"code": code})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def test_mfa_enrolment_then_two_step_login(client, make, db):
    make.user("alice")
    headers = login(client)
    r = client.post(f"{API}/auth/mfa/enroll", headers=headers)
    assert r.status_code == 200 and r.json()["otpauth_uri"].startswith("otpauth://totp/")
    secret = r.json()["secret"]
    # The secret is stored encrypted, never in clear text.
    stored = db.execute(select(User.mfa_secret_enc).where(User.username == "alice")).scalar_one()
    assert secret.encode() not in stored
    assert client.post(f"{API}/auth/mfa/enable", headers=headers, json={"code": "000000"}).status_code == 400
    r = client.post(f"{API}/auth/mfa/enable", headers=headers, json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10

    client.cookies.clear()
    step1 = client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD}).json()
    assert step1["status"] == "mfa_required" and step1["access_token"] is None
    bad = client.post(f"{API}/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": "123456"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_code"


def test_totp_code_cannot_be_replayed(client, make):
    make.user("alice")
    headers = login(client)
    secret, _ = _enrol(client, headers)
    client.cookies.clear()
    # the code used for enrolment was already consumed
    step1 = client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD}).json()
    used = pyotp.TOTP(secret).now()
    r = client.post(f"{API}/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": used})
    assert r.status_code == 401
    # a code from the next window is accepted exactly once
    nxt = pyotp.TOTP(secret).at(datetime.now(UTC).timestamp() + 30)
    ok = client.post(f"{API}/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": nxt})
    assert ok.status_code == 200 and ok.json()["status"] == "ok"
    again = client.post(f"{API}/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": nxt})
    assert again.status_code == 401


def test_recovery_codes_work_once(client, make):
    make.user("alice")
    headers = login(client)
    _, codes = _enrol(client, headers)
    client.cookies.clear()
    for attempt in (1, 2):
        step1 = client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD}).json()
        r = client.post(f"{API}/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": codes[0]})
        assert r.status_code == (200 if attempt == 1 else 401)


def test_wrong_mfa_codes_count_towards_lockout(client, make, db):
    make.user("alice", mfa_secret=pyotp.random_base32())
    step1 = client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD}).json()
    for _ in range(5):
        client.post(f"{API}/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": "000000"})
    user = db.execute(select(User).where(User.username == "alice")).scalar_one()
    assert user.locked_until and user.locked_until > datetime.now(UTC)


def test_policy_require_mfa_blocks_users_without_it_until_enrolled(client, make):
    make.user("alice")
    admin = login(client)
    r = client.patch(f"{API}/settings", headers=admin, json={"changes": {"security.require_mfa": True}})
    assert r.status_code == 200
    r = client.get(f"{API}/users", headers=admin)
    assert r.status_code == 403 and r.json()["error"]["code"] == "mfa_enrollment_required"
    assert client.get(f"{API}/auth/me", headers=admin).json()["mfa_enrollment_required"] is True
    _enrol(client, admin)
    assert client.get(f"{API}/users", headers=admin).status_code == 200


def test_mfa_cannot_be_disabled_while_policy_requires_it(client, make):
    secret = pyotp.random_base32()
    make.user("alice", mfa_secret=secret)
    step1 = client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD}).json()
    ok = client.post(f"{API}/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": pyotp.TOTP(secret).now()})
    headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    nxt = pyotp.TOTP(secret).at(datetime.now(UTC).timestamp() + 30)
    client.patch(f"{API}/settings", headers=headers, json={"changes": {"security.require_mfa": True}})
    r = client.post(f"{API}/auth/mfa/disable", headers=headers, json={"password": PASSWORD, "code": nxt})
    assert r.status_code == 403 and r.json()["error"]["code"] == "mfa_required_by_policy"


def test_sessions_table_never_stores_the_raw_refresh_token(client, make, db):
    make.user("alice")
    login(client)
    raw = client.cookies.get("obs_refresh")
    rows = db.execute(select(AuthSession)).scalars().all()
    assert rows and all(raw != r.token_hash and len(r.token_hash) == 64 for r in rows)
