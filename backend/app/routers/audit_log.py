"""Read-only access to the audit log: search, CSV export and chain verification."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import CurrentUser, request_ctx, require
from app.models import AuditLog
from app.schemas import AuditOut, AuditPage, ChainOut

router = APIRouter(prefix="/audit", tags=["audit"])

EXPORT_LIMIT = 100_000


def _filtered(
    stmt: Select, actor: str | None, action: str | None, resource_type: str | None, result: str | None,
    q: str | None, since: datetime | None, until: datetime | None,
) -> Select:
    if actor:
        stmt = stmt.where(AuditLog.actor_name == actor)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if result:
        stmt = stmt.where(AuditLog.result == result)
    if since:
        stmt = stmt.where(AuditLog.ts >= since)
    if until:
        stmt = stmt.where(AuditLog.ts <= until)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuditLog.action.ilike(like), AuditLog.resource_name.ilike(like),
                              AuditLog.detail.ilike(like), AuditLog.actor_name.ilike(like)))
    return stmt


@router.get("", response_model=AuditPage)
def list_audit(
    before_id: int | None = None, limit: int = Query(50, ge=1, le=200),
    actor: str | None = None, action: str | None = None, resource_type: str | None = None,
    result: str | None = Query(None, pattern="^(success|failure|denied)$"), q: str | None = Query(None, max_length=100),
    since: datetime | None = None, until: datetime | None = None,
    _: CurrentUser = Depends(require("audit.view")), db: Session = Depends(get_db),
) -> AuditPage:
    stmt = _filtered(select(AuditLog), actor, action, resource_type, result, q, since, until)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).limit(limit + 1)).scalars().all()
    items = rows[:limit]
    return AuditPage(items=[AuditOut.model_validate(r) for r in items],
                     next_before_id=items[-1].id if len(rows) > limit else None)


@router.get("/export.csv")
def export_csv(
    request: Request, actor: str | None = None, action: str | None = None, resource_type: str | None = None,
    result: str | None = Query(None, pattern="^(success|failure|denied)$"), q: str | None = Query(None, max_length=100),
    since: datetime | None = None, until: datetime | None = None,
    current: CurrentUser = Depends(require("audit.view")), db: Session = Depends(get_db),
) -> StreamingResponse:
    stmt = _filtered(select(AuditLog), actor, action, resource_type, result, q, since, until)
    stmt = stmt.order_by(AuditLog.id.desc()).limit(EXPORT_LIMIT)
    rows = db.execute(stmt).scalars().all()
    audit.record(db, action="audit.export", actor=current.user, ctx=request_ctx(request),
                 resource_type="audit_log", detail=f"{len(rows)} rows exported")
    db.commit()

    def generate() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "time_utc", "actor", "action", "result", "resource_type", "resource_id",
                         "resource_name", "host_id", "old_value", "new_value", "detail", "ip"])
        yield buf.getvalue()
        for r in rows:
            buf.seek(0)
            buf.truncate()
            writer.writerow([r.id, r.ts.isoformat(), r.actor_name, _csv_safe(r.action), r.result, r.resource_type,
                             r.resource_id, _csv_safe(r.resource_name), r.host_id,
                             _csv_safe(r.old_value), _csv_safe(r.new_value), _csv_safe(r.detail), r.ip])
            yield buf.getvalue()

    return StreamingResponse(generate(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'})


def _csv_safe(value: object) -> str:
    """Neutralise spreadsheet formula injection in exported text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text


@router.get("/verify", response_model=ChainOut)
def verify(request: Request, current: CurrentUser = Depends(require("audit.view")), db: Session = Depends(get_db)) -> ChainOut:
    result = audit.verify_chain(db)
    audit.record(db, action="audit.verify", actor=current.user, ctx=request_ctx(request),
                 result="success" if result.ok else "failure",
                 detail=f"checked {result.checked} entries" + ("" if result.ok else f"; first bad entry {result.first_bad_id}: {result.reason}"))
    db.commit()
    return ChainOut(ok=result.ok, checked=result.checked, first_bad_id=result.first_bad_id, reason=result.reason)
