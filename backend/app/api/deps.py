import hmac
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Session, User
from app.models.base import utcnow
from app.security.crypto import token_hash
from app.services import audit
from app.services import settings as settings_svc

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def client_ip(request: Request) -> str | None:
    # The API is only reachable through Caddy on the private network; uvicorn's proxy-headers
    # support has already replaced request.client with the X-Forwarded-For address.
    return request.client.host if request.client else None


def actor_for(user: User, request: Request) -> audit.Actor:
    return audit.Actor(id=user.id, name=user.username, ip=client_ip(request))


async def _load_session(request: Request, db: AsyncSession) -> Session | None:
    token = request.cookies.get(get_settings().session_cookie)
    if not token:
        return None
    sess = (
        await db.execute(select(Session).where(Session.token_hash == token_hash(token)))
    ).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None:
        return None
    now = utcnow()
    idle = timedelta(minutes=int(await settings_svc.get(db, "security.session_idle_minutes")))
    if sess.expires_at <= now or sess.last_seen_at + idle <= now or not sess.user.is_active:
        return None  # expired rows are purged by the worker's session cleanup task
    # Avoid a write on every request: refresh activity at most once a minute.
    if now - sess.last_seen_at > timedelta(seconds=60):
        sess.last_seen_at = now
    return sess


def _check_csrf(request: Request, sess: Session) -> None:
    if request.method in SAFE_METHODS:
        return
    header = request.headers.get("x-csrf-token", "")
    if not header or not hmac.compare_digest(header, sess.csrf_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")


async def any_session(request: Request, db: AsyncSession = Depends(get_db)) -> Session:
    """A session in any state (used by the login continuation steps: MFA, enrolment, password change)."""
    sess = await _load_session(request, db)
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    _check_csrf(request, sess)
    return sess


async def full_session(sess: Session = Depends(any_session)) -> Session:
    if sess.state != "full":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Sign-in not complete: {sess.state}")
    return sess


async def current_user(sess: Session = Depends(full_session)) -> User:
    return sess.user


def require(permission: str) -> Callable[..., Coroutine[Any, Any, User]]:
    async def checker(request: Request, user: User = Depends(current_user)) -> User:
        if permission not in user.permissions:
            await audit.record_standalone(
                actor=actor_for(user, request),
                action="access.denied",
                resource_type="api",
                resource_id=f"{request.method} {request.url.path}",
                result="denied",
                detail=f"Missing permission {permission}",
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission}")
        return user

    return checker
