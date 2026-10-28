"""Audit trail writer and verifier (PDF §12: who, what, when, which resource/host, old, new, result)."""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import sessionmaker
from app.models import AuditLog
from app.models.base import utcnow

log = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64
# Arbitrary constant: serialises audit inserts so the hash chain stays linear under concurrency.
_CHAIN_LOCK_KEY = 0x0B5A0D17

_SENSITIVE_KEYS = {"password", "password_hash", "mfa_secret_enc", "mfa_pending_secret_enc", "secret",
                   "token", "token_hash", "api_key", "csrf_token"}


@dataclass(frozen=True)
class Actor:
    id: uuid.UUID | None
    name: str
    ip: str | None = None

    @classmethod
    def system(cls, name: str = "system") -> "Actor":
        return cls(id=None, name=name, ip=None)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in _SENSITIVE_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _json_safe(value: Any) -> Any:
    # Normalise to what JSONB will hand back (UUIDs/datetimes become strings) so the hash re-verifies.
    return json.loads(json.dumps(value, default=str))


def _canonical(row: dict[str, Any]) -> bytes:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode()


def compute_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256(prev_hash.encode() + _canonical(fields)).hexdigest()


def _hashed_fields(entry: AuditLog) -> dict[str, Any]:
    return {
        "ts": entry.ts.isoformat(),
        "actor_id": str(entry.actor_id) if entry.actor_id else None,
        "actor_name": entry.actor_name,
        "actor_ip": str(entry.actor_ip) if entry.actor_ip else None,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "host_id": entry.host_id,
        "old_value": entry.old_value,
        "new_value": entry.new_value,
        "result": entry.result,
        "detail": entry.detail,
    }


async def record(
    db: AsyncSession,
    *,
    actor: Actor,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    host_id: str | None = None,
    old: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
    result: str = "success",
    detail: str = "",
) -> AuditLog:
    """Append an audit entry inside the caller's transaction, so the entry and the change commit together."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    prev = (await db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))).scalar()
    entry = AuditLog(
        ts=utcnow(),
        actor_id=actor.id,
        actor_name=actor.name,
        actor_ip=actor.ip,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        host_id=host_id,
        old_value=_json_safe(redact(old)) if old is not None else None,
        new_value=_json_safe(redact(new)) if new is not None else None,
        result=result,
        detail=detail,
        prev_hash=prev or GENESIS_HASH,
    )
    entry.hash = compute_hash(entry.prev_hash, _hashed_fields(entry))
    db.add(entry)
    await db.flush()
    return entry


async def record_standalone(**kwargs: Any) -> None:
    """Write an audit entry in its own transaction — for failures and denials whose request rolls back."""
    try:
        async with sessionmaker()() as db:
            await record(db, **kwargs)
            await db.commit()
    except Exception:  # never let audit-of-a-failure mask the original error
        log.exception("failed to write standalone audit entry")


@dataclass
class ChainReport:
    ok: bool
    checked: int
    first_bad_id: int | None
    message: str
    verified_at: datetime


async def verify_chain(db: AsyncSession, batch: int = 5000) -> ChainReport:
    prev = GENESIS_HASH
    checked = 0
    last_id = 0
    while True:
        rows = (
            await db.execute(select(AuditLog).where(AuditLog.id > last_id).order_by(AuditLog.id).limit(batch))
        ).scalars().all()
        if not rows:
            break
        for row in rows:
            if row.prev_hash != prev:
                return ChainReport(False, checked, row.id, f"Entry {row.id} does not follow entry before it "
                                   "(an entry was removed or reordered).", utcnow())
            if compute_hash(row.prev_hash, _hashed_fields(row)) != row.hash:
                return ChainReport(False, checked, row.id, f"Entry {row.id} content does not match its hash "
                                   "(it was modified).", utcnow())
            prev = row.hash
            checked += 1
            last_id = row.id
    return ChainReport(True, checked, None, f"All {checked} entries verified.", utcnow())
