"""Integration tests run the real API against real PostgreSQL and Valkey.

Start them with `scripts/dev/test-services.sh up` (or the CI service containers). Connection settings:
  OPSBRAIN_TEST_PG_URL     superuser URL, default postgresql+asyncpg://postgres:opsbrain-test@127.0.0.1:55432/postgres
  OPSBRAIN_TEST_REDIS_URL  default redis://:opsbrain-test@127.0.0.1:56379/15
If the services are unreachable the tests are skipped, unless OPSBRAIN_REQUIRE_INTEGRATION=1 (CI), where they fail.
"""

import asyncio
import os
import secrets
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pyotp
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

PG_URL = os.environ.get("OPSBRAIN_TEST_PG_URL",
                        "postgresql+asyncpg://postgres:opsbrain-test@127.0.0.1:55432/postgres")
REDIS_URL = os.environ.get("OPSBRAIN_TEST_REDIS_URL", "redis://:opsbrain-test@127.0.0.1:56379/15")
APP_ROLE, APP_PW = "opsbrain_app", "app-test-password-1"
DB_NAME = f"opsbrain_test_{secrets.token_hex(4)}"
BACKEND = Path(__file__).resolve().parents[2]


def _url_for(db: str, user: str | None = None, pw: str | None = None) -> str:
    base, _, _ = PG_URL.rpartition("/")
    if user:
        scheme, rest = base.split("://", 1)
        hostpart = rest.split("@", 1)[1]
        base = f"{scheme}://{user}:{pw}@{hostpart}"
    return f"{base}/{db}"


def _plain(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


os.environ.update({
    "OPSBRAIN_ENV": "test",
    "OPSBRAIN_DATABASE_URL": _url_for(DB_NAME, APP_ROLE, APP_PW),
    "OPSBRAIN_DATABASE_MIGRATION_URL": _url_for(DB_NAME),
    "OPSBRAIN_REDIS_URL": REDIS_URL,
    "OPSBRAIN_SECRET_KEY": secrets.token_urlsafe(32),
    "OPSBRAIN_LOGIN_IP_LIMIT": "100000",
    "OPSBRAIN_MODULES_FILE": str(BACKEND / "tests" / "integration" / "modules.json"),
    "OPSBRAIN_LOG_LEVEL": "WARNING",
})


async def _reachable() -> str | None:
    try:
        conn = await asyncpg.connect(_plain(PG_URL), timeout=3)
        await conn.close()
    except Exception as exc:
        return f"PostgreSQL not reachable at {PG_URL}: {exc}"
    try:
        from redis.asyncio import Redis
        r = Redis.from_url(REDIS_URL)
        await r.ping()
        await r.flushdb()
        await r.aclose()
    except Exception as exc:
        return f"Valkey not reachable at {REDIS_URL}: {exc}"
    return None


async def _create_db() -> None:
    conn = await asyncpg.connect(_plain(PG_URL))
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", APP_ROLE)
        verb = "ALTER" if exists else "CREATE"
        await conn.execute(f"{verb} ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PW}'")
        await conn.execute(f'CREATE DATABASE "{DB_NAME}"')
        await conn.execute(f'GRANT CONNECT ON DATABASE "{DB_NAME}" TO {APP_ROLE}')
    finally:
        await conn.close()


async def _drop_db() -> None:
    conn = await asyncpg.connect(_plain(PG_URL))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def database() -> object:
    problem = asyncio.run(_reachable())
    if problem:
        if os.environ.get("OPSBRAIN_REQUIRE_INTEGRATION") == "1":
            pytest.fail(problem)
        pytest.skip(problem)
    asyncio.run(_create_db())
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env=os.environ.copy())
    yield
    asyncio.run(_drop_db())


@pytest_asyncio.fixture(loop_scope="session")
async def client(database: object) -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        yield c


@pytest_asyncio.fixture(loop_scope="session")
async def owner_conn(database: object) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(_plain(_url_for(DB_NAME)))
    yield conn
    await conn.close()


class Users:
    """Creates real users directly in the database for test setup."""

    async def create(self, roles: list[str], *, password: str | None = None, mfa: bool = False,
                     must_change: bool = False) -> tuple[str, str, str | None]:
        from sqlalchemy import select

        from app.db import sessionmaker
        from app.models import Role, User
        from app.security import crypto

        username = f"u{uuid.uuid4().hex[:10]}"
        password = password or f"pw-{secrets.token_urlsafe(16)}"
        secret = pyotp.random_base32() if mfa else None
        async with sessionmaker()() as s:
            user = User(username=username, email=f"{username}@example.test", password_hash=crypto.hash_password(password),
                        must_change_password=must_change, mfa_enabled=mfa,
                        mfa_secret_enc=crypto.encrypt(secret) if secret else None)
            user.roles = list((await s.execute(select(Role).where(Role.name.in_(roles)))).scalars())
            s.add(user)
            await s.commit()
        return username, password, secret


@pytest.fixture
def users() -> Users:
    return Users()


def csrf(client: AsyncClient) -> None:
    from app.config import get_settings

    client.headers["X-CSRF-Token"] = client.cookies.get(get_settings().csrf_cookie) or ""


async def login_full(client: AsyncClient, users: Users, roles: list[str]) -> str:
    """Create a user with the given roles and complete sign-in (including MFA for privileged roles)."""
    privileged = bool({"Admin"} & set(roles))
    username, password, secret = await users.create(roles, mfa=privileged)
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    csrf(client)
    if r.json()["state"] == "mfa_required":
        r = await client.post("/api/v1/auth/mfa/verify", json={"code": pyotp.TOTP(secret).now()})
        assert r.status_code == 200, r.text
    assert r.json()["state"] == "full", r.json()
    return username
