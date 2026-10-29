"""Typed, validated system settings stored in the database and changed through the API.

Only keys declared here can be stored. Values are validated against their definition, and
every change is written to the audit log with the old and new value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.errors import ApiError
from app.models import SystemSetting, User


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: str  # "int" | "bool" | "str"
    default: Any
    description: str
    group: str
    minimum: int | None = None
    maximum: int | None = None
    max_length: int | None = None
    https_url: bool = False


DEFINITIONS: tuple[SettingDef, ...] = (
    SettingDef("general.instance_name", "str", "AI Observability Platform",
               "Name shown on the login page and in the header", "General", max_length=64),
    SettingDef("security.require_mfa", "bool", False,
               "Require every user to enrol a TOTP authenticator before using the platform", "Security"),
    SettingDef("security.access_token_minutes", "int", 15,
               "Lifetime of an access token in minutes (the browser refreshes it silently)", "Security",
               minimum=5, maximum=60),
    SettingDef("security.session_days", "int", 7,
               "Days a login session stays valid without signing in again", "Security", minimum=1, maximum=30),
    SettingDef("security.password_min_length", "int", 12,
               "Minimum password length", "Security", minimum=12, maximum=128),
    SettingDef("security.lockout_threshold", "int", 5,
               "Failed sign-ins before an account is temporarily locked", "Security", minimum=3, maximum=20),
    SettingDef("security.lockout_minutes", "int", 15,
               "How long a locked account stays locked", "Security", minimum=1, maximum=1440),
    SettingDef("selfmon.heartbeat_url", "str", "",
               "HTTPS URL pinged while the platform is healthy (dead-man's switch for an external monitor). Empty disables it.",
               "Self-monitoring", max_length=512, https_url=True),
    SettingDef("selfmon.heartbeat_interval_seconds", "int", 60,
               "Seconds between heartbeat pings", "Self-monitoring", minimum=30, maximum=3600),
)

_BY_KEY = {d.key: d for d in DEFINITIONS}


def definition(key: str) -> SettingDef:
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise ApiError(422, "unknown_setting", f"Unknown setting: {key}") from exc


def validate(d: SettingDef, value: Any) -> Any:
    if d.type == "bool":
        if not isinstance(value, bool):
            raise ApiError(422, "invalid_setting", f"{d.key} must be true or false")
        return value
    if d.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError(422, "invalid_setting", f"{d.key} must be a whole number")
        if d.minimum is not None and value < d.minimum:
            raise ApiError(422, "invalid_setting", f"{d.key} must be at least {d.minimum}")
        if d.maximum is not None and value > d.maximum:
            raise ApiError(422, "invalid_setting", f"{d.key} must be at most {d.maximum}")
        return value
    if not isinstance(value, str):
        raise ApiError(422, "invalid_setting", f"{d.key} must be text")
    value = value.strip()
    if d.max_length is not None and len(value) > d.max_length:
        raise ApiError(422, "invalid_setting", f"{d.key} must be at most {d.max_length} characters")
    if d.https_url and value and not value.startswith("https://"):
        raise ApiError(422, "invalid_setting", f"{d.key} must start with https://")
    if d.key == "general.instance_name" and not value:
        raise ApiError(422, "invalid_setting", "The instance name must not be empty")
    return value


def get_all(db: Session) -> dict[str, Any]:
    stored = {row.key: row.value.get("v") for row in db.execute(select(SystemSetting)).scalars()}
    return {d.key: stored.get(d.key, d.default) for d in DEFINITIONS}


def get(db: Session, key: str) -> Any:
    d = definition(key)
    row = db.get(SystemSetting, key)
    return row.value.get("v") if row else d.default


def update(db: Session, changes: dict[str, Any], actor: User, ctx: audit.RequestContext) -> dict[str, Any]:
    """Validate everything first, then apply and audit each change. Caller commits."""
    validated = {k: validate(definition(k), v) for k, v in changes.items()}
    current = get_all(db)
    for key, new_value in validated.items():
        old_value = current[key]
        if old_value == new_value:
            continue
        row = db.get(SystemSetting, key)
        if row is None:
            db.add(SystemSetting(key=key, value={"v": new_value}, updated_by=actor.username))
        else:
            row.value = {"v": new_value}
            row.updated_by = actor.username
        audit.record(
            db, action="setting.update", actor=actor, ctx=ctx,
            resource_type="setting", resource_id=key, resource_name=key,
            old={"value": old_value}, new={"value": new_value},
        )
    db.flush()
    return get_all(db)
