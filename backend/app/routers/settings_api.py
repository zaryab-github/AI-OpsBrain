"""System settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import settings_registry as reg
from app.db import get_db
from app.deps import CurrentUser, request_ctx, require
from app.schemas import SettingOut, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def _render(db: Session) -> list[SettingOut]:
    values = reg.get_all(db)
    return [
        SettingOut(key=d.key, group=d.group, description=d.description, type=d.type, value=values[d.key],
                   default=d.default, minimum=d.minimum, maximum=d.maximum)
        for d in reg.DEFINITIONS
    ]


@router.get("", response_model=list[SettingOut])
def list_settings(_: CurrentUser = Depends(require("settings.view")), db: Session = Depends(get_db)) -> list[SettingOut]:
    return _render(db)


@router.patch("", response_model=list[SettingOut])
def update_settings(
    body: SettingsUpdate, request: Request, current: CurrentUser = Depends(require("settings.manage")),
    db: Session = Depends(get_db),
) -> list[SettingOut]:
    reg.update(db, body.changes, current.user, request_ctx(request))
    db.commit()
    return _render(db)
