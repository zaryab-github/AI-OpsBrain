"""Login-session lifecycle: issuing, rotating (with reuse detection) and revoking refresh tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import audit, security
from app import settings_registry as cfg
from app.config import get_config
from app.errors import ApiError
from app.models import AuthSession, User

COOKIE_NAME = "obs_refresh"
COOKIE_PATH = "/api/v1/auth"
MAX_FAMILY_DAYS = 30


def _now() -> datetime:
    return datetime.now(UTC)


def set_cookie(response: Response, raw: str, seconds: int) -> None:
    response.set_cookie(
        COOKIE_NAME, raw, max_age=max(60, seconds), path=COOKIE_PATH,
        httponly=True, secure=get_config().cookie_secure, samesite="strict",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)


def start_session(db: Session, user: User, ctx: audit.RequestContext, response: Response) -> tuple[str, int]:
    """Create a new login session; returns (access_token, expires_in_seconds)."""
    days = int(cfg.get(db, "security.session_days"))
    minutes = int(cfg.get(db, "security.access_token_minutes"))
    raw, digest = security.new_refresh_token()
    family = uuid.uuid4()
    now = _now()
    db.add(AuthSession(
        user_id=user.id, family_id=family, token_hash=digest, family_started_at=now,
        expires_at=now + timedelta(days=days), last_used_at=now,
        ip=ctx.ip, user_agent=(ctx.user_agent or "")[:255] or None,
    ))
    db.flush()
    set_cookie(response, raw, days * 86400)
    return security.issue_access_token(user.id, family, minutes), minutes * 60


def rotate_session(db: Session, raw: str | None, ctx: audit.RequestContext, response: Response) -> tuple[User, str, int, uuid.UUID]:
    """Exchange a refresh token for a new one. A reused (already rotated) token revokes the family."""
    if not raw:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    digest = security.sha256_hex(raw)
    row = db.execute(select(AuthSession).where(AuthSession.token_hash == digest).with_for_update()).scalar_one_or_none()
    if row is None:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    now = _now()
    if row.revoked_at is not None:
        # Someone presented a token that was already rotated: assume theft, end the whole session.
        revoke_family(db, row.family_id)
        user = db.get(User, row.user_id)
        audit.record(db, action="auth.refresh_reuse_detected", result="denied", actor=user, ctx=ctx,
                     resource_type="session", resource_id=row.family_id,
                     detail="a rotated refresh token was presented again; the session was revoked")
        db.commit()
        raise ApiError(401, "session_revoked", "This session has ended. Sign in again.")
    if row.expires_at <= now:
        raise ApiError(401, "session_expired", "Your session expired. Sign in again.")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")

    days = int(cfg.get(db, "security.session_days"))
    minutes = int(cfg.get(db, "security.access_token_minutes"))
    new_raw, new_digest = security.new_refresh_token()
    hard_limit = row.family_started_at + timedelta(days=MAX_FAMILY_DAYS)
    expires = min(now + timedelta(days=days), hard_limit)
    row.revoked_at = now
    db.add(AuthSession(
        user_id=user.id, family_id=row.family_id, token_hash=new_digest,
        family_started_at=row.family_started_at, expires_at=expires, last_used_at=now,
        ip=ctx.ip, user_agent=(ctx.user_agent or "")[:255] or None,
    ))
    db.flush()
    set_cookie(response, new_raw, int((expires - now).total_seconds()))
    return user, security.issue_access_token(user.id, row.family_id, minutes), minutes * 60, row.family_id


def revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def revoke_user_sessions(db: Session, user_id: uuid.UUID, except_family: uuid.UUID | None = None) -> int:
    stmt = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if except_family is not None:
        stmt = stmt.where(AuthSession.family_id != except_family)
    return db.execute(stmt.values(revoked_at=_now())).rowcount or 0
