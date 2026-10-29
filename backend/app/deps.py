"""Request-scoped dependencies: client context, authentication and permission checks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, security
from app import settings_registry as cfg
from app.db import get_db
from app.errors import ApiError
from app.models import AuthSession, User


def request_ctx(request: Request) -> audit.RequestContext:
    ip = request.client.host if request.client else None
    return audit.RequestContext(ip=ip, user_agent=request.headers.get("user-agent"))


@dataclass
class CurrentUser:
    user: User
    session_id: object
    permissions: frozenset[str]
    superuser: bool
    password_change_required: bool
    mfa_enrollment_required: bool

    @property
    def restricted(self) -> bool:
        return self.password_change_required or self.mfa_enrollment_required

    def can(self, permission: str) -> bool:
        return self.superuser or permission in self.permissions


def _authenticate(request: Request, db: Session) -> CurrentUser:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    try:
        claims = security.decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, "token_expired", "Your session expired. Sign in again.") from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise ApiError(401, "token_invalid", "Sign in to continue.") from exc

    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    alive = db.execute(
        select(AuthSession.id)
        .where(
            AuthSession.family_id == claims.session_id,
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
        .limit(1)
    ).first()
    if alive is None:
        raise ApiError(401, "session_revoked", "This session has ended. Sign in again.")

    return build_current(db, user, claims.session_id)


def build_current(db: Session, user: User, session_id: object) -> CurrentUser:
    require_mfa = bool(cfg.get(db, "security.require_mfa"))
    return CurrentUser(
        user=user,
        session_id=session_id,
        permissions=frozenset(user.role.permission_keys),
        superuser=user.role.is_superuser,
        password_change_required=user.must_change_password,
        mfa_enrollment_required=require_mfa and not user.mfa_enabled,
    )


def authenticated_restricted_ok(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    """For the few endpoints a user may call while a password change / MFA enrolment is pending."""
    return _authenticate(request, db)


def authenticated(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    current = _authenticate(request, db)
    if current.password_change_required:
        raise ApiError(403, "password_change_required", "You must change your password before continuing.")
    if current.mfa_enrollment_required:
        raise ApiError(403, "mfa_enrollment_required", "You must set up two-factor authentication before continuing.")
    return current


def require(*permissions: str) -> Callable[..., CurrentUser]:
    """Dependency factory. Denials are written to the audit log."""

    def dependency(request: Request, current: CurrentUser = Depends(authenticated)) -> CurrentUser:
        missing = [p for p in permissions if not current.can(p)]
        if missing:
            audit.record_independent(
                action="access.denied", result="denied", actor=current.user, ctx=request_ctx(request),
                detail=f"{request.method} {request.url.path} requires {', '.join(missing)}",
            )
            raise ApiError(403, "forbidden", "You do not have permission to do this.")
        return current

    return dependency
