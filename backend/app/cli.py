"""Operator CLI, run inside the api image: ``python -m app.cli <command>``.

Used by ``obsctl core ...``. Passwords are read from stdin, never from arguments, so they do
not appear in process listings or shell history. Every action is written to the audit log.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy import func, select

from app import audit, security, sessions
from app import selfmon as selfmon_mod
from app import settings_registry as cfg
from app.db import session_factory
from app.models import Role, User

ACTOR = f"cli:{getpass.getuser() if sys.platform != 'win32' else 'operator'}"


def _read_password(args: argparse.Namespace) -> tuple[str, bool]:
    """Return (password, generated)."""
    if args.generate:
        return security.generate_password(), True
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise SystemExit("error: no password supplied on stdin")
        return password, False
    raise SystemExit("error: use --password-stdin or --generate")


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def cmd_has_users(_: argparse.Namespace) -> int:
    with session_factory()() as db:
        count = db.execute(select(func.count()).select_from(User)).scalar_one()
    return 0 if count else 1


def cmd_create_admin(args: argparse.Namespace) -> int:
    password, generated = _read_password(args)
    username = args.username.strip().lower()
    with session_factory()() as db:
        if db.execute(select(User.id).where(User.username == username)).first():
            return _fail(f"user '{username}' already exists")
        role = db.execute(select(Role).where(Role.name == "Admin")).scalar_one_or_none()
        if role is None:
            return _fail("the Admin role is missing: run the database migrations first")
        problems = security.password_problems(password, username, int(cfg.get(db, "security.password_min_length")))
        if problems:
            return _fail("the password " + "; ".join(problems))
        user = User(
            username=username, full_name=args.full_name or "", role_id=role.id, role=role,
            password_hash=security.hash_password(password), must_change_password=generated,
            password_changed_at=datetime.now(UTC),
        )
        db.add(user)
        db.flush()
        audit.record(db, action="user.create", actor_name=ACTOR, resource_type="user", resource_id=user.id,
                     resource_name=username, new={"username": username, "role": "Admin"}, detail="created with obsctl")
        db.commit()
    print(f"created administrator '{username}'")
    if generated:
        print(f"ONE-TIME PASSWORD (shown once, must be changed at first sign-in): {password}")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    password, generated = _read_password(args)
    username = args.username.strip().lower()
    with session_factory()() as db:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user is None:
            return _fail(f"no such user '{username}'")
        problems = security.password_problems(password, username, int(cfg.get(db, "security.password_min_length")))
        if problems:
            return _fail("the password " + "; ".join(problems))
        user.password_hash = security.hash_password(password)
        user.must_change_password = True
        user.failed_attempts = 0
        user.locked_until = None
        sessions.revoke_user_sessions(db, user.id)
        audit.record(db, action="user.reset_password", actor_name=ACTOR, resource_type="user", resource_id=user.id,
                     resource_name=username, detail="reset with obsctl; all sessions ended")
        db.commit()
    print(f"password for '{username}' reset; it must be changed at next sign-in")
    if generated:
        print(f"ONE-TIME PASSWORD (shown once): {password}")
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    with session_factory()() as db:
        user = db.execute(select(User).where(User.username == args.username.strip().lower())).scalar_one_or_none()
        if user is None:
            return _fail("no such user")
        user.failed_attempts = 0
        user.locked_until = None
        audit.record(db, action="user.unlock", actor_name=ACTOR, resource_type="user", resource_id=user.id,
                     resource_name=user.username, detail="unlocked with obsctl")
        db.commit()
    print("unlocked")
    return 0


def cmd_disable_mfa(args: argparse.Namespace) -> int:
    with session_factory()() as db:
        user = db.execute(select(User).where(User.username == args.username.strip().lower())).scalar_one_or_none()
        if user is None:
            return _fail("no such user")
        user.mfa_enabled = False
        user.mfa_secret_enc = None
        user.mfa_recovery = []
        user.mfa_last_step = None
        sessions.revoke_user_sessions(db, user.id)
        audit.record(db, action="user.reset_mfa", actor_name=ACTOR, resource_type="user", resource_id=user.id,
                     resource_name=user.username, detail="two-factor authentication removed with obsctl")
        db.commit()
    print("two-factor authentication removed; the user must enrol again at next sign-in if policy requires it")
    return 0


def cmd_verify_audit(_: argparse.Namespace) -> int:
    with session_factory()() as db:
        result = audit.verify_chain(db)
    if result.ok:
        print(f"audit log OK: {result.checked} entries verified")
        return 0
    print(f"AUDIT LOG TAMPERING SUSPECTED at entry {result.first_bad_id}: {result.reason}", file=sys.stderr)
    return 2


def cmd_list_users(_: argparse.Namespace) -> int:
    with session_factory()() as db:
        for u in db.execute(select(User).order_by(User.username)).scalars():
            flags = ("active" if u.is_active else "disabled") + (", mfa" if u.mfa_enabled else "")
            print(f"{u.username:<24} {u.role.name:<10} {flags}")
    return 0


def cmd_selfmon_report(args: argparse.Namespace) -> int:
    """Read TSV lines (name<TAB>status<TAB>detail) from stdin and store them."""
    results = []
    for line in sys.stdin:
        parts = line.rstrip("\n").split("\t", 2)
        if len(parts) != 3 or parts[1] not in {"ok", "warn", "crit"}:
            continue
        results.append(selfmon_mod.Result(parts[0][:96], parts[1], parts[2]))
    if not results:
        return _fail("no valid check lines on stdin")
    with session_factory()() as db:
        selfmon_mod.store(db, args.source, results)
        db.commit()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("has-users").set_defaults(func=cmd_has_users)
    sub.add_parser("verify-audit").set_defaults(func=cmd_verify_audit)
    sub.add_parser("list-users").set_defaults(func=cmd_list_users)

    for name, func in (("create-admin", cmd_create_admin), ("reset-password", cmd_reset_password)):
        p = sub.add_parser(name)
        p.add_argument("--username", required=True)
        p.add_argument("--full-name", default="")
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--password-stdin", action="store_true")
        group.add_argument("--generate", action="store_true")
        p.set_defaults(func=func)

    for name, func in (("unlock", cmd_unlock), ("disable-mfa", cmd_disable_mfa)):
        p = sub.add_parser(name)
        p.add_argument("--username", required=True)
        p.set_defaults(func=func)

    p = sub.add_parser("selfmon-report")
    p.add_argument("--source", choices=["watchdog"], required=True)
    p.set_defaults(func=cmd_selfmon_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
