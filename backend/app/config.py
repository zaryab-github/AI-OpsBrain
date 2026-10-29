"""Runtime configuration.

Every secret is read from a file (``OBS_<NAME>_FILE``) so that it never appears in the
container environment, ``docker inspect`` output or process listings. A plain
``OBS_<NAME>`` variable is accepted for development and tests only.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy.engine import URL

MIN_SECRET_LENGTH = 32


class ConfigError(RuntimeError):
    """Raised at start-up when the configuration is unusable. Never started half-configured."""


def _read(name: str) -> str | None:
    direct = os.environ.get(f"OBS_{name}")
    if direct:
        return direct.strip()
    path = os.environ.get(f"OBS_{name}_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"cannot read OBS_{name}_FILE={path}: {exc}") from exc
    return None


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    env: str
    version: str
    hostname: str
    database_url: URL | str
    jwt_secret: str
    field_key: str
    audit_hmac_key: bytes
    metrics_token: str
    cookie_secure: bool

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def _require(name: str, value: str | None, production: bool) -> str:
    if not value:
        raise ConfigError(f"missing secret OBS_{name}_FILE (or OBS_{name} for development)")
    if production and len(value) < MIN_SECRET_LENGTH:
        raise ConfigError(f"OBS_{name} is shorter than {MIN_SECRET_LENGTH} characters")
    return value


def load_config() -> Config:
    env = os.environ.get("OBS_ENV", "production").strip().lower()
    if env not in {"production", "development", "test"}:
        raise ConfigError("OBS_ENV must be production, development or test")
    production = env == "production"

    jwt_secret = _require("JWT_SECRET", _read("JWT_SECRET"), production)
    field_key = _require("FIELD_KEY", _read("FIELD_KEY"), False)
    audit_key = _require("AUDIT_HMAC_KEY", _read("AUDIT_HMAC_KEY"), production)
    metrics_token = _require("METRICS_TOKEN", _read("METRICS_TOKEN"), production)
    try:
        Fernet(field_key.encode())
    except (ValueError, TypeError) as exc:
        raise ConfigError("OBS_FIELD_KEY is not a valid Fernet key (32 url-safe base64 bytes)") from exc
    if len({jwt_secret, field_key, audit_key, metrics_token}) != 4:
        raise ConfigError("the application secrets must all be different from each other")

    database_url: URL | str
    explicit = os.environ.get("OBS_DATABASE_URL")
    if explicit:
        database_url = explicit
    else:
        password = _require("DB_PASSWORD", _read("DB_PASSWORD"), False)
        database_url = URL.create(
            "postgresql+psycopg",
            username=os.environ.get("OBS_DB_USER", "obs"),
            password=password,
            host=os.environ.get("OBS_DB_HOST", "postgres"),
            port=int(os.environ.get("OBS_DB_PORT", "5432")),
            database=os.environ.get("OBS_DB_NAME", "obs"),
        )

    version = os.environ.get("OBS_VERSION", "").strip() or "dev"
    return Config(
        env=env,
        version=version,
        hostname=os.environ.get("OBS_HOSTNAME", "localhost"),
        database_url=database_url,
        jwt_secret=jwt_secret,
        field_key=field_key,
        audit_hmac_key=audit_key.encode(),
        metrics_token=metrics_token,
        cookie_secure=_flag("OBS_COOKIE_SECURE", production),
    )


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()


def reset_config_cache() -> None:
    """Tests only."""
    get_config.cache_clear()


def generate_fernet_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()
