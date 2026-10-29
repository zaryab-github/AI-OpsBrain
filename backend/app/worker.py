"""Background worker: self-monitoring, heartbeat, housekeeping.

Run as ``python -m app.worker``. ``--healthcheck`` exits 0 when the worker's own heartbeat
in the database is fresh (used by the container health check).
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select

from app import selfmon
from app import settings_registry as cfg
from app.db import session_factory
from app.logging_setup import configure_logging
from app.models import AuthSession, SelfmonCheck

log = logging.getLogger("obs.worker")
_stop = threading.Event()


def task_selfmon() -> None:
    with session_factory()() as db:
        results = selfmon.run_backend_checks(db)
        selfmon.store(db, "backend", results)
        selfmon.store(db, "worker", [selfmon.Result("worker.heartbeat", "ok", "worker loop is running")])
        db.commit()


def task_heartbeat() -> None:
    """Ping the external dead-man's-switch URL, but only while the platform is healthy."""
    with session_factory()() as db:
        url = str(cfg.get(db, "selfmon.heartbeat_url"))
        if not url:
            return
        checks = selfmon.load(db)
    if selfmon.overall([c for c in checks if c.source != "watchdog"]) == "crit":
        log.warning("not sending heartbeat: platform checks are critical")
        return
    try:
        httpx.get(url, timeout=10, follow_redirects=False).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("heartbeat failed: %s", type(exc).__name__)


def task_cleanup() -> None:
    """Remove refresh-token rows that expired or were revoked more than 30 days ago."""
    cutoff = datetime.now(UTC) - timedelta(days=30)
    with session_factory()() as db:
        removed = db.execute(
            delete(AuthSession).where(
                (AuthSession.expires_at < cutoff) | (AuthSession.revoked_at < cutoff)
            )
        ).rowcount
        db.commit()
    if removed:
        log.info("removed %d expired session rows", removed)


def _heartbeat_interval() -> int:
    with session_factory()() as db:
        return int(cfg.get(db, "selfmon.heartbeat_interval_seconds"))


def run() -> None:
    configure_logging()
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    log.info("worker started")
    schedule = {"selfmon": 0.0, "heartbeat": 0.0, "cleanup": 0.0}
    while not _stop.is_set():
        now = time.monotonic()
        for name, fn, every in (
            ("selfmon", task_selfmon, 30),
            ("heartbeat", task_heartbeat, None),
            ("cleanup", task_cleanup, 3600),
        ):
            if now < schedule[name]:
                continue
            try:
                fn()
            except Exception:  # noqa: BLE001 - one failing task must not stop the loop
                log.exception("task %s failed", name)
            interval = every if every is not None else _safe_interval()
            schedule[name] = time.monotonic() + interval
        _stop.wait(5)
    log.info("worker stopped")


def _safe_interval() -> int:
    try:
        return _heartbeat_interval()
    except Exception:  # noqa: BLE001
        return 60


def healthcheck() -> int:
    try:
        with session_factory()() as db:
            row = db.execute(select(SelfmonCheck).where(SelfmonCheck.name == "worker.heartbeat")).scalar_one_or_none()
        if row and datetime.now(UTC) - row.checked_at < selfmon.WORKER_STALE:
            return 0
    except Exception:  # noqa: BLE001
        pass
    return 1


if __name__ == "__main__":
    sys.exit(healthcheck() if "--healthcheck" in sys.argv else (run() or 0))
