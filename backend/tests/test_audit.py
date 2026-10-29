from __future__ import annotations

import threading

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import audit
from app.db import get_engine, session_factory
from app.models import AuditLog
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("db_clean")
API = "/api/v1"


def _write(n: int, prefix: str = "test.event"):
    for i in range(n):
        audit.record_independent(action=f"{prefix}.{i}", actor_name="tester", detail=f"entry {i}")


def test_chain_links_every_entry_and_verifies(db):
    _write(5)
    rows = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    assert rows[0].prev_hash == audit.GENESIS
    for earlier, later in zip(rows, rows[1:], strict=False):
        assert later.prev_hash == earlier.hash
    result = audit.verify_chain(db)
    assert result.ok and result.checked == 5


def test_database_refuses_update_delete_and_truncate(db):
    _write(2)
    for sql in ("UPDATE audit_log SET detail = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
        with pytest.raises(DBAPIError, match="append-only"):
            with get_engine().begin() as conn:
                conn.execute(text(sql))


def test_tampering_is_detected_even_if_the_guard_is_bypassed(db):
    _write(6)
    ids = [i for (i,) in db.execute(select(AuditLog.id).order_by(AuditLog.id)).all()]
    with get_engine().begin() as conn:  # an attacker with DB superuser rights disables the guard...
        conn.execute(text("SET LOCAL obs.audit_maintenance = 'on'"))
        conn.execute(text("UPDATE audit_log SET detail = 'edited' WHERE id = :i"), {"i": ids[2]})
    result = audit.verify_chain(db)  # ...but the HMAC chain still catches the edit
    assert not result.ok and result.first_bad_id == ids[2]


def test_deleting_a_middle_entry_breaks_the_chain(db):
    _write(6)
    ids = [i for (i,) in db.execute(select(AuditLog.id).order_by(AuditLog.id)).all()]
    with get_engine().begin() as conn:
        conn.execute(text("SET LOCAL obs.audit_maintenance = 'on'"))
        conn.execute(text("DELETE FROM audit_log WHERE id = :i"), {"i": ids[3]})
    result = audit.verify_chain(db)
    assert not result.ok and result.first_bad_id == ids[4]


def test_tail_verification_checks_only_recent_entries(db):
    _write(10)
    assert audit.verify_chain(db, tail=3).checked == 3


def test_concurrent_writers_still_produce_one_linear_chain(db):
    errors = []

    def worker(n):
        try:
            for i in range(10):
                audit.record_independent(action="load.test", actor_name=f"w{n}", detail=str(i))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    result = audit.verify_chain(db)
    assert result.ok and result.checked == 60


def test_secrets_are_redacted_before_they_are_stored(db):
    audit.record(db, action="x.test", actor_name="t", new={"password": "hunter2", "api_token": "abc",
                                                           "nested": {"mfa_secret": "S3CR3T"}, "note": "fine"})
    db.commit()
    row = db.execute(select(AuditLog)).scalar_one()
    assert row.new_value == {"password": "[redacted]", "api_token": "[redacted]",
                             "nested": {"mfa_secret": "[redacted]"}, "note": "fine"}


def test_an_invalid_result_value_is_refused(db):
    with pytest.raises(ValueError):
        audit.record(db, action="x", result="maybe", actor_name="t")


def test_audit_api_lists_filters_and_paginates(client, make):
    make.user("alice")
    headers = login(client)
    _write(7, prefix="bulk")
    page1 = client.get(f"{API}/audit?limit=5", headers=headers).json()
    assert len(page1["items"]) == 5 and page1["next_before_id"]
    page2 = client.get(f"{API}/audit?limit=5&before_id={page1['next_before_id']}", headers=headers).json()
    assert {i["id"] for i in page1["items"]}.isdisjoint({i["id"] for i in page2["items"]})
    only = client.get(f"{API}/audit?action=bulk.&actor=tester", headers=headers).json()["items"]
    assert len(only) == 7 and all(i["action"].startswith("bulk.") for i in only)
    assert client.get(f"{API}/audit?result=bogus", headers=headers).status_code == 422
    found = client.get(f"{API}/audit?q=entry 3", headers=headers).json()["items"]
    assert [i["detail"] for i in found] == ["entry 3"]


def test_audit_api_verify_endpoint(client, make, db):
    make.user("alice")
    headers = login(client)
    body = client.get(f"{API}/audit/verify", headers=headers).json()
    assert body["ok"] is True and body["checked"] >= 1
    with get_engine().begin() as conn:
        conn.execute(text("SET LOCAL obs.audit_maintenance = 'on'"))
        conn.execute(text("UPDATE audit_log SET actor_name = 'mallory' WHERE id = 1"))
    bad = client.get(f"{API}/audit/verify", headers=headers).json()
    assert bad["ok"] is False and bad["first_bad_id"] == 1


def test_csv_export_is_audited_and_neutralises_formula_injection(client, make):
    make.user("alice")
    headers = login(client)
    audit.record_independent(action="=HYPERLINK(\"http://evil\")", actor_name="tester", detail="@cmd|' /C calc'!A0")
    r = client.get(f"{API}/audit/export.csv", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.splitlines()
    assert lines[0].startswith("id,time_utc,actor,action")
    assert "'=HYPERLINK" in r.text and "'@cmd" in r.text
    assert not any(cell.startswith("=") for line in lines[1:] for cell in line.split(","))
    export_rows = client.get(f"{API}/audit?action=audit.export", headers=headers).json()["items"]
    assert len(export_rows) == 1


def test_the_audit_api_has_no_write_endpoints(client, make):
    make.user("alice")
    headers = login(client)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, f"{API}/audit", headers=headers).status_code == 405
    assert session_factory()  # keeps import used
