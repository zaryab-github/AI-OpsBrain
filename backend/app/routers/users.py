"""User administration. Users are deactivated, never deleted, so the audit trail stays meaningful."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, security, sessions
from app import settings_registry as cfg
from app.db import get_db
from app.deps import CurrentUser, request_ctx, require
from app.errors import ApiError
from app.models import Role, User
from app.presenters import user_out
from app.schemas import PasswordResetOut, UserCreate, UserCreated, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _get(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found", "No such user.")
    return user


def _role(db: Session, role_id: uuid.UUID) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise ApiError(422, "unknown_role", "That role does not exist.")
    return role


def _active_superusers(db: Session) -> int:
    return db.execute(
        select(func.count()).select_from(User).join(Role, User.role_id == Role.id)
        .where(User.is_active.is_(True), Role.is_superuser.is_(True))
    ).scalar_one()


def _snapshot(user: User) -> dict:
    return {"username": user.username, "email": user.email, "full_name": user.full_name,
            "role": user.role.name, "is_active": user.is_active}


@router.get("", response_model=list[UserOut])
def list_users(_: CurrentUser = Depends(require("users.view")), db: Session = Depends(get_db)) -> list[UserOut]:
    users = db.execute(select(User).order_by(User.username)).scalars().all()
    return [user_out(u) for u in users]


@router.post("", response_model=UserCreated, status_code=201)
def create_user(
    body: UserCreate, request: Request, current: CurrentUser = Depends(require("users.manage")),
    db: Session = Depends(get_db),
) -> UserCreated:
    if db.execute(select(User.id).where(User.username == body.username)).first():
        raise ApiError(409, "username_taken", "That username is already in use.")
    role = _role(db, body.role_id)
    generated = body.password is None
    password = body.password or security.generate_password()
    if not generated:
        problems = security.password_problems(password, body.username, int(cfg.get(db, "security.password_min_length")))
        if problems:
            raise ApiError(422, "weak_password", "The password " + "; ".join(problems) + ".")
    user = User(
        username=body.username, email=body.email, full_name=body.full_name, role_id=role.id, role=role,
        password_hash=security.hash_password(password), must_change_password=True,
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    audit.record(db, action="user.create", actor=current.user, ctx=request_ctx(request), resource_type="user",
                 resource_id=user.id, resource_name=user.username, new=_snapshot(user))
    db.commit()
    return UserCreated(user=user_out(user), temporary_password=password if generated else None)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, _: CurrentUser = Depends(require("users.view")), db: Session = Depends(get_db)) -> UserOut:
    return user_out(_get(db, user_id))


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID, body: UserUpdate, request: Request,
    current: CurrentUser = Depends(require("users.manage")), db: Session = Depends(get_db),
) -> UserOut:
    user = _get(db, user_id)
    old = _snapshot(user)
    fields = body.model_fields_set
    if "is_active" in fields and body.is_active is not None:
        if user.id == current.user.id and not body.is_active:
            raise ApiError(409, "cannot_disable_self", "You cannot disable your own account.")
        user.is_active = body.is_active
    if "role_id" in fields and body.role_id is not None:
        user.role = _role(db, body.role_id)
        user.role_id = user.role.id
    if "email" in fields:
        user.email = body.email
    if "full_name" in fields and body.full_name is not None:
        user.full_name = body.full_name
    db.flush()
    # The platform must always keep at least one active administrator.
    if (old["role"] != user.role.name or old["is_active"] != user.is_active) and _active_superusers(db) == 0:
        db.rollback()
        raise ApiError(409, "last_admin", "At least one active administrator must remain.")
    if old["is_active"] and not user.is_active:
        sessions.revoke_user_sessions(db, user.id)
    new = _snapshot(user)
    audit.record(db, action="user.update", actor=current.user, ctx=request_ctx(request), resource_type="user",
                 resource_id=user.id, resource_name=user.username, old=old, new=new)
    db.commit()
    return user_out(user)


@router.post("/{user_id}/reset-password", response_model=PasswordResetOut)
def reset_password(
    user_id: uuid.UUID, request: Request, current: CurrentUser = Depends(require("users.manage")),
    db: Session = Depends(get_db),
) -> PasswordResetOut:
    user = _get(db, user_id)
    temp = security.generate_password()
    user.password_hash = security.hash_password(temp)
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    sessions.revoke_user_sessions(db, user.id)
    audit.record(db, action="user.reset_password", actor=current.user, ctx=request_ctx(request),
                 resource_type="user", resource_id=user.id, resource_name=user.username,
                 detail="temporary password issued; all sessions ended")
    db.commit()
    return PasswordResetOut(temporary_password=temp)


@router.post("/{user_id}/unlock", status_code=204)
def unlock(
    user_id: uuid.UUID, request: Request, current: CurrentUser = Depends(require("users.manage")),
    db: Session = Depends(get_db),
) -> None:
    user = _get(db, user_id)
    user.failed_attempts = 0
    user.locked_until = None
    audit.record(db, action="user.unlock", actor=current.user, ctx=request_ctx(request),
                 resource_type="user", resource_id=user.id, resource_name=user.username)
    db.commit()


@router.post("/{user_id}/reset-mfa", status_code=204)
def reset_mfa(
    user_id: uuid.UUID, request: Request, current: CurrentUser = Depends(require("users.manage")),
    db: Session = Depends(get_db),
) -> None:
    user = _get(db, user_id)
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    user.mfa_recovery = []
    user.mfa_last_step = None
    sessions.revoke_user_sessions(db, user.id)
    audit.record(db, action="user.reset_mfa", actor=current.user, ctx=request_ctx(request),
                 resource_type="user", resource_id=user.id, resource_name=user.username,
                 detail="two-factor authentication removed; all sessions ended")
    db.commit()
