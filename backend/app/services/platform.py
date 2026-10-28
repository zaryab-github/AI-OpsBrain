"""Installed modules and the platform's own health (self-monitoring of the core module)."""

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography import x509
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.redis_client import get_redis

log = logging.getLogger(__name__)

WORKER_HEARTBEAT_KEY = "opsbrain:worker:heartbeat"
AUDIT_VERIFY_KEY = "opsbrain:audit:last_verify"

MODULES: dict[str, dict[str, str]] = {
    "core": {"name": "Core platform", "description": "Web UI, API, users, RBAC, audit log, hosts and agents."},
    "logging": {"name": "Logging", "description": "Log collection, storage, search, live tail and log alerts."},
    "monitoring": {"name": "Monitoring", "description": "Metric collection, storage, dashboards and thresholds."},
    "ai": {"name": "AI / AIOps", "description": "AI analysis, anomaly detection, root cause and recommendations."},
    "automation": {"name": "Automation", "description": "n8n workflows and approved remediation actions."},
    "archive": {"name": "Retention & Archive", "description": "Object storage archive and restore."},
}


def installed_modules() -> dict[str, dict[str, Any]]:
    path = get_settings().modules_file
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.exception("cannot read modules file %s", path)
        return {}
    return {k: v for k, v in data.get("modules", {}).items() if k in MODULES}


@dataclass
class Check:
    component: str
    status: str  # ok | warning | critical | unknown
    message: str
    detail: dict[str, Any] | None = None


async def _db(db: AsyncSession) -> Check:
    try:
        t0 = time.perf_counter()
        await db.execute(text("SELECT 1"))
        version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return Check("database", "ok", f"PostgreSQL reachable ({ms} ms), schema {version}")
    except Exception as exc:
        return Check("database", "critical", f"PostgreSQL error: {exc.__class__.__name__}")


async def _redis() -> Check:
    try:
        await get_redis().ping()
        return Check("redis", "ok", "Valkey reachable")
    except Exception as exc:
        return Check("redis", "critical", f"Valkey error: {exc.__class__.__name__}")


async def _worker() -> Check:
    try:
        raw = await get_redis().get(WORKER_HEARTBEAT_KEY)
    except Exception:
        return Check("worker", "unknown", "Cannot read worker heartbeat (Valkey unavailable)")
    if raw is None:
        return Check("worker", "critical", "No heartbeat from the background worker")
    age = time.time() - float(raw)
    if age > 180:
        return Check("worker", "critical", f"Last worker heartbeat {int(age)} s ago")
    return Check("worker", "ok", f"Worker heartbeat {int(age)} s ago")


async def _audit_chain() -> Check:
    try:
        raw = await get_redis().get(AUDIT_VERIFY_KEY)
    except Exception:
        return Check("audit_chain", "unknown", "Cannot read last verification (Valkey unavailable)")
    if raw is None:
        return Check("audit_chain", "unknown", "Audit chain not verified yet (runs hourly)")
    report = json.loads(raw)
    return Check("audit_chain", "ok" if report["ok"] else "critical", report["message"],
                 {"verified_at": report["verified_at"]})


def _backup() -> Check:
    path = get_settings().backup_status_file
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return Check("backup", "warning", "No backup has run yet. Run: sudo opsbrainctl backup")
    except (OSError, ValueError):
        return Check("backup", "unknown", f"Cannot read {path}")
    last_ok = data.get("last_success")
    if data.get("last_result") != "success":
        return Check("backup", "critical", f"Last backup failed: {data.get('last_error', 'unknown error')}", data)
    if not last_ok:
        return Check("backup", "warning", "No successful backup recorded", data)
    age_h = (datetime.now(UTC) - datetime.fromisoformat(last_ok)).total_seconds() / 3600
    status = "ok" if age_h <= 26 else "warning" if age_h <= 72 else "critical"
    return Check("backup", status, f"Last successful backup {age_h:.1f} h ago", data)


def _tls() -> Check:
    path = get_settings().tls_cert_file
    try:
        cert = x509.load_pem_x509_certificate(path.read_bytes())
    except FileNotFoundError:
        return Check("tls", "unknown", f"Certificate not mounted at {path}")
    except (OSError, ValueError):
        return Check("tls", "critical", f"Cannot parse certificate {path}")
    days = (cert.not_valid_after_utc - datetime.now(UTC)).days
    status = "ok" if days > 30 else "warning" if days > 7 else "critical"
    return Check("tls", status, f"Server certificate expires in {days} days",
                 {"not_after": cert.not_valid_after_utc.isoformat(), "subject": cert.subject.rfc4514_string()})


async def health(db: AsyncSession) -> list[dict[str, Any]]:
    checks = [Check("api", "ok", "API responding"), await _db(db), await _redis(), await _worker(),
              await _audit_chain(), _backup(), _tls()]
    return [asdict(c) for c in checks]
