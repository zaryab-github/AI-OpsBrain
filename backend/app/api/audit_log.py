import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import actor_for, require
from app.api.schemas import AuditOut, AuditPage
from app.db import get_db, sessionmaker
from app.models import AuditLog, User
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditFilters(BaseModel):
    actor: str | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    host_id: str | None = None
    result: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    q: str | None = None


def _filtered(f: AuditFilters) -> Select[tuple[AuditLog]]:
    q = select(AuditLog)
    if f.actor:
        q = q.where(AuditLog.actor_name.ilike(f"%{f.actor}%"))
    if f.action:
        q = q.where(AuditLog.action.like(f"{f.action}%"))
    if f.resource_type:
        q = q.where(AuditLog.resource_type == f.resource_type)
    if f.resource_id:
        q = q.where(AuditLog.resource_id == f.resource_id)
    if f.host_id:
        q = q.where(AuditLog.host_id == f.host_id)
    if f.result:
        q = q.where(AuditLog.result == f.result)
    if f.since:
        q = q.where(AuditLog.ts >= f.since)
    if f.until:
        q = q.where(AuditLog.ts < f.until)
    if f.q:
        q = q.where(or_(AuditLog.detail.ilike(f"%{f.q}%"), AuditLog.resource_id.ilike(f"%{f.q}%"),
                        AuditLog.action.ilike(f"%{f.q}%")))
    return q


@router.get("", response_model=AuditPage)
async def list_audit(f: AuditFilters = Depends(), before_id: int | None = None,
                     limit: int = Query(100, ge=1, le=500),
                     _: User = Depends(require("audit.view")),
                     db: AsyncSession = Depends(get_db)) -> AuditPage:
    q = _filtered(f)
    if before_id is not None:
        q = q.where(AuditLog.id < before_id)
    rows = (await db.execute(q.order_by(AuditLog.id.desc()).limit(limit + 1))).scalars().all()
    items = [AuditOut.model_validate(r) for r in rows[:limit]]
    return AuditPage(items=items, next_before_id=items[-1].id if len(rows) > limit else None)


class ChainOut(BaseModel):
    ok: bool
    checked: int
    first_bad_id: int | None
    message: str
    verified_at: datetime


@router.post("/verify", response_model=ChainOut)
async def verify(request: Request, me: User = Depends(require("audit.view")),
                 db: AsyncSession = Depends(get_db)) -> ChainOut:
    report = await audit.verify_chain(db)
    await audit.record(db, actor=actor_for(me, request), action="audit.verify", resource_type="audit_log",
                       result="success" if report.ok else "failure", detail=report.message)
    return ChainOut(**report.__dict__)


@router.get("/export.csv")
async def export_csv(request: Request, f: AuditFilters = Depends(),
                     me: User = Depends(require("audit.view")),
                     db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    await audit.record(db, actor=actor_for(me, request), action="audit.export", resource_type="audit_log",
                       detail=f"filters: {f.model_dump_json(exclude_none=True)}")
    await db.commit()
    query = _filtered(f).order_by(AuditLog.id)

    async def rows() -> AsyncIterator[str]:
        cols = ["id", "ts", "actor_name", "actor_ip", "action", "resource_type", "resource_id", "host_id",
                "result", "detail", "old_value", "new_value", "prev_hash", "hash"]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        yield buf.getvalue()
        async with sessionmaker()() as s:
            result = await s.stream_scalars(query.execution_options(yield_per=1000))
            async for r in result:
                buf.seek(0)
                buf.truncate()
                writer.writerow([r.id, r.ts.isoformat(), r.actor_name, r.actor_ip or "", r.action,
                                 r.resource_type, r.resource_id or "", r.host_id or "", r.result, r.detail,
                                 json.dumps(r.old_value) if r.old_value is not None else "",
                                 json.dumps(r.new_value) if r.new_value is not None else "",
                                 r.prev_hash, r.hash])
                yield buf.getvalue()

    return StreamingResponse(rows(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'})
