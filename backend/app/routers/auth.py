"""Sign-in, MFA, refresh, sessions and self-service password / MFA management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, security, sessions
from app import settings_registry as cfg
from app.db import get_db
from app.deps import CurrentUser, authenticated, authenticated_restricted_ok, build_current, request_ctx
from app.errors import ApiError
from app.models import AuthSession, User
from app.presenters import me_out
from app.ratelimit import auth_limiter
from app.schemas import (
    ChangePasswordIn,
    LoginIn,
    LoginOut,
    MfaDisableIn,
    MfaEnableIn,
    MfaEnableOut,
    MfaEnrollOut,
    MfaVerifyIn,
    MeOut,
    SessionOut,
    TokenOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC = "Invalid username or password, or the account is temporarily locked."


def _require_csrf_header(request: Request) -> None:
    """Cookie-authenticated endpoints must carry a header a cross-site form cannot set."""
    if request.headers.get("x-obs-csrf") != "1":
        raise ApiError(403, "csrf", "Missing CSRF header.")


def _is_locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > datetime.now(UTC))


def _register_failure(db: Session, user: User) -> str:
    """Count a failed credential attempt; lock the account when the threshold is reached."""
    threshold = int(cfg.get(db, "security.lockout_threshold"))
    minutes = int(cfg.get(db, "security.lockout_minutes"))
    user.failed_attempts = (user.failed_attempts or 0) + 1
    if user.failed_attempts >= threshold:
        user.locked_until = datetime.now(UTC) + timedelta(minutes=minutes)
        user.failed_attempts = 0
        return f"account locked for {minutes} minutes"
    return f"{user.failed_attempts}/{threshold} failed attempts"


def _complete_login(db: Session, user: User, ctx: audit.RequestContext, response: Response, method: str) -> LoginOut:
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    token, expires_in = sessions.start_session(db, user, ctx, response)
    audit.record(db, action="auth.login", actor=user, ctx=ctx, resource_type="user",
                 resource_id=user.id, resource_name=user.username, detail=f"method: {method}")
    db.commit()
    session_id = security.decode_access_token(token).session_id
    current = build_current(db, user, session_id)
    return LoginOut(status="ok", access_token=token, expires_in=expires_in, me=me_out(db, current))


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> LoginOut:
    ctx = request_ctx(request)
    auth_limiter.check(f"login:{ctx.ip}")
    username = body.username.strip().lower()
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    password_ok = security.verify_password(user.password_hash if user else None, body.password)
    invalid = ApiError(401, "invalid_credentials", _GENERIC)

    if user is None:
        audit.record(db, action="auth.login", result="failure", actor_name=username[:64], ctx=ctx, detail="unknown user")
        db.commit()
        raise invalid
    if not user.is_active:
        audit.record(db, action="auth.login", result="failure", actor=user, ctx=ctx, detail="account disabled")
        db.commit()
        raise invalid
    if _is_locked(user):
        audit.record(db, action="auth.login", result="failure", actor=user, ctx=ctx, detail="account locked")
        db.commit()
        raise invalid
    if not password_ok:
        detail = _register_failure(db, user)
        audit.record(db, action="auth.login", result="failure", actor=user, ctx=ctx, detail=f"wrong password; {detail}")
        db.commit()
        raise invalid

    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(body.password)
    if user.mfa_enabled:
        db.commit()
        return LoginOut(status="mfa_required", mfa_token=security.issue_mfa_token(user.id))
    return _complete_login(db, user, ctx, response, "password")


@router.post("/mfa/verify", response_model=LoginOut)
def mfa_verify(body: MfaVerifyIn, request: Request, response: Response, db: Session = Depends(get_db)) -> LoginOut:
    ctx = request_ctx(request)
    auth_limiter.check(f"mfa:{ctx.ip}")
    try:
        user_id = security.decode_mfa_token(body.mfa_token)
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise ApiError(401, "mfa_token_invalid", "The sign-in step expired. Start again.") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active or not user.mfa_enabled or user.mfa_secret_enc is None:
        raise ApiError(401, "mfa_token_invalid", "The sign-in step expired. Start again.")
    if _is_locked(user):
        audit.record(db, action="auth.mfa", result="failure", actor=user, ctx=ctx, detail="account locked")
        db.commit()
        raise ApiError(401, "invalid_credentials", _GENERIC)

    secret = security.decrypt_field(user.mfa_secret_enc)
    code = body.code.strip()
    step = security.check_totp(secret, code, user.mfa_last_step) if secret else None
    method = "password+totp"
    if step is not None:
        user.mfa_last_step = step
    else:
        digest = security.hash_recovery_code(code)
        if digest in (user.mfa_recovery or []):
            user.mfa_recovery = [h for h in user.mfa_recovery if h != digest]
            method = "password+recovery-code"
        else:
            detail = _register_failure(db, user)
            audit.record(db, action="auth.mfa", result="failure", actor=user, ctx=ctx, detail=f"wrong code; {detail}")
            db.commit()
            raise ApiError(401, "invalid_code", "That code is not valid.")
    return _complete_login(db, user, ctx, response, method)


@router.post("/refresh", response_model=TokenOut)
def refresh(
    request: Request, response: Response, db: Session = Depends(get_db),
    obs_refresh: str | None = Cookie(default=None),
) -> TokenOut:
    _require_csrf_header(request)
    ctx = request_ctx(request)
    user, token, expires_in, family = sessions.rotate_session(db, obs_refresh, ctx, response)
    db.commit()
    return TokenOut(access_token=token, expires_in=expires_in, me=me_out(db, build_current(db, user, family)))


@router.post("/logout", status_code=204)
def logout(
    request: Request, response: Response, db: Session = Depends(get_db),
    obs_refresh: str | None = Cookie(default=None),
) -> None:
    _require_csrf_header(request)
    ctx = request_ctx(request)
    if obs_refresh:
        row = db.execute(
            select(AuthSession).where(AuthSession.token_hash == security.sha256_hex(obs_refresh))
        ).scalar_one_or_none()
        if row is not None:
            sessions.revoke_family(db, row.family_id)
            user = db.get(User, row.user_id)
            audit.record(db, action="auth.logout", actor=user, ctx=ctx, resource_type="session", resource_id=row.family_id)
            db.commit()
    sessions.clear_cookie(response)


@router.get("/me", response_model=MeOut)
def me(current: CurrentUser = Depends(authenticated_restricted_ok), db: Session = Depends(get_db)) -> MeOut:
    return me_out(db, current)


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordIn, request: Request, db: Session = Depends(get_db),
    current: CurrentUser = Depends(authenticated_restricted_ok),
) -> None:
    ctx = request_ctx(request)
    user = current.user
    auth_limiter.check(f"chpw:{user.id}")
    if not security.verify_password(user.password_hash, body.current_password):
        audit.record(db, action="auth.password_change", result="failure", actor=user, ctx=ctx, detail="current password wrong")
        db.commit()
        raise ApiError(400, "wrong_password", "The current password is not correct.")
    if body.new_password == body.current_password:
        raise ApiError(422, "password_unchanged", "The new password must be different from the current one.")
    problems = security.password_problems(body.new_password, user.username, int(cfg.get(db, "security.password_min_length")))
    if problems:
        raise ApiError(422, "weak_password", "The new password " + "; ".join(problems) + ".")
    user.password_hash = security.hash_password(body.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(UTC)
    ended = sessions.revoke_user_sessions(db, user.id, except_family=current.session_id)  # type: ignore[arg-type]
    audit.record(db, action="auth.password_change", actor=user, ctx=ctx, resource_type="user",
                 resource_id=user.id, resource_name=user.username, detail=f"{ended} other session(s) ended")
    db.commit()


# ---------------------------------------------------------------- MFA self-service
@router.post("/mfa/enroll", response_model=MfaEnrollOut)
def mfa_enroll(
    request: Request, db: Session = Depends(get_db),
    current: CurrentUser = Depends(authenticated_restricted_ok),
) -> MfaEnrollOut:
    user = current.user
    if user.mfa_enabled:
        raise ApiError(409, "mfa_already_enabled", "Two-factor authentication is already on.")
    secret = security.new_totp_secret()
    user.mfa_secret_enc = security.encrypt_field(secret)
    audit.record(db, action="auth.mfa_enroll_started", actor=user, ctx=request_ctx(request),
                 resource_type="user", resource_id=user.id, resource_name=user.username)
    db.commit()
    issuer = str(cfg.get(db, "general.instance_name"))
    return MfaEnrollOut(secret=secret, otpauth_uri=security.totp_uri(secret, user.username, issuer))


@router.post("/mfa/enable", response_model=MfaEnableOut)
def mfa_enable(
    body: MfaEnableIn, request: Request, db: Session = Depends(get_db),
    current: CurrentUser = Depends(authenticated_restricted_ok),
) -> MfaEnableOut:
    user = current.user
    ctx = request_ctx(request)
    auth_limiter.check(f"mfa-enable:{user.id}")
    if user.mfa_enabled or user.mfa_secret_enc is None:
        raise ApiError(409, "mfa_not_pending", "Start the setup first.")
    secret = security.decrypt_field(user.mfa_secret_enc)
    step = security.check_totp(secret, body.code, None) if secret else None
    if step is None:
        audit.record(db, action="auth.mfa_enable", result="failure", actor=user, ctx=ctx, detail="wrong code")
        db.commit()
        raise ApiError(400, "invalid_code", "That code is not valid. Check the clock on your phone.")
    codes = security.generate_recovery_codes()
    user.mfa_enabled = True
    user.mfa_last_step = step
    user.mfa_recovery = [security.hash_recovery_code(c) for c in codes]
    audit.record(db, action="auth.mfa_enable", actor=user, ctx=ctx, resource_type="user",
                 resource_id=user.id, resource_name=user.username)
    db.commit()
    return MfaEnableOut(recovery_codes=codes)


@router.post("/mfa/disable", status_code=204)
def mfa_disable(
    body: MfaDisableIn, request: Request, db: Session = Depends(get_db),
    current: CurrentUser = Depends(authenticated),
) -> None:
    user = current.user
    ctx = request_ctx(request)
    auth_limiter.check(f"mfa-disable:{user.id}")
    if cfg.get(db, "security.require_mfa"):
        raise ApiError(403, "mfa_required_by_policy", "Two-factor authentication is required by policy and cannot be turned off.")
    if not user.mfa_enabled or user.mfa_secret_enc is None:
        raise ApiError(409, "mfa_not_enabled", "Two-factor authentication is not on.")
    secret = security.decrypt_field(user.mfa_secret_enc)
    step = security.check_totp(secret, body.code, user.mfa_last_step) if secret else None
    if not security.verify_password(user.password_hash, body.password) or step is None:
        audit.record(db, action="auth.mfa_disable", result="failure", actor=user, ctx=ctx, detail="password or code wrong")
        db.commit()
        raise ApiError(400, "invalid_credentials", "The password or code is not correct.")
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    user.mfa_recovery = []
    user.mfa_last_step = None
    sessions.revoke_user_sessions(db, user.id, except_family=current.session_id)  # type: ignore[arg-type]
    audit.record(db, action="auth.mfa_disable", actor=user, ctx=ctx, resource_type="user",
                 resource_id=user.id, resource_name=user.username)
    db.commit()


# ---------------------------------------------------------------- sessions
@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(current: CurrentUser = Depends(authenticated), db: Session = Depends(get_db)) -> list[SessionOut]:
    rows = db.execute(
        select(AuthSession)
        .where(AuthSession.user_id == current.user.id, AuthSession.revoked_at.is_(None),
               AuthSession.expires_at > datetime.now(UTC))
        .order_by(AuthSession.family_started_at.desc())
    ).scalars().all()
    return [
        SessionOut(id=r.family_id, created_at=r.family_started_at, last_used_at=r.last_used_at,
                   ip=r.ip, user_agent=r.user_agent, current=(r.family_id == current.session_id))
        for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def end_session(
    session_id: uuid.UUID, request: Request, current: CurrentUser = Depends(authenticated),
    db: Session = Depends(get_db),
) -> None:
    owned = db.execute(
        select(AuthSession.id).where(AuthSession.family_id == session_id, AuthSession.user_id == current.user.id).limit(1)
    ).first()
    if owned is None:
        raise ApiError(404, "not_found", "No such session.")
    sessions.revoke_family(db, session_id)
    audit.record(db, action="auth.session_revoked", actor=current.user, ctx=request_ctx(request),
                 resource_type="session", resource_id=session_id)
    db.commit()
