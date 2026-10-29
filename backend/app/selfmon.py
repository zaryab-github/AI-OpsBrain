"""Platform self-monitoring that works even if no Monitoring module is installed.

Three sources feed the ``selfmon_checks`` table:
  * backend  - checks the API itself runs (database, migrations, audit chain)
  * worker   - the background worker's heartbeat
  * watchdog - host-level checks reported by ``obsctl core watchdog`` (containers, disk, TLS, backups)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import audit
from app.models import SelfmonCheck
from app.schemas import CheckOut

WORKER_STALE = timedelta(seconds=120)
WATCHDOG_STALE = timedelta(minutes=15)
_SEVERITY = {"ok": 0, "warn": 1, "crit": 2}


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


def _alembic_head() -> str | None:
    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    if not ini.exists():
        return None
    cfg = AlembicConfig(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def check_database(db: Session) -> Result:
    start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        size = db.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
    except Exception as exc:  # noqa: BLE001 - report any failure as a critical check
        return Result("database", "crit", f"query failed: {type(exc).__name__}")
    ms = (time.perf_counter() - start) * 1000
    status = "ok" if ms < 500 else "warn"
    return Result("database", status, f"responded in {ms:.0f} ms; size {size / 1024 / 1024:.1f} MiB")


def check_migrations(db: Session) -> Result:
    head = _alembic_head()
    if head is None:
        return Result("migrations", "warn", "migration scripts not found next to the application")
    current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if current == head:
        return Result("migrations", "ok", f"database schema is at {head}")
    return Result("migrations", "crit", f"database schema {current} does not match code {head}")


def check_audit_chain(db: Session) -> Result:
    result = audit.verify_chain(db, tail=500)
    if result.ok:
        return Result("audit.chain", "ok", f"last {result.checked} entries verified")
    return Result("audit.chain", "crit", f"TAMPERING SUSPECTED at entry {result.first_bad_id}: {result.reason}")


def run_backend_checks(db: Session) -> list[Result]:
    return [check_database(db), check_migrations(db), check_audit_chain(db)]


def store(db: Session, source: str, results: list[Result]) -> None:
    now = datetime.now(UTC)
    for r in results:
        stmt = insert(SelfmonCheck).values(name=r.name, source=source, status=r.status, detail=r.detail, checked_at=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=["name"],
            set_={"source": stmt.excluded.source, "status": stmt.excluded.status,
                  "detail": stmt.excluded.detail, "checked_at": stmt.excluded.checked_at},
        )
        db.execute(stmt)


def load(db: Session) -> list[CheckOut]:
    now = datetime.now(UTC)
    out: list[CheckOut] = []
    rows = db.execute(select(SelfmonCheck).order_by(SelfmonCheck.name)).scalars().all()
    for r in rows:
        stale = (r.source == "worker" and now - r.checked_at > WORKER_STALE) or (
            r.source == "watchdog" and now - r.checked_at > WATCHDOG_STALE) or (
            r.source == "backend" and now - r.checked_at > WORKER_STALE)
        status, detail = r.status, r.detail
        if stale:
            status = "crit" if r.source in {"worker", "backend"} else "warn"
            detail = f"no update since {r.checked_at.isoformat(timespec='seconds')} - {detail}"
        out.append(CheckOut(name=r.name, source=r.source, status=status, detail=detail,
                            checked_at=r.checked_at, stale=stale))
    if not any(c.source == "watchdog" for c in out):
        out.append(CheckOut(name="watchdog", source="watchdog", status="warn", checked_at=None, stale=True,
                            detail="no report from the host watchdog yet (is the obs-core-watchdog timer enabled?)"))
    if not any(c.source == "worker" for c in out):
        out.append(CheckOut(name="worker.heartbeat", source="worker", status="crit", checked_at=None, stale=True,
                            detail="the background worker has not reported"))
    return out


def overall(checks: list[CheckOut]) -> str:
    worst = max((_SEVERITY[c.status] for c in checks), default=0)
    return {0: "ok", 1: "warn", 2: "crit"}[worst]
