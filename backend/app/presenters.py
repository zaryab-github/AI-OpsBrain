"""Build API output models from ORM objects."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import settings_registry as cfg
from app.deps import CurrentUser
from app.models import User
from app.rbac.permissions import PERMISSION_KEYS
from app.schemas import MeOut, RoleRef, UserOut


def user_out(user: User) -> UserOut:
    locked = bool(user.locked_until and user.locked_until > datetime.now(UTC))
    return UserOut(
        id=user.id, username=user.username, email=user.email, full_name=user.full_name,
        role=RoleRef(id=user.role.id, name=user.role.name), is_active=user.is_active,
        must_change_password=user.must_change_password, mfa_enabled=user.mfa_enabled, locked=locked,
        last_login_at=user.last_login_at, created_at=user.created_at,
    )


def me_out(db: Session, current: CurrentUser) -> MeOut:
    return MeOut(
        user=user_out(current.user),
        permissions=sorted(PERMISSION_KEYS) if current.superuser else sorted(current.permissions),
        superuser=current.superuser,
        password_change_required=current.password_change_required,
        mfa_enrollment_required=current.mfa_enrollment_required,
        instance_name=str(cfg.get(db, "general.instance_name")),
    )
