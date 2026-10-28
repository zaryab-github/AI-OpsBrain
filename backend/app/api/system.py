from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.deps import current_user, require
from app.db import get_db
from app.models import User
from app.redis_client import get_redis
from app.services import platform

router = APIRouter(prefix="/system", tags=["system"])
health_router = APIRouter(tags=["health"])


@health_router.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/health/ready", include_in_schema=False)
async def ready(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    problems = []
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        problems.append("database")
    try:
        await get_redis().ping()
    except Exception:
        problems.append("redis")
    if problems:
        return JSONResponse({"status": "unavailable", "failing": problems}, status_code=503)
    return JSONResponse({"status": "ok"})


@router.get("/modules")
async def modules(_: User = Depends(current_user)) -> dict[str, Any]:
    installed = platform.installed_modules()
    return {
        "version": __version__,
        "modules": [
            {"key": key, **meta, "installed": key in installed, "info": installed.get(key)}
            for key, meta in platform.MODULES.items()
        ],
    }


@router.get("/health")
async def system_health(_: User = Depends(require("settings.view")),
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    checks = await platform.health(db)
    order = {"ok": 0, "unknown": 1, "warning": 2, "critical": 3}
    overall = max((c["status"] for c in checks), key=lambda s: order[s])
    return {"overall": overall, "checks": checks}
