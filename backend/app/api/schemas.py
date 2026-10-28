import re
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.models import User

# Deliberately not pydantic's EmailStr: it rejects reserved TLDs such as .local and .test, which internal
# company mail domains commonly use. Addresses are entered by administrators, so a strict syntax check suffices.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
                       r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _check_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise ValueError("not a valid email address")
    return value


Email = Annotated[str, AfterValidator(_check_email)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    full_name: str
    is_active: bool
    mfa_enabled: bool
    must_change_password: bool
    roles: list[str]
    locked_until: datetime | None
    last_login_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            mfa_enabled=user.mfa_enabled,
            must_change_password=user.must_change_password,
            roles=sorted(r.name for r in user.roles),
            locked_until=user.locked_until,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
        )


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    email: Email
    full_name: str = Field(default="", max_length=255)
    roles: list[str] = Field(min_length=1)


class UserUpdate(BaseModel):
    email: Email | None = None
    full_name: str | None = Field(default=None, max_length=255)
    roles: list[str] | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class TempPassword(BaseModel):
    user: UserOut
    temporary_password: str = Field(description="Shown once. The user must change it at first sign-in.")


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    is_system: bool
    permissions: list[str]
    user_count: int = 0


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    description: str = Field(default="", max_length=500)
    permissions: list[str]


class RoleUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None


class PermissionOut(BaseModel):
    key: str
    group: str
    description: str


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor_id: uuid.UUID | None
    actor_name: str
    actor_ip: str | None
    action: str
    resource_type: str
    resource_id: str | None
    host_id: str | None
    old_value: Any
    new_value: Any
    result: str
    detail: str
    hash: str

    @field_validator("actor_ip", mode="before")
    @classmethod
    def _ip_to_str(cls, v: Any) -> str | None:
        return str(v) if v is not None else None


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_before_id: int | None


class Message(BaseModel):
    message: str
