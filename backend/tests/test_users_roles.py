from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role, User
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.usefixtures("db_clean")
API = "/api/v1"


def _role_id(make, name):
    return str(make.role(name).id)


# ---- the permission matrix is actually enforced -------------------------------------------
ENDPOINTS = [
    # (method, path, permission needed)
    ("GET", "/users", "users.view"),
    ("GET", "/roles", "roles.view"),
    ("GET", "/permissions", "roles.view"),
    ("GET", "/audit", "audit.view"),
    ("GET", "/audit/verify", "audit.view"),
    ("GET", "/settings", "settings.view"),
    ("GET", "/system/status", "system.view"),
]


@pytest.mark.parametrize("role", ["Admin", "DevOps", "NOC", "Developer", "Viewer", "Auditor"])
def test_every_builtin_role_gets_exactly_the_endpoints_its_permissions_allow(client, make, role):
    make.user("tester", role=role)
    headers = login(client, "tester")
    granted = set(client.get(f"{API}/auth/me", headers=headers).json()["permissions"])
    for method, path, needed in ENDPOINTS:
        r = client.request(method, f"{API}{path}", headers=headers)
        if needed in granted:
            assert r.status_code == 200, f"{role} should reach {path}: {r.text}"
        else:
            assert r.status_code == 403, f"{role} must NOT reach {path}"
            assert r.json()["error"]["code"] == "forbidden"


def test_denied_requests_are_audited(client, make, db):
    make.user("viewer1", role="Viewer")
    headers = login(client, "viewer1")
    assert client.get(f"{API}/users", headers=headers).status_code == 403
    row = db.execute(select(AuditLog).where(AuditLog.action == "access.denied")).scalar_one()
    assert row.result == "denied" and row.actor_name == "viewer1" and "users.view" in row.detail


def test_only_users_manage_can_create_users(client, make):
    make.user("auditor1", role="Auditor")  # may list users but not manage them
    headers = login(client, "auditor1")
    assert client.get(f"{API}/users", headers=headers).status_code == 200
    r = client.post(f"{API}/users", headers=headers, json={"username": "newbie", "role_id": _role_id(make, "Viewer")})
    assert r.status_code == 403


# ---- users --------------------------------------------------------------------------------
def test_create_user_generates_a_one_time_password_and_forces_change(client, make, db):
    make.user("alice")
    headers = login(client)
    r = client.post(f"{API}/users", headers=headers, json={
        "username": "Bob.Smith", "email": "bob@example.com", "full_name": "Bob", "role_id": _role_id(make, "NOC")})
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["username"] == "bob.smith" and body["user"]["must_change_password"] is True
    temp = body["temporary_password"]
    assert temp and len(temp) >= 16
    # the password is not stored or audited in clear text
    row = db.execute(select(AuditLog).where(AuditLog.action == "user.create")).scalar_one()
    assert temp not in str(row.new_value) and temp not in str(row.detail)
    client.cookies.clear()
    bob = login(client, "bob.smith", temp)
    assert client.get(f"{API}/users", headers=bob).json()["error"]["code"] == "password_change_required"


def test_create_user_with_supplied_password_does_not_echo_it_and_enforces_policy(client, make):
    make.user("alice")
    headers = login(client)
    weak = client.post(f"{API}/users", headers=headers, json={
        "username": "carol", "role_id": _role_id(make, "Viewer"), "password": "short"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "weak_password"
    ok = client.post(f"{API}/users", headers=headers, json={
        "username": "carol", "role_id": _role_id(make, "Viewer"), "password": "a long enough passphrase"})
    assert ok.status_code == 201 and ok.json()["temporary_password"] is None


@pytest.mark.parametrize("name", ["ab", "Has Space", "1starts-with-digit", "x" * 40, "semi;colon"])
def test_invalid_usernames_are_rejected(client, make, name):
    make.user("alice")
    headers = login(client)
    r = client.post(f"{API}/users", headers=headers, json={"username": name, "role_id": _role_id(make, "Viewer")})
    assert r.status_code == 422


def test_duplicate_username_is_a_conflict(client, make):
    make.user("alice")
    headers = login(client)
    r = client.post(f"{API}/users", headers=headers, json={"username": "ALICE", "role_id": _role_id(make, "Viewer")})
    assert r.status_code == 409


def test_update_user_audits_old_and_new_values(client, make, db):
    make.user("alice")
    bob = make.user("bob", role="Viewer")
    headers = login(client)
    r = client.patch(f"{API}/users/{bob.id}", headers=headers, json={"role_id": _role_id(make, "DevOps"), "full_name": "Bob B"})
    assert r.status_code == 200 and r.json()["role"]["name"] == "DevOps"
    row = db.execute(select(AuditLog).where(AuditLog.action == "user.update")).scalar_one()
    assert row.old_value["role"] == "Viewer" and row.new_value["role"] == "DevOps"
    assert row.resource_name == "bob" and row.result == "success"


def test_disabling_a_user_ends_their_sessions(client, make):
    from fastapi.testclient import TestClient

    from app.main import app
    make.user("alice")
    bob = make.user("bob", role="Viewer")
    admin = login(client)
    with TestClient(app, base_url="https://testserver") as bob_client:
        bobs = login(bob_client, "bob")
        assert client.patch(f"{API}/users/{bob.id}", headers=admin, json={"is_active": False}).status_code == 200
        assert bob_client.get(f"{API}/auth/me", headers=bobs).status_code == 401
        r = bob_client.post(f"{API}/auth/login", json={"username": "bob", "password": PASSWORD})
        assert r.status_code == 401


def test_admin_cannot_disable_themselves_or_remove_the_last_administrator(client, make):
    alice = make.user("alice")
    headers = login(client)
    r = client.patch(f"{API}/users/{alice.id}", headers=headers, json={"is_active": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "cannot_disable_self"
    r = client.patch(f"{API}/users/{alice.id}", headers=headers, json={"role_id": _role_id(make, "Viewer")})
    assert r.status_code == 409 and r.json()["error"]["code"] == "last_admin"
    # nothing changed
    assert client.get(f"{API}/users/{alice.id}", headers=headers).json()["role"]["name"] == "Admin"


def test_reset_password_issues_a_temporary_password_and_ends_sessions(client, make, db):
    make.user("alice")
    bob = make.user("bob", role="Viewer")
    admin = login(client)
    r = client.post(f"{API}/users/{bob.id}/reset-password", headers=admin)
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    client.cookies.clear()
    assert login(client, "bob", temp)
    assert db.execute(select(AuditLog).where(AuditLog.action == "user.reset_password")).first()


def test_unlock_and_reset_mfa(client, make, db):
    import pyotp
    make.user("alice")
    bob = make.user("bob", role="Viewer", mfa_secret=pyotp.random_base32())
    bob = db.get(User, bob.id)
    bob.failed_attempts, bob.locked_until = 0, __import__("datetime").datetime.now(__import__("datetime").UTC) + __import__("datetime").timedelta(hours=1)
    db.commit()
    admin = login(client)
    assert client.get(f"{API}/users/{bob.id}", headers=admin).json()["locked"] is True
    assert client.post(f"{API}/users/{bob.id}/unlock", headers=admin).status_code == 204
    assert client.get(f"{API}/users/{bob.id}", headers=admin).json()["locked"] is False
    assert client.post(f"{API}/users/{bob.id}/reset-mfa", headers=admin).status_code == 204
    assert client.get(f"{API}/users/{bob.id}", headers=admin).json()["mfa_enabled"] is False


# ---- roles --------------------------------------------------------------------------------
def test_builtin_roles_exist_with_the_documented_matrix(client, make):
    make.user("alice")
    headers = login(client)
    roles = {r["name"]: r for r in client.get(f"{API}/roles", headers=headers).json()}
    assert set(roles) == {"Admin", "DevOps", "NOC", "Developer", "Viewer", "Auditor"}
    assert roles["Admin"]["is_superuser"] and roles["Admin"]["is_system"]
    assert "users.manage" not in roles["DevOps"]["permissions"]
    assert "logs.view" not in roles["Viewer"]["permissions"]
    assert "audit.view" in roles["Auditor"]["permissions"]
    perms = {p["key"] for p in client.get(f"{API}/permissions", headers=headers).json()}
    assert {"users.manage", "automation.approve", "actions.execute", "thresholds.modify"} <= perms


def test_custom_role_lifecycle(client, make, db):
    make.user("alice")
    headers = login(client)
    r = client.post(f"{API}/roles", headers=headers, json={
        "name": "Log Reader", "description": "only logs", "permissions": ["logs.view", "hosts.view"]})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.post(f"{API}/roles", headers=headers, json={"name": "log reader", "permissions": []}).status_code == 409
    assert client.post(f"{API}/roles", headers=headers, json={"name": "Bad", "permissions": ["nope.nope"]}).status_code == 422
    r = client.put(f"{API}/roles/{rid}", headers=headers, json={
        "name": "Log Reader", "description": "logs and metrics", "permissions": ["logs.view", "metrics.view"]})
    assert r.status_code == 200 and r.json()["permissions"] == ["logs.view", "metrics.view"]
    user = make.user("dave", role="Viewer")
    client.patch(f"{API}/users/{user.id}", headers=headers, json={"role_id": rid})
    assert client.delete(f"{API}/roles/{rid}", headers=headers).json()["error"]["code"] == "role_in_use"
    client.patch(f"{API}/users/{user.id}", headers=headers, json={"role_id": _role_id(make, "Viewer")})
    assert client.delete(f"{API}/roles/{rid}", headers=headers).status_code == 204
    actions = [a for (a,) in db.execute(select(AuditLog.action).where(AuditLog.action.like("role.%"))).all()]
    assert {"role.create", "role.update", "role.delete"} <= set(actions)


def test_builtin_roles_cannot_be_edited_or_deleted(client, make):
    make.user("alice")
    headers = login(client)
    rid = _role_id(make, "DevOps")
    r = client.put(f"{API}/roles/{rid}", headers=headers, json={"name": "DevOps", "permissions": ["users.manage"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "system_role"
    assert client.delete(f"{API}/roles/{rid}", headers=headers).status_code == 409


def test_a_custom_role_grants_exactly_its_permissions(client, make):
    make.user("alice")
    admin = login(client)
    rid = client.post(f"{API}/roles", headers=admin, json={"name": "Only Settings", "permissions": ["settings.view"]}).json()["id"]
    user = make.user("eve", role="Viewer")
    client.patch(f"{API}/users/{user.id}", headers=admin, json={"role_id": rid})
    client.cookies.clear()
    eve = login(client, "eve")
    assert client.get(f"{API}/settings", headers=eve).status_code == 200
    assert client.get(f"{API}/users", headers=eve).status_code == 403
    assert client.patch(f"{API}/settings", headers=eve, json={"changes": {"general.instance_name": "x"}}).status_code == 403
