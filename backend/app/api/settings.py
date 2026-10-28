from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import actor_for, current_user, require
from app.db import get_db
from app.models import Setting, User
from app.services import audit
from app.services import settings as settings_svc

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingOut(BaseModel):
    key: str
    group: str
    label: str
    description: str
    type: str
    value: Any
    default: Any
    minimum: int | None
    maximum: int | None
    choices: list[str]


class SettingIn(BaseModel):
    value: Any


@router.get("/public")
async def public_settings(_: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Non-sensitive values every signed-in user's UI needs."""
    return {"platform_name": await settings_svc.get(db, "general.platform_name")}


@router.get("", response_model=list[SettingOut])
async def list_settings(_: User = Depends(require("settings.view")),
                        db: AsyncSession = Depends(get_db)) -> list[SettingOut]:
    values = await settings_svc.get_all(db)
    return [SettingOut(key=d.key, group=d.group, label=d.label, description=d.description, type=d.type,
                       value=values[d.key], default=d.default, minimum=d.minimum, maximum=d.maximum,
                       choices=list(d.choices)) for d in settings_svc.DEFINITIONS.values()]


@router.put("/{key}", response_model=SettingOut)
async def update_setting(key: str, body: SettingIn, request: Request,
                         me: User = Depends(require("settings.manage")),
                         db: AsyncSession = Depends(get_db)) -> SettingOut:
    definition = settings_svc.DEFINITIONS.get(key)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown setting")
    try:
        value = definition.validate(body.value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    old = await settings_svc.get(db, key)
    row = await db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value, updated_by=me.id))
    else:
        row.value = value
        row.updated_by = me.id
    await audit.record(db, actor=actor_for(me, request), action="setting.update", resource_type="setting",
                       resource_id=key, old={"value": old}, new={"value": value})
    d = definition
    return SettingOut(key=d.key, group=d.group, label=d.label, description=d.description, type=d.type,
                      value=value, default=d.default, minimum=d.minimum, maximum=d.maximum,
                      choices=list(d.choices))
