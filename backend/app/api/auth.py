import logging
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import actor_for, any_session, client_ip, full_session
from app.api.schemas import Message, UserOut
from app.config import get_settings
from app.db import get_db
from app.models import Session, User
from app.models.base import utcnow
from app.redis_client import get_redis
from app.security import crypto, mfa
from app.security.passwords import check_password_policy
from app.services import audit
from app.services import settings as settings_svc

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Invalid username or password, or the account is locked."
PRIVILEGED = {"users.manage", "settings.manage"}


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class PasswordConfirmIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AuthState(BaseModel):
    state: str
    user: UserOut | None = None
    permissions: list[str] = []
    mfa_required_by_policy: bool = False


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class SessionOut(BaseModel):
    id: uuid.UUID
    ip: str | None
    user_agent: str
    created_at: str
    last_seen_at: str
    current: bool


async def mfa_required_for(db: AsyncSession, user: User) -> bool:
    policy = await settings_svc.get(db, "security.mfa_required")
    return policy == "all" or (policy == "admins" and bool(user.permissions & PRIVILEGED))


async def next_state(db: AsyncSession, user: User, *, mfa_verified: bool) -> str:
    if user.mfa_enabled and not mfa_verified:
        return "mfa_required"
    if user.must_change_password:
        return "password_change_required"
    if not user.mfa_enabled and await mfa_required_for(db, user):
        return "mfa_enrollment_required"
    return "full"


async def auth_state(db: AsyncSession, sess: Session) -> AuthState:
    user = sess.user
    full = sess.state == "full"
    return AuthState(
        state=sess.state,
        user=UserOut.of(user),
        permissions=sorted(user.permissions) if full else [],
        mfa_required_by_policy=await mfa_required_for(db, user),
    )


def _set_cookies(response: Response, token: str, csrf: str, max_age: int) -> None:
    s = get_settings()
    response.set_cookie(s.session_cookie, token, max_age=max_age, httponly=True, secure=True,
                        samesite="strict", path="/")
    # Readable by the SPA, which echoes it in X-CSRF-Token on state-changing requests.
    response.set_cookie(s.csrf_cookie, csrf, max_age=max_age, httponly=False, secure=True,
                        samesite="strict", path="/")


def _clear_cookies(response: Response) -> None:
    s = get_settings()
    for name in (s.session_cookie, s.csrf_cookie):
        response.delete_cookie(name, path="/", secure=True, samesite="strict")


async def _ip_rate_limited(ip: str | None) -> bool:
    s = get_settings()
    key = f"opsbrain:login:ip:{ip or 'unknown'}"
    try:
        r = get_redis()
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, s.login_ip_window_seconds)
        return count > s.login_ip_limit
    except Exception:
        # Per-account lockout in the database still applies; don't take login down with Redis.
        log.warning("login rate limiter unavailable", exc_info=True)
        return False


async def _register_failure(db: AsyncSession, user: User) -> None:
    user.failed_logins += 1
    threshold = int(await settings_svc.get(db, "security.lockout_threshold"))
    if user.failed_logins >= threshold:
        minutes = int(await settings_svc.get(db, "security.lockout_minutes"))
        user.locked_until = utcnow() + timedelta(minutes=minutes)
        user.failed_logins = 0


@router.post("/login", response_model=AuthState)
async def login(body: LoginIn, request: Request, response: Response,
                db: AsyncSession = Depends(get_db)) -> AuthState:
    ip = client_ip(request)
    if await _ip_rate_limited(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many sign-in attempts. Try again later.")

    ident = body.username.strip().lower()
    user = (
        await db.execute(select(User).where(or_(User.username == ident, func.lower(User.email) == ident)))
    ).scalar_one_or_none()
    password_ok = await crypto.verify_password_async(user.password_hash if user else None, body.password)
    now = utcnow()

    if user is None or not user.is_active or (user.locked_until and user.locked_until > now) or not password_ok:
        reason = ("unknown user" if user is None else "inactive account" if not user.is_active
                  else "account locked" if user.locked_until and user.locked_until > now else "wrong password")
        if user is not None and reason == "wrong password":
            await _register_failure(db, user)
        await audit.record(db, actor=audit.Actor(id=user.id if user else None, name=ident[:128], ip=ip),
                           action="auth.login", resource_type="user",
                           resource_id=str(user.id) if user else None, result="failure", detail=reason)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    user.failed_logins = 0
    user.locked_until = None
    if crypto.password_needs_rehash(user.password_hash):
        user.password_hash = await crypto.hash_password_async(body.password)

    state = await next_state(db, user, mfa_verified=False)
    max_hours = int(await settings_svc.get(db, "security.session_max_hours"))
    token, csrf = crypto.new_token(), crypto.new_token()
    sess = Session(token_hash=crypto.token_hash(token), csrf_token=csrf, user_id=user.id, state=state,
                   ip=ip, user_agent=(request.headers.get("user-agent") or "")[:512],
                   expires_at=now + timedelta(hours=max_hours), last_seen_at=now)
    sess.user = user
    db.add(sess)
    if state == "full":
        user.last_login_at = now
    await audit.record(db, actor=audit.Actor(user.id, user.username, ip), action="auth.login",
                       resource_type="user", resource_id=str(user.id),
                       detail="password accepted" + ("" if state == "full" else f"; next step: {state}"))
    await db.flush()
    _set_cookies(response, token, csrf, max_hours * 3600)
    return await auth_state(db, sess)


@router.post("/mfa/verify", response_model=AuthState)
async def mfa_verify(body: CodeIn, request: Request, sess: Session = Depends(any_session),
                     db: AsyncSession = Depends(get_db)) -> AuthState:
    if sess.state != "mfa_required":
        raise HTTPException(status.HTTP_409_CONFLICT, "No two-factor check pending")
    user = sess.user
    counter = mfa.verify(crypto.decrypt(user.mfa_secret_enc or ""), body.code, user.mfa_last_counter)
    if counter is None:
        await _register_failure(db, user)
        if user.locked_until:
            sess.revoked_at = utcnow()
        await audit.record(db, actor=actor_for(user, request), action="auth.mfa", resource_type="user",
                           resource_id=str(user.id), result="failure", detail="wrong code")
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code")
    user.mfa_last_counter = counter
    user.failed_logins = 0
    sess.state = await next_state(db, user, mfa_verified=True)
    if sess.state == "full":
        user.last_login_at = utcnow()
    await audit.record(db, actor=actor_for(user, request), action="auth.mfa", resource_type="user",
                       resource_id=str(user.id))
    return await auth_state(db, sess)


@router.post("/mfa/setup", response_model=MfaSetupOut)
async def mfa_setup(sess: Session = Depends(any_session)) -> MfaSetupOut:
    if sess.state not in ("full", "mfa_enrollment_required"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Finish the current sign-in step first")
    if sess.user.mfa_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor authentication is already enabled")
    secret = mfa.new_secret()
    sess.mfa_pending_secret_enc = crypto.encrypt(secret)
    return MfaSetupOut(secret=secret, otpauth_uri=mfa.provisioning_uri(secret, sess.user.username))


@router.post("/mfa/enable", response_model=AuthState)
async def mfa_enable(body: CodeIn, request: Request, sess: Session = Depends(any_session),
                     db: AsyncSession = Depends(get_db)) -> AuthState:
    if sess.state not in ("full", "mfa_enrollment_required") or not sess.mfa_pending_secret_enc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Start two-factor setup first")
    secret = crypto.decrypt(sess.mfa_pending_secret_enc)
    counter = mfa.verify(secret, body.code, None)
    if counter is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code. Check the time on your phone.")
    user = sess.user
    user.mfa_secret_enc = crypto.encrypt(secret)
    user.mfa_enabled = True
    user.mfa_last_counter = counter
    sess.mfa_pending_secret_enc = None
    if sess.state != "full":
        sess.state = await next_state(db, user, mfa_verified=True)
        if sess.state == "full":
            user.last_login_at = utcnow()
    await audit.record(db, actor=actor_for(user, request), action="user.mfa_enable", resource_type="user",
                       resource_id=str(user.id), old={"mfa_enabled": False}, new={"mfa_enabled": True})
    return await auth_state(db, sess)


@router.post("/mfa/disable", response_model=AuthState)
async def mfa_disable(body: PasswordConfirmIn, request: Request, sess: Session = Depends(full_session),
                      db: AsyncSession = Depends(get_db)) -> AuthState:
    user = sess.user
    if not await crypto.verify_password_async(user.password_hash, body.password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is incorrect")
    if await mfa_required_for(db, user):
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor authentication is required for your account")
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    user.mfa_last_counter = None
    await audit.record(db, actor=actor_for(user, request), action="user.mfa_disable", resource_type="user",
                       resource_id=str(user.id), old={"mfa_enabled": True}, new={"mfa_enabled": False})
    return await auth_state(db, sess)


@router.post("/password", response_model=AuthState)
async def change_password(body: PasswordChangeIn, request: Request, sess: Session = Depends(any_session),
                          db: AsyncSession = Depends(get_db)) -> AuthState:
    if sess.state not in ("full", "password_change_required"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Finish the current sign-in step first")
    user = sess.user
    if not await crypto.verify_password_async(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must differ from the current one")
    min_len = int(await settings_svc.get(db, "security.password_min_length"))
    problems = check_password_policy(body.new_password, username=user.username, min_length=min_len)
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, " ".join(problems))
    user.password_hash = await crypto.hash_password_async(body.new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    # Sign out every other session of this user.
    await db.execute(update(Session).where(Session.user_id == user.id, Session.id != sess.id,
                                           Session.revoked_at.is_(None)).values(revoked_at=utcnow()))
    if sess.state != "full":
        sess.state = await next_state(db, user, mfa_verified=True)
        if sess.state == "full":
            user.last_login_at = utcnow()
    await audit.record(db, actor=actor_for(user, request), action="user.password_change",
                       resource_type="user", resource_id=str(user.id), detail="other sessions signed out")
    return await auth_state(db, sess)


@router.post("/logout", response_model=Message)
async def logout(request: Request, response: Response, sess: Session = Depends(any_session),
                 db: AsyncSession = Depends(get_db)) -> Message:
    sess.revoked_at = utcnow()
    await audit.record(db, actor=actor_for(sess.user, request), action="auth.logout", resource_type="user",
                       resource_id=str(sess.user_id))
    _clear_cookies(response)
    return Message(message="Signed out")


@router.get("/me", response_model=AuthState)
async def me(sess: Session = Depends(any_session), db: AsyncSession = Depends(get_db)) -> AuthState:
    return await auth_state(db, sess)


@router.get("/sessions", response_model=list[SessionOut])
async def my_sessions(sess: Session = Depends(full_session), db: AsyncSession = Depends(get_db)) -> list[SessionOut]:
    rows = (await db.execute(
        select(Session).where(Session.user_id == sess.user_id, Session.revoked_at.is_(None),
                              Session.expires_at > utcnow()).order_by(Session.last_seen_at.desc())
    )).scalars().all()
    return [SessionOut(id=r.id, ip=str(r.ip) if r.ip else None, user_agent=r.user_agent,
                       created_at=r.created_at.isoformat(), last_seen_at=r.last_seen_at.isoformat(),
                       current=r.id == sess.id) for r in rows]


@router.delete("/sessions/{session_id}", response_model=Message)
async def revoke_session(session_id: uuid.UUID, request: Request, sess: Session = Depends(full_session),
                         db: AsyncSession = Depends(get_db)) -> Message:
    target = await db.get(Session, session_id)
    if target is None or target.user_id != sess.user_id or target.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    target.revoked_at = utcnow()
    await audit.record(db, actor=actor_for(sess.user, request), action="auth.session_revoke",
                       resource_type="session", resource_id=str(session_id))
    return Message(message="Session signed out")
