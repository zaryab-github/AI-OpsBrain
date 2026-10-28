import asyncpg
import pytest
from sqlalchemy import select

from app.db import sessionmaker
from app.models import AuditLog
from tests.integration.conftest import csrf, login_full

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_viewer_denied_admin_routes_and_denial_audited(client, users):
    username = await login_full(client, users, ["Viewer"])
    for path in ("/api/v1/users", "/api/v1/roles", "/api/v1/audit", "/api/v1/settings", "/api/v1/system/health"):
        assert (await client.get(path)).status_code == 403, path
    async with sessionmaker()() as s:
        denied = (await s.execute(select(AuditLog).where(AuditLog.actor_name == username,
                                                         AuditLog.result == "denied"))).scalars().all()
    assert len(denied) == 5
    assert {d.detail for d in denied} >= {"Missing permission users.manage", "Missing permission audit.view"}


async def test_auditor_can_read_audit_but_not_manage(client, users):
    await login_full(client, users, ["Auditor"])
    assert (await client.get("/api/v1/audit")).status_code == 200
    assert (await client.get("/api/v1/settings")).status_code == 200
    assert (await client.put("/api/v1/settings/security.lockout_minutes", json={"value": 20})).status_code == 403
    assert (await client.get("/api/v1/users")).status_code == 403


async def test_user_lifecycle(client, users):
    await login_full(client, users, ["Admin"])
    r = await client.post("/api/v1/users", json={"username": "New.Person", "email": "New.Person@Example.test",
                                                 "full_name": "New Person", "roles": ["NOC"]})
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["user"]["username"] == "new.person" and created["user"]["must_change_password"]
    temp = created["temporary_password"]
    uid = created["user"]["id"]

    dup = await client.post("/api/v1/users", json={"username": "new.person", "email": "x@example.test",
                                                   "roles": ["NOC"]})
    assert dup.status_code == 409
    bad_role = await client.post("/api/v1/users", json={"username": "zz", "email": "zz@example.test",
                                                        "roles": ["Wizard"]})
    assert bad_role.status_code == 400

    r = await client.patch(f"/api/v1/users/{uid}", json={"roles": ["Developer", "Viewer"]})
    assert r.json()["roles"] == ["Developer", "Viewer"]

    from httpx import ASGITransport, AsyncClient

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as newbie:
        r = await newbie.post("/api/v1/auth/login", json={"username": "new.person", "password": temp})
        assert r.json()["state"] == "password_change_required"
        assert (await client.patch(f"/api/v1/users/{uid}", json={"is_active": False})).status_code == 200
        assert (await newbie.get("/api/v1/auth/me")).status_code == 401
        r = await newbie.post("/api/v1/auth/login", json={"username": "new.person", "password": temp})
        assert r.status_code == 401

    r = await client.post(f"/api/v1/users/{uid}/reset-password")
    assert r.status_code == 200 and r.json()["temporary_password"] != temp

    async with sessionmaker()() as s:
        actions = [a.action for a in (await s.execute(
            select(AuditLog).where(AuditLog.resource_id == uid).order_by(AuditLog.id))).scalars()]
    assert actions[:1] == ["user.create"] and "user.update" in actions and "user.password_reset" in actions
    async with sessionmaker()() as s:
        upd = (await s.execute(select(AuditLog).where(AuditLog.resource_id == uid, AuditLog.action == "user.update")
                               .order_by(AuditLog.id).limit(1))).scalar_one()
    assert upd.old_value["roles"] == ["NOC"] and upd.new_value["roles"] == ["Developer", "Viewer"]


async def test_cannot_lock_out_last_admin(client, users):
    me = await login_full(client, users, ["Admin"])
    all_users = (await client.get("/api/v1/users")).json()
    mine = next(u for u in all_users if u["username"] == me)
    assert (await client.patch(f"/api/v1/users/{mine['id']}", json={"is_active": False})).status_code == 409
    # Demote every *other* admin, then demoting myself must fail.
    for u in all_users:
        if "Admin" in u["roles"] and u["id"] != mine["id"] and u["is_active"]:
            assert (await client.patch(f"/api/v1/users/{u['id']}", json={"roles": ["Viewer"]})).status_code == 200
    r = await client.patch(f"/api/v1/users/{mine['id']}", json={"roles": ["Viewer"]})
    assert r.status_code == 409 and "Admin" in r.json()["detail"]


async def test_roles_crud_and_guards(client, users):
    await login_full(client, users, ["Admin"])
    roles = (await client.get("/api/v1/roles")).json()
    names = {r["name"] for r in roles}
    assert {"Admin", "DevOps", "NOC", "Developer", "Viewer", "Auditor"} <= names
    admin = next(r for r in roles if r["name"] == "Admin")
    assert (await client.patch(f"/api/v1/roles/{admin['id']}", json={"permissions": []})).status_code == 409
    assert (await client.delete(f"/api/v1/roles/{admin['id']}")).status_code == 409

    perms = (await client.get("/api/v1/roles/permissions")).json()
    assert any(p["key"] == "automation.approve" for p in perms)
    r = await client.post("/api/v1/roles", json={"name": "DB Team", "permissions": ["metrics.view", "logs.view"]})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert (await client.post("/api/v1/roles", json={"name": "Bad", "permissions": ["x.y"]})).status_code == 400
    r = await client.patch(f"/api/v1/roles/{rid}", json={"permissions": ["metrics.view"]})
    assert r.json()["permissions"] == ["metrics.view"]
    await client.post("/api/v1/users", json={"username": "dbguy", "email": "dbguy@example.test", "roles": ["DB Team"]})
    assert (await client.delete(f"/api/v1/roles/{rid}")).status_code == 409


async def test_settings_update_validated_and_audited(client, users):
    await login_full(client, users, ["Admin"])
    assert (await client.put("/api/v1/settings/security.lockout_minutes", json={"value": 0})).status_code == 400
    assert (await client.put("/api/v1/settings/nope", json={"value": 1})).status_code == 404
    r = await client.put("/api/v1/settings/security.lockout_minutes", json={"value": 20})
    assert r.status_code == 200 and r.json()["value"] == 20
    values = {s["key"]: s["value"] for s in (await client.get("/api/v1/settings")).json()}
    assert values["security.lockout_minutes"] == 20
    async with sessionmaker()() as s:
        row = (await s.execute(select(AuditLog).where(AuditLog.action == "setting.update")
                               .order_by(AuditLog.id.desc()).limit(1))).scalar_one()
    assert row.old_value == {"value": 15} and row.new_value == {"value": 20}
    await client.put("/api/v1/settings/security.lockout_minutes", json={"value": 15})


async def test_mfa_policy_all_applies_to_everyone(client, users):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    await login_full(client, users, ["Admin"])
    assert (await client.put("/api/v1/settings/security.mfa_required", json={"value": "all"})).status_code == 200
    try:
        username, password, _ = await users.create(["Viewer"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as v:
            r = await v.post("/api/v1/auth/login", json={"username": username, "password": password})
            assert r.json()["state"] == "mfa_enrollment_required"
    finally:
        await client.put("/api/v1/settings/security.mfa_required", json={"value": "admins"})


async def test_audit_list_filter_export_and_verify(client, users):
    await login_full(client, users, ["Auditor"])
    page = (await client.get("/api/v1/audit", params={"limit": 5})).json()
    assert len(page["items"]) == 5 and page["next_before_id"] is not None
    nxt = (await client.get("/api/v1/audit", params={"limit": 5, "before_id": page["next_before_id"]})).json()
    assert nxt["items"][0]["id"] < page["items"][-1]["id"]
    only_fail = (await client.get("/api/v1/audit", params={"result": "failure"})).json()["items"]
    assert only_fail and all(i["result"] == "failure" for i in only_fail)
    r = await client.get("/api/v1/audit/export.csv", params={"action": "auth."})
    assert r.status_code == 200 and r.text.splitlines()[0].startswith("id,ts,actor_name")
    csrf(client)
    v = (await client.post("/api/v1/audit/verify")).json()
    assert v["ok"] and v["checked"] > 10


async def test_audit_log_is_append_only(owner_conn: asyncpg.Connection):
    from tests.integration.conftest import APP_PW, APP_ROLE, DB_NAME, _plain, _url_for
    app_conn = await asyncpg.connect(_plain(_url_for(DB_NAME, APP_ROLE, APP_PW)))
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute("UPDATE audit_log SET detail = 'x'")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute("DELETE FROM audit_log")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute("TRUNCATE audit_log")
    finally:
        await app_conn.close()
    # Even the owner is stopped by the trigger.
    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        await owner_conn.execute("UPDATE audit_log SET detail = 'x'")
    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        await owner_conn.execute("DELETE FROM audit_log")


async def test_tampering_is_detected(owner_conn: asyncpg.Connection):
    from app.services import audit
    async with sessionmaker()() as s:
        assert (await audit.verify_chain(s)).ok
    target = await owner_conn.fetchval("SELECT max(id) - 1 FROM audit_log")
    original = await owner_conn.fetchval("SELECT detail FROM audit_log WHERE id = $1", target)
    # Simulate an attacker with superuser rights bypassing the trigger.
    await owner_conn.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_modify")
    try:
        await owner_conn.execute("UPDATE audit_log SET detail = 'covered up' WHERE id = $1", target)
        async with sessionmaker()() as s:
            report = await audit.verify_chain(s)
        assert not report.ok and report.first_bad_id == target
    finally:
        await owner_conn.execute("UPDATE audit_log SET detail = $2 WHERE id = $1", target, original)
        await owner_conn.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_modify")
    async with sessionmaker()() as s:
        assert (await audit.verify_chain(s)).ok


async def test_system_endpoints(client, users):
    assert (await client.get("/api/health/live")).json() == {"status": "ok"}
    assert (await client.get("/api/health/ready")).json() == {"status": "ok"}
    assert (await client.get("/api/v1/system/modules")).status_code == 401
    await login_full(client, users, ["Admin"])
    mods = {m["key"]: m for m in (await client.get("/api/v1/system/modules")).json()["modules"]}
    assert mods["core"]["installed"] and not mods["logging"]["installed"]
    health = (await client.get("/api/v1/system/health")).json()
    comps = {c["component"]: c["status"] for c in health["checks"]}
    assert comps["database"] == "ok" and comps["redis"] == "ok"
    # No worker runs in this test process, so the platform must report that honestly.
    assert comps["worker"] == "critical"
    metrics = await client.get("/api/metrics")
    assert "opsbrain_api_requests_total" in metrics.text
