from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("db_clean")
API = "/api/v1"


def test_settings_have_safe_defaults(client, make):
    make.user("alice")
    headers = login(client)
    values = {s["key"]: s["value"] for s in client.get(f"{API}/settings", headers=headers).json()}
    assert values["security.require_mfa"] is False
    assert values["security.password_min_length"] == 12
    assert values["security.lockout_threshold"] == 5
    assert values["selfmon.heartbeat_url"] == ""


def test_change_a_setting_is_validated_persisted_and_audited(client, make, db):
    make.user("alice")
    headers = login(client)
    r = client.patch(f"{API}/settings", headers=headers, json={"changes": {"security.lockout_threshold": 3, "general.instance_name": "Prod Observability"}})
    assert r.status_code == 200
    values = {s["key"]: s["value"] for s in r.json()}
    assert values["security.lockout_threshold"] == 3 and values["general.instance_name"] == "Prod Observability"
    rows = db.execute(select(AuditLog).where(AuditLog.action == "setting.update").order_by(AuditLog.id)).scalars().all()
    assert {(r.resource_name, r.old_value["value"], r.new_value["value"]) for r in rows} == {
        ("security.lockout_threshold", 5, 3), ("general.instance_name", "AI Observability Platform", "Prod Observability")}


@pytest.mark.parametrize("changes", [
    {"security.lockout_threshold": 1},
    {"security.lockout_threshold": "five"},
    {"security.lockout_threshold": True},
    {"security.require_mfa": "yes"},
    {"security.password_min_length": 8},
    {"selfmon.heartbeat_url": "http://insecure.example"},
    {"general.instance_name": "   "},
    {"unknown.key": 1},
])
def test_invalid_settings_are_rejected_and_nothing_is_applied(client, make, changes):
    make.user("alice")
    headers = login(client)
    r = client.patch(f"{API}/settings", headers=headers, json={"changes": {**changes, "general.instance_name": "should not stick"}})
    assert r.status_code == 422
    values = {s["key"]: s["value"] for s in client.get(f"{API}/settings", headers=headers).json()}
    assert values["general.instance_name"] == "AI Observability Platform"


def test_unchanged_values_do_not_create_audit_noise(client, make, db):
    make.user("alice")
    headers = login(client)
    client.patch(f"{API}/settings", headers=headers, json={"changes": {"security.lockout_threshold": 5}})
    assert db.execute(select(AuditLog).where(AuditLog.action == "setting.update")).first() is None


def test_lockout_threshold_setting_is_honoured(client, make):
    make.user("alice")
    admin = login(client)
    client.patch(f"{API}/settings", headers=admin, json={"changes": {"security.lockout_threshold": 3}})
    make.user("bob", role="Viewer")
    client.cookies.clear()
    for _ in range(3):
        client.post(f"{API}/auth/login", json={"username": "bob", "password": "wrong-password-1"})
    r = client.post(f"{API}/auth/login", json={"username": "bob", "password": "correct horse battery staple"})
    assert r.status_code == 401


# ---- system ----
def test_health_is_public_and_minimal(client):
    r = client.get(f"{API}/system/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_public_info_is_limited_to_the_instance_name(client):
    assert client.get(f"{API}/system/public").json() == {"instance_name": "AI Observability Platform"}


def test_status_requires_permission_and_reports_checks(client, make, db):
    from app import selfmon
    make.user("alice")
    make.user("viewer1", role="Viewer")
    assert client.get(f"{API}/system/status").status_code == 401
    selfmon.store(db, "backend", selfmon.run_backend_checks(db))
    selfmon.store(db, "worker", [selfmon.Result("worker.heartbeat", "ok", "running")])
    db.commit()
    headers = login(client)
    body = client.get(f"{API}/system/status", headers=headers).json()
    names = {c["name"]: c for c in body["checks"]}
    assert names["database"]["status"] == "ok"
    assert names["migrations"]["status"] == "ok"
    assert names["audit.chain"]["status"] == "ok"
    assert names["watchdog"]["status"] == "warn"  # no host watchdog report yet: stated honestly
    assert body["overall"] == "warn"
    client.cookies.clear()
    assert client.get(f"{API}/system/status", headers=login(client, "viewer1")).status_code == 403


def test_stale_worker_heartbeat_is_critical(client, make, db):
    from datetime import UTC, datetime, timedelta

    from app import selfmon
    from app.models import SelfmonCheck
    make.user("alice")
    selfmon.store(db, "worker", [selfmon.Result("worker.heartbeat", "ok", "running")])
    db.commit()
    row = db.get(SelfmonCheck, "worker.heartbeat")
    row.checked_at = datetime.now(UTC) - timedelta(minutes=10)
    db.commit()
    headers = login(client)
    checks = {c["name"]: c for c in client.get(f"{API}/system/status", headers=headers).json()["checks"]}
    assert checks["worker.heartbeat"]["status"] == "crit" and checks["worker.heartbeat"]["stale"] is True


def test_metrics_need_the_bearer_token_and_are_not_documented(client, make):
    from app.config import get_config
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/metrics", headers={"Authorization": f"Bearer {get_config().metrics_token}"})
    assert r.status_code == 200
    assert "obs_build_info" in r.text and "obs_http_requests_total" in r.text
    assert client.get("/api/openapi.json").status_code in (200, 404)  # docs exist only outside production
