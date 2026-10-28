"""Runtime-adjustable system settings with typed, validated definitions."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting


@dataclass(frozen=True)
class SettingDef:
    key: str
    group: str
    label: str
    description: str
    type: str  # int | bool | str | enum
    default: Any
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = field(default_factory=tuple)

    def validate(self, value: Any) -> Any:
        if self.type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{self.label} must be a whole number")
            if self.minimum is not None and value < self.minimum:
                raise ValueError(f"{self.label} must be at least {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise ValueError(f"{self.label} must be at most {self.maximum}")
        elif self.type == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{self.label} must be true or false")
        elif self.type == "enum":
            if value not in self.choices:
                raise ValueError(f"{self.label} must be one of: {', '.join(self.choices)}")
        elif self.type == "str":
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError(f"{self.label} must be 1-200 characters")
            value = value.strip()
        return value


DEFINITIONS: dict[str, SettingDef] = {
    d.key: d
    for d in (
        SettingDef("general.platform_name", "General", "Platform name",
                   "Shown in the browser title, reports and notifications.", "str", "AI-OpsBrain"),
        SettingDef("security.mfa_required", "Security", "Two-factor authentication required for",
                   "Users in scope must enrol an authenticator app at their next login.",
                   "enum", "admins", choices=("none", "admins", "all")),
        SettingDef("security.password_min_length", "Security", "Minimum password length",
                   "Applies to new and changed passwords.", "int", 12, 10, 128),
        SettingDef("security.session_idle_minutes", "Security", "Session idle timeout (minutes)",
                   "Sign users out after this much inactivity.", "int", 30, 5, 1440),
        SettingDef("security.session_max_hours", "Security", "Maximum session length (hours)",
                   "Sign users out after this long regardless of activity.", "int", 12, 1, 168),
        SettingDef("security.lockout_threshold", "Security", "Failed logins before lockout",
                   "Consecutive wrong passwords or codes before the account is locked.", "int", 5, 3, 20),
        SettingDef("security.lockout_minutes", "Security", "Lockout duration (minutes)",
                   "How long a locked account stays locked. Admins can unlock sooner.", "int", 15, 1, 1440),
    )
}


async def get_all(db: AsyncSession) -> dict[str, Any]:
    values = {k: d.default for k, d in DEFINITIONS.items()}
    for row in (await db.execute(select(Setting))).scalars():
        if row.key in DEFINITIONS:
            values[row.key] = row.value
    return values


async def get(db: AsyncSession, key: str) -> Any:
    row = await db.get(Setting, key)
    return row.value if row is not None else DEFINITIONS[key].default
