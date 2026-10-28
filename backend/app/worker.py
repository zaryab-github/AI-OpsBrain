"""Background worker and scheduler (Celery). Later phases add alert, AI, report and archive tasks here."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TypeVar

from celery import Celery
from sqlalchemy import delete, or_

from app import db as db_module
from app.config import get_settings
from app.logging_setup import configure
from app.models import Session
from app.models.base import utcnow
from app.redis_client import close_redis, get_redis
from app.services import audit
from app.services.platform import AUDIT_VERIFY_KEY, WORKER_HEARTBEAT_KEY

T = TypeVar("T")

_cfg = get_settings()
configure(_cfg.log_level)

celery_app = Celery("opsbrain", broker=_cfg.redis_url.get_secret_value())
celery_app.conf.update(
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    timezone="UTC",
    beat_schedule={
        "heartbeat": {"task": "opsbrain.heartbeat", "schedule": 30.0},
        "session-cleanup": {"task": "opsbrain.session_cleanup", "schedule": 3600.0},
        "audit-verify": {"task": "opsbrain.audit_verify", "schedule": 3600.0},
    },
)


def run(coro_fn: Callable[[], Awaitable[T]]) -> T:
    """Run an async job on a fresh loop, with engine/redis clients bound to that loop."""

    async def wrapper() -> T:
        try:
            return await coro_fn()
        finally:
            await db_module.dispose_engine()
            await close_redis()

    return asyncio.run(wrapper())


@celery_app.task(name="opsbrain.heartbeat")
def heartbeat() -> None:
    async def job() -> None:
        await get_redis().set(WORKER_HEARTBEAT_KEY, str(time.time()), ex=600)

    run(job)


@celery_app.task(name="opsbrain.session_cleanup")
def session_cleanup() -> int:
    async def job() -> int:
        cutoff = utcnow() - timedelta(days=1)
        async with db_module.sessionmaker()() as s:
            res = await s.execute(delete(Session).where(or_(Session.expires_at < utcnow(),
                                                            Session.revoked_at < cutoff)))
            await s.commit()
            return res.rowcount or 0

    return run(job)


@celery_app.task(name="opsbrain.audit_verify")
def audit_verify() -> bool:
    async def job() -> bool:
        async with db_module.sessionmaker()() as s:
            report = await audit.verify_chain(s)
            if not report.ok:
                await audit.record(s, actor=audit.Actor.system("audit-verifier"), action="audit.verify",
                                   resource_type="audit_log", result="failure", detail=report.message)
                await s.commit()
        await get_redis().set(AUDIT_VERIFY_KEY, json.dumps({
            "ok": report.ok, "checked": report.checked, "first_bad_id": report.first_bad_id,
            "message": report.message, "verified_at": report.verified_at.isoformat(),
        }))
        return report.ok

    return run(job)
