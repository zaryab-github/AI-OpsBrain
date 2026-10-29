"""Append-only, HMAC hash-chained audit log.

Every row stores the hash of the previous row, and its own hash is
HMAC-SHA256(key, prev_hash | canonical_json(row)). Editing or deleting a row therefore
breaks the chain from that point on, which ``verify_chain`` reports. The database also
rejects UPDATE/DELETE/TRUNCATE on the table (see the migration).

Success entries are written in the SAME transaction as the change they describe, so the
log can never claim something happened that was rolled back. Failure and denied entries
use ``record_independent`` (their own transaction) because the surrounding transaction
is being abandoned.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import session_factory
from app.models import AuditLog, User

GENESIS = "0" * 64
_LOCK_KEY = 7357001  # arbitrary constant for pg_advisory_xact_lock
_SENSITIVE = ("password", "token", "secret", "hash", "recovery", "mfa_secret", "key")


@dataclass(frozen=True)
class RequestContext:
    ip: str | None = None
    user_agent: str | None = None


def redact(value: Any) -> Any:
    """Never let credentials into the log, whatever the caller passes."""
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if any(s in k.lower() for s in _SENSITIVE) and v else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="microseconds")


def _row_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "ts": _iso(row["ts"]),
        "actor_id": str(row["actor_id"]) if row["actor_id"] else None,
        "actor_name": row["actor_name"],
        "action": row["action"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "resource_name": row["resource_name"],
        "host_id": row["host_id"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
        "result": row["result"],
        "detail": row["detail"],
        "ip": row["ip"],
        "user_agent": row["user_agent"],
    }


def compute_hash(prev_hash: str, row: dict[str, Any]) -> str:
    message = f"{prev_hash}|{_canonical(_row_payload(row))}".encode()
    return hmac.new(get_config().audit_hmac_key, message, hashlib.sha256).hexdigest()


def record(
    db: Session,
    *,
    action: str,
    result: str = "success",
    actor: User | None = None,
    actor_name: str | None = None,
    ctx: RequestContext | None = None,
    resource_type: str | None = None,
    resource_id: object | None = None,
    resource_name: str | None = None,
    host_id: str | None = None,
    old: Any = None,
    new: Any = None,
    detail: str | None = None,
) -> AuditLog:
    """Add one audit row to the caller's transaction. The caller commits."""
    if result not in {"success", "failure", "denied"}:
        raise ValueError(f"invalid audit result: {result}")
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    prev = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar() or GENESIS
    next_id = db.execute(text("SELECT nextval(pg_get_serial_sequence('audit_log', 'id'))")).scalar_one()
    ctx = ctx or RequestContext()
    row = {
        "id": int(next_id),
        "ts": datetime.now(UTC),
        "actor_id": actor.id if actor else None,
        "actor_name": (actor.username if actor else actor_name) or "anonymous",
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id is not None else None,
        "resource_name": resource_name,
        "host_id": host_id,
        "old_value": _jsonable(redact(old)),
        "new_value": _jsonable(redact(new)),
        "result": result,
        "detail": detail,
        "ip": ctx.ip,
        "user_agent": (ctx.user_agent or "")[:255] or None,
    }
    entry = AuditLog(**row, prev_hash=prev, hash=compute_hash(prev, row))
    db.add(entry)
    db.flush()
    return entry


def record_independent(**kwargs: Any) -> None:
    """Write an audit row in its own transaction (failure / denied paths)."""
    with session_factory()() as session:
        record(session, **kwargs)
        session.commit()


@dataclass(frozen=True)
class ChainResult:
    ok: bool
    checked: int
    first_bad_id: int | None = None
    reason: str | None = None


def verify_chain(db: Session, tail: int | None = None) -> ChainResult:
    """Recompute every hash. With ``tail`` only the newest N rows are checked (cheap)."""
    stmt = select(AuditLog).order_by(AuditLog.id)
    expected_prev: str | None = GENESIS
    if tail is not None:
        newest = db.execute(select(AuditLog.id).order_by(AuditLog.id.desc()).limit(tail)).scalars().all()
        if not newest:
            return ChainResult(True, 0)
        stmt = stmt.where(AuditLog.id >= newest[-1])
        expected_prev = None  # trust the stored link of the first row we look at
    checked = 0
    offset = 0
    batch = 1000
    while True:
        rows = db.execute(stmt.limit(batch).offset(offset)).scalars().all()
        if not rows:
            break
        for r in rows:
            if expected_prev is not None and r.prev_hash != expected_prev:
                return ChainResult(False, checked, r.id, "link to the previous entry is broken")
            as_dict = {
                "id": r.id, "ts": r.ts, "actor_id": r.actor_id, "actor_name": r.actor_name,
                "action": r.action, "resource_type": r.resource_type, "resource_id": r.resource_id,
                "resource_name": r.resource_name, "host_id": r.host_id, "old_value": r.old_value,
                "new_value": r.new_value, "result": r.result, "detail": r.detail, "ip": r.ip,
                "user_agent": r.user_agent,
            }
            if not hmac.compare_digest(compute_hash(r.prev_hash, as_dict), r.hash):
                return ChainResult(False, checked, r.id, "entry content does not match its hash")
            expected_prev = r.hash
            checked += 1
        offset += batch
    return ChainResult(True, checked)
