"""Health, public branding info and platform status."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import selfmon
from app import settings_registry as cfg
from app.config import get_config
from app.db import get_db
from app.deps import CurrentUser, require
from app.schemas import StatusOut

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> JSONResponse:
    """Unauthenticated liveness + database reachability. Reveals nothing else."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


@router.get("/public")
def public(db: Session = Depends(get_db)) -> dict:
    """What the login page may show before sign-in."""
    return {"instance_name": cfg.get(db, "general.instance_name")}


@router.get("/status", response_model=StatusOut)
def status(_: CurrentUser = Depends(require("system.view")), db: Session = Depends(get_db)) -> StatusOut:
    checks = selfmon.load(db)
    return StatusOut(overall=selfmon.overall(checks), version=get_config().version, checks=checks)
