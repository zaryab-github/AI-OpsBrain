"""Database engine and session handling (synchronous SQLAlchemy 2.0, psycopg 3)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_config

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        _engine = create_engine(
            get_config().database_url,
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
        )
        _factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _factory is not None
    return _factory


def dispose_engine() -> None:
    """Tests only: drop pooled connections so the database can be recreated."""
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


def get_db() -> Iterator[Session]:
    """FastAPI dependency. Handlers commit explicitly; an unhandled error rolls back."""
    with session_factory()() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
