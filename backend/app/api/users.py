import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import actor_for, require
from app.api.schemas import TempPassword, UserCreate, UserOut, UserUpdate
from app.db import get_db
from app.models import Role, Session, User
from app.models.base import utcnow
from app.security import crypto
from app.security.permissions import ADMIN_ROLE
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])


def _snapshot(user: User) -> dict:
    return {
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "roles": sorted(r.name for r in user.roles),
        "mfa_enabled": user.mfa_enabled,
    }


async def _roles_by_name(db: AsyncSession, names: list[str]) -> list[Role]:
    roles = (await db.execute(select(Role).where(Role.name.in_(names)))).scalars().all()
    missing = sorted(set(names) - {r.name for r in roles})
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown roles: {', '.join(missing)}")
    return list(roles)


async def _active_admin_count(db: AsyncSession, excluding: uuid.UUID | None = None) -> int:
    q = (select(func.count(func.distinct(User.id))).select_from(User).join(User.roles)
         .where(Role.name == ADMIN_ROLE, User.is_active.is_(True)))
    if excluding is not None:
        q = q.where(User.id != excluding)
    return int((await db.execute(q)).scalar_one())


async def _get(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def _revoke_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
                     .values(revoked_at=utcnow()))


@router.get("", response_model=list[UserOut])
async def list_users(_: User = Depends(require("users.manage")),
                     db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    users = (await db.execute(select(User).order_by(User.username))).scalars().all()
    return [UserOut.of(u) for u in users]


@router.post("", response_model=TempPassword, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, request: Request, me: User = Depends(require("users.manage")),
                      db: AsyncSession = Depends(get_db)) -> TempPassword:
    temp = crypto.generate_password()
    user = User(username=body.username.lower(), email=str(body.email).lower(), full_name=body.full_name,
                password_hash=await crypto.hash_password_async(temp), must_change_password=True)
    user.roles = await _roles_by_name(db, body.roles)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists") from exc
    await audit.record(db, actor=actor_for(me, request), action="user.create", resource_type="user",
                       resource_id=str(user.id), new=_snapshot(user))
    return TempPassword(user=UserOut.of(user), temporary_password=temp)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, _: User = Depends(require("users.manage")),
                   db: AsyncSession = Depends(get_db)) -> UserOut:
    return UserOut.of(await _get(db, user_id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request,
                      me: User = Depends(require("users.manage")),
                      db: AsyncSession = Depends(get_db)) -> UserOut:
    user = await _get(db, user_id)
    old = _snapshot(user)
    if body.email is not None:
        user.email = str(body.email).lower()
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.roles is not None:
        user.roles = await _roles_by_name(db, body.roles)
    if body.is_active is not None:
        if not body.is_active and user.id == me.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot deactivate your own account")
        user.is_active = body.is_active
        if not user.is_active:
            await _revoke_sessions(db, user.id)
    still_admin = ADMIN_ROLE in {r.name for r in user.roles} and user.is_active
    if not still_admin and await _active_admin_count(db, excluding=user.id) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "At least one active Admin must remain")
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use") from exc
    await audit.record(db, actor=actor_for(me, request), action="user.update", resource_type="user",
                       resource_id=str(user.id), old=old, new=_snapshot(user))
    return UserOut.of(user)


@router.post("/{user_id}/reset-password", response_model=TempPassword)
async def reset_password(user_id: uuid.UUID, request: Request, me: User = Depends(require("users.manage")),
                         db: AsyncSession = Depends(get_db)) -> TempPassword:
    user = await _get(db, user_id)
    temp = crypto.generate_password()
    user.password_hash = await crypto.hash_password_async(temp)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
    await _revoke_sessions(db, user.id)
    await audit.record(db, actor=actor_for(me, request), action="user.password_reset", resource_type="user",
                       resource_id=str(user.id), detail="temporary password issued; sessions signed out")
    return TempPassword(user=UserOut.of(user), temporary_password=temp)


@router.post("/{user_id}/reset-mfa", response_model=UserOut)
async def reset_mfa(user_id: uuid.UUID, request: Request, me: User = Depends(require("users.manage")),
                    db: AsyncSession = Depends(get_db)) -> UserOut:
    user = await _get(db, user_id)
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    user.mfa_last_counter = None
    await _revoke_sessions(db, user.id)
    await audit.record(db, actor=actor_for(me, request), action="user.mfa_reset", resource_type="user",
                       resource_id=str(user.id), old={"mfa_enabled": True}, new={"mfa_enabled": False})
    return UserOut.of(user)


@router.post("/{user_id}/unlock", response_model=UserOut)
async def unlock(user_id: uuid.UUID, request: Request, me: User = Depends(require("users.manage")),
                 db: AsyncSession = Depends(get_db)) -> UserOut:
    user = await _get(db, user_id)
    old = {"locked_until": user.locked_until.isoformat() if user.locked_until else None}
    user.locked_until = None
    user.failed_logins = 0
    await audit.record(db, actor=actor_for(me, request), action="user.unlock", resource_type="user",
                       resource_id=str(user.id), old=old, new={"locked_until": None})
    return UserOut.of(user)
