"""Roles and the permission matrix. Built-in roles are fixed; custom roles can be edited."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import CurrentUser, request_ctx, require
from app.errors import ApiError
from app.models import Role, RolePermission, User
from app.rbac.permissions import PERMISSION_KEYS, PERMISSIONS
from app.schemas import PermissionOut, RoleOut, RoleWrite

router = APIRouter(tags=["roles"])


def _out(role: Role, count: int) -> RoleOut:
    keys = sorted(PERMISSION_KEYS) if role.is_superuser else role.permission_keys
    return RoleOut(id=role.id, name=role.name, description=role.description, is_system=role.is_system,
                   is_superuser=role.is_superuser, permissions=keys, user_count=count)


def _counts(db: Session) -> dict[uuid.UUID, int]:
    return dict(db.execute(select(User.role_id, func.count()).group_by(User.role_id)).all())


def _validate_permissions(permissions: list[str]) -> list[str]:
    unknown = sorted(set(permissions) - PERMISSION_KEYS)
    if unknown:
        raise ApiError(422, "unknown_permission", "Unknown permission(s): " + ", ".join(unknown))
    return sorted(set(permissions))


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(_: CurrentUser = Depends(require("roles.view"))) -> list[PermissionOut]:
    return [PermissionOut(key=p.key, group=p.group, description=p.description) for p in PERMISSIONS]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(_: CurrentUser = Depends(require("roles.view")), db: Session = Depends(get_db)) -> list[RoleOut]:
    counts = _counts(db)
    roles = db.execute(select(Role).order_by(Role.is_system.desc(), Role.name)).scalars().all()
    return [_out(r, counts.get(r.id, 0)) for r in roles]


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(
    body: RoleWrite, request: Request, current: CurrentUser = Depends(require("roles.manage")),
    db: Session = Depends(get_db),
) -> RoleOut:
    name = body.name.strip()
    if db.execute(select(Role.id).where(func.lower(Role.name) == name.lower())).first():
        raise ApiError(409, "role_exists", "A role with that name already exists.")
    perms = _validate_permissions(body.permissions)
    role = Role(name=name, description=body.description.strip(), is_system=False, is_superuser=False)
    role.permissions = [RolePermission(permission=p) for p in perms]
    db.add(role)
    db.flush()
    audit.record(db, action="role.create", actor=current.user, ctx=request_ctx(request), resource_type="role",
                 resource_id=role.id, resource_name=role.name, new={"permissions": perms, "description": role.description})
    db.commit()
    return _out(role, 0)


def _get_editable(db: Session, role_id: uuid.UUID) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise ApiError(404, "not_found", "No such role.")
    if role.is_system:
        raise ApiError(409, "system_role", "Built-in roles cannot be changed. Create a custom role instead.")
    return role


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: uuid.UUID, body: RoleWrite, request: Request,
    current: CurrentUser = Depends(require("roles.manage")), db: Session = Depends(get_db),
) -> RoleOut:
    role = _get_editable(db, role_id)
    name = body.name.strip()
    clash = db.execute(select(Role.id).where(func.lower(Role.name) == name.lower(), Role.id != role.id)).first()
    if clash:
        raise ApiError(409, "role_exists", "A role with that name already exists.")
    perms = _validate_permissions(body.permissions)
    old = {"name": role.name, "description": role.description, "permissions": role.permission_keys}
    role.name = name
    role.description = body.description.strip()
    role.permissions = [RolePermission(permission=p) for p in perms]
    db.flush()
    audit.record(db, action="role.update", actor=current.user, ctx=request_ctx(request), resource_type="role",
                 resource_id=role.id, resource_name=role.name, old=old,
                 new={"name": role.name, "description": role.description, "permissions": perms})
    db.commit()
    return _out(role, _counts(db).get(role.id, 0))


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(
    role_id: uuid.UUID, request: Request, current: CurrentUser = Depends(require("roles.manage")),
    db: Session = Depends(get_db),
) -> None:
    role = _get_editable(db, role_id)
    if _counts(db).get(role.id, 0):
        raise ApiError(409, "role_in_use", "Users still have this role. Move them to another role first.")
    audit.record(db, action="role.delete", actor=current.user, ctx=request_ctx(request), resource_type="role",
                 resource_id=role.id, resource_name=role.name, old={"permissions": role.permission_keys})
    db.delete(role)
    db.commit()
