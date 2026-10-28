import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import actor_for, current_user, require
from app.api.schemas import Message, PermissionOut, RoleCreate, RoleOut, RoleUpdate
from app.db import get_db
from app.models import Role, User, user_roles
from app.security.permissions import ADMIN_ROLE, PERMISSIONS, validate_permissions
from app.services import audit

router = APIRouter(prefix="/roles", tags=["roles"])


def _snapshot(role: Role) -> dict:
    return {"name": role.name, "description": role.description, "permissions": sorted(role.permissions)}


async def _user_counts(db: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await db.execute(select(user_roles.c.role_id, func.count()).group_by(user_roles.c.role_id))
    return {rid: n for rid, n in rows.all()}


async def _get(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return role


def _out(role: Role, count: int) -> RoleOut:
    return RoleOut(id=role.id, name=role.name, description=role.description, is_system=role.is_system,
                   permissions=sorted(role.permissions), user_count=count)


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(_: User = Depends(current_user)) -> list[PermissionOut]:
    return [PermissionOut(key=p.key, group=p.group, description=p.description) for p in PERMISSIONS]


@router.get("", response_model=list[RoleOut])
async def list_roles(_: User = Depends(require("users.manage")),
                     db: AsyncSession = Depends(get_db)) -> list[RoleOut]:
    counts = await _user_counts(db)
    roles = (await db.execute(select(Role).order_by(Role.is_system.desc(), Role.name))).scalars().all()
    return [_out(r, counts.get(r.id, 0)) for r in roles]


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(body: RoleCreate, request: Request, me: User = Depends(require("users.manage")),
                      db: AsyncSession = Depends(get_db)) -> RoleOut:
    try:
        perms = validate_permissions(body.permissions)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    role = Role(name=body.name.strip(), description=body.description, permissions=perms, is_system=False)
    db.add(role)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name exists") from exc
    await audit.record(db, actor=actor_for(me, request), action="role.create", resource_type="role",
                       resource_id=str(role.id), new=_snapshot(role))
    return _out(role, 0)


@router.patch("/{role_id}", response_model=RoleOut)
async def update_role(role_id: uuid.UUID, body: RoleUpdate, request: Request,
                      me: User = Depends(require("users.manage")),
                      db: AsyncSession = Depends(get_db)) -> RoleOut:
    role = await _get(db, role_id)
    old = _snapshot(role)
    if body.permissions is not None:
        if role.name == ADMIN_ROLE:
            raise HTTPException(status.HTTP_409_CONFLICT, "The Admin role always has every permission")
        try:
            role.permissions = validate_permissions(body.permissions)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if body.description is not None:
        role.description = body.description
    await db.flush()
    await audit.record(db, actor=actor_for(me, request), action="role.update", resource_type="role",
                       resource_id=str(role.id), old=old, new=_snapshot(role))
    return _out(role, (await _user_counts(db)).get(role.id, 0))


@router.delete("/{role_id}", response_model=Message)
async def delete_role(role_id: uuid.UUID, request: Request, me: User = Depends(require("users.manage")),
                      db: AsyncSession = Depends(get_db)) -> Message:
    role = await _get(db, role_id)
    if role.is_system:
        raise HTTPException(status.HTTP_409_CONFLICT, "Built-in roles cannot be deleted")
    if (await _user_counts(db)).get(role.id, 0):
        raise HTTPException(status.HTTP_409_CONFLICT, "Remove this role from all users first")
    old = _snapshot(role)
    await db.delete(role)
    await audit.record(db, actor=actor_for(me, request), action="role.delete", resource_type="role",
                       resource_id=str(role_id), old=old)
    return Message(message="Role deleted")
