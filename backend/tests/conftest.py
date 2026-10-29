"""Test fixtures.

The tests need a real PostgreSQL (the audit log relies on advisory locks, JSONB and triggers).
Point ``OBS_TEST_ADMIN_URL`` at a server where the user may CREATE DATABASE, e.g.
``postgresql+psycopg://postgres@127.0.0.1:5432/postgres``. A throw-away database is created
and migrated with the real Alembic migrations, then dropped at the end of the run.
"""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ADMIN_URL = os.environ.get("OBS_TEST_ADMIN_URL")

# Environment must be fixed before the application modules read their configuration.
os.environ["OBS_ENV"] = "test"
os.environ.setdefault("OBS_JWT_SECRET", secrets.token_urlsafe(48))
os.environ.setdefault("OBS_AUDIT_HMAC_KEY", secrets.token_urlsafe(48))
os.environ.setdefault("OBS_METRICS_TOKEN", secrets.token_urlsafe(32))
if "OBS_FIELD_KEY" not in os.environ:
    from app.config import generate_fernet_key

    os.environ["OBS_FIELD_KEY"] = generate_fernet_key()

PASSWORD = "correct horse battery staple"


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    if ADMIN_URL:
        return
    skip = pytest.mark.skip(reason="set OBS_TEST_ADMIN_URL to run database tests")
    for item in items:
        if "database" in item.fixturenames:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def database():
    from alembic import command
    from alembic.config import Config as AlembicConfig

    from app import config as app_config
    from app import db as app_db

    name = f"obs_test_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(ADMIN_URL).set(database=name)
    os.environ["OBS_DATABASE_URL"] = url.render_as_string(hide_password=False)
    app_config.reset_config_cache()
    app_db.dispose_engine()
    ini = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
    cfg = AlembicConfig(ini)
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(ini), "alembic"))
    command.upgrade(cfg, "head")
    yield url
    app_db.dispose_engine()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture()
def db_clean(database):
    """Empty every mutable table before a test; built-in roles stay."""
    from app.db import get_engine
    from app.ratelimit import auth_limiter

    auth_limiter.reset()
    with get_engine().begin() as conn:
        conn.execute(text("SET LOCAL obs.audit_maintenance = 'on'"))
        conn.execute(text("TRUNCATE audit_log RESTART IDENTITY"))
        conn.execute(text("TRUNCATE sessions, users, system_settings, selfmon_checks CASCADE"))
        conn.execute(text("DELETE FROM roles WHERE NOT is_system"))
    yield


@pytest.fixture()
def db(db_clean):
    from app.db import session_factory

    with session_factory()() as session:
        yield session


@pytest.fixture()
def client(db_clean):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="https://testserver", headers={"user-agent": "pytest"}) as c:
        yield c


class Factory:
    def __init__(self, session):
        self.db = session

    def role(self, name: str):
        from sqlalchemy import select

        from app.models import Role

        return self.db.execute(select(Role).where(Role.name == name)).scalar_one()

    def user(self, username: str = "alice", role: str = "Admin", password: str = PASSWORD,
             must_change: bool = False, active: bool = True, mfa_secret: str | None = None):
        from app import security
        from app.models import User

        r = self.role(role)
        u = User(username=username, role_id=r.id, role=r, password_hash=security.hash_password(password),
                 must_change_password=must_change, is_active=active, password_changed_at=datetime.now(UTC))
        if mfa_secret:
            u.mfa_enabled = True
            u.mfa_secret_enc = security.encrypt_field(mfa_secret)
        self.db.add(u)
        self.db.commit()
        return u


@pytest.fixture()
def make(db):
    return Factory(db)


def login(client, username: str = "alice", password: str = PASSWORD):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok", body
    return {"Authorization": f"Bearer {body['access_token']}"}
