"""Request / response models."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{2,31}$")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth ----
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MfaVerifyIn(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=16)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class MfaEnableIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MfaDisableIn(BaseModel):
    password: str = Field(max_length=256)
    code: str = Field(min_length=6, max_length=16)


class RoleRef(_Out):
    id: uuid.UUID
    name: str


class UserOut(_Out):
    id: uuid.UUID
    username: str
    email: str | None
    full_name: str
    role: RoleRef
    is_active: bool
    must_change_password: bool
    mfa_enabled: bool
    locked: bool = False
    last_login_at: datetime | None
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut
    permissions: list[str]
    superuser: bool
    password_change_required: bool
    mfa_enrollment_required: bool
    instance_name: str


class LoginOut(BaseModel):
    status: Literal["ok", "mfa_required"]
    access_token: str | None = None
    expires_in: int | None = None
    mfa_token: str | None = None
    me: MeOut | None = None


class TokenOut(BaseModel):
    access_token: str
    expires_in: int
    me: MeOut


class MfaEnrollOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaEnableOut(BaseModel):
    recovery_codes: list[str]


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime | None
    ip: str | None
    user_agent: str | None
    current: bool


# ---- users ----
class UserCreate(BaseModel):
    username: str
    email: EmailStr | None = None
    full_name: str = Field(default="", max_length=128)
    role_id: uuid.UUID
    password: str | None = Field(default=None, max_length=256)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("3-32 characters: lowercase letters, digits, '.', '_' or '-'; must start with a letter")
        return v


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=128)
    role_id: uuid.UUID | None = None
    is_active: bool | None = None


class UserCreated(BaseModel):
    user: UserOut
    temporary_password: str | None = None


class PasswordResetOut(BaseModel):
    temporary_password: str


# ---- roles ----
class RoleOut(_Out):
    id: uuid.UUID
    name: str
    description: str
    is_system: bool
    is_superuser: bool
    permissions: list[str]
    user_count: int = 0


class RoleWrite(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = Field(default="", max_length=255)
    permissions: list[str]


class PermissionOut(BaseModel):
    key: str
    group: str
    description: str


# ---- audit ----
class AuditOut(_Out):
    id: int
    ts: datetime
    actor_name: str
    action: str
    resource_type: str | None
    resource_id: str | None
    resource_name: str | None
    host_id: str | None
    old_value: Any
    new_value: Any
    result: str
    detail: str | None
    ip: str | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_before_id: int | None


class ChainOut(BaseModel):
    ok: bool
    checked: int
    first_bad_id: int | None
    reason: str | None


# ---- settings ----
class SettingOut(BaseModel):
    key: str
    group: str
    description: str
    type: str
    value: Any
    default: Any
    minimum: int | None = None
    maximum: int | None = None


class SettingsUpdate(BaseModel):
    changes: dict[str, Any]


# ---- system ----
class CheckOut(BaseModel):
    name: str
    source: str
    status: str
    detail: str
    checked_at: datetime | None
    stale: bool = False


class StatusOut(BaseModel):
    overall: str
    version: str
    checks: list[CheckOut]
