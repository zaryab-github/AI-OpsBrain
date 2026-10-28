"""Administrative commands run inside the API container by opsbrainctl.

    opsbrain-admin create-admin --username NAME --email EMAIL   (password read from stdin)
    opsbrain-admin verify-audit
    opsbrain-admin user-count
"""

import argparse
import asyncio
import re
import sys

from sqlalchemy import func, select

from app.api.schemas import _check_email
from app.db import dispose_engine, sessionmaker
from app.models import Role, User
from app.security import crypto
from app.security.passwords import check_password_policy
from app.security.permissions import ADMIN_ROLE
from app.services import audit
from app.services import settings as settings_svc


async def create_admin(username: str, email: str, password: str) -> int:
    async with sessionmaker()() as db:
        username = username.strip().lower()
        try:
            email = _check_email(email)
        except ValueError:
            print(f"'{email}' is not a valid email address.", file=sys.stderr)
            return 2
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", username):
            print("Username must be 2-64 characters: letters, digits, dot, dash or underscore.", file=sys.stderr)
            return 2
        min_len = int(await settings_svc.get(db, "security.password_min_length"))
        problems = check_password_policy(password, username=username, min_length=min_len)
        if problems:
            print("Password rejected: " + " ".join(problems), file=sys.stderr)
            return 2
        exists = (await db.execute(select(User).where(
            (User.username == username) | (func.lower(User.email) == email.lower())))).scalar_one_or_none()
        if exists:
            print(f"A user with username '{username}' or that email already exists.", file=sys.stderr)
            return 3
        role = (await db.execute(select(Role).where(Role.name == ADMIN_ROLE))).scalar_one()
        user = User(username=username, email=email.lower(), full_name="", password_hash=crypto.hash_password(password))
        user.roles = [role]
        db.add(user)
        await db.flush()
        await audit.record(db, actor=audit.Actor.system("opsbrainctl"), action="user.create",
                           resource_type="user", resource_id=str(user.id),
                           new={"username": username, "email": email.lower(), "roles": [ADMIN_ROLE]},
                           detail="initial administrator created from the server console")
        await db.commit()
    print(f"Administrator '{username}' created.")
    return 0


async def verify_audit() -> int:
    async with sessionmaker()() as db:
        report = await audit.verify_chain(db)
    print(report.message)
    return 0 if report.ok else 1


async def user_count() -> int:
    async with sessionmaker()() as db:
        print((await db.execute(select(func.count()).select_from(User))).scalar_one())
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="opsbrain-admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ca = sub.add_parser("create-admin", help="Create an administrator; password is read from stdin")
    ca.add_argument("--username", required=True)
    ca.add_argument("--email", required=True)
    sub.add_parser("verify-audit", help="Verify the audit log hash chain")
    sub.add_parser("user-count", help="Print the number of users")
    args = parser.parse_args()

    async def go() -> int:
        try:
            if args.cmd == "create-admin":
                password = sys.stdin.readline().rstrip("\n")
                return await create_admin(args.username, args.email, password)
            if args.cmd == "verify-audit":
                return await verify_audit()
            return await user_count()
        finally:
            await dispose_engine()

    sys.exit(asyncio.run(go()))


if __name__ == "__main__":
    main()
