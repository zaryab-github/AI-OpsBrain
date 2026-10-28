from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. Everything comes from the environment (written by opsbrainctl)."""

    model_config = SettingsConfigDict(env_prefix="OPSBRAIN_", extra="ignore")

    env: Literal["production", "development", "test"] = "production"
    public_url: str = "https://localhost"

    # Runtime role: SELECT/INSERT/UPDATE/DELETE only, cannot alter or erase the audit log.
    database_url: SecretStr
    # Owner role: used only by migrations and maintenance commands.
    database_migration_url: SecretStr | None = None
    redis_url: SecretStr

    # 32+ random bytes, base64. Used to encrypt secrets stored in the database (MFA seeds, API keys).
    secret_key: SecretStr

    # __Host- prefix: browser enforces Secure, Path=/ and no Domain attribute.
    session_cookie: str = "__Host-opsbrain_session"
    csrf_cookie: str = "__Host-opsbrain_csrf"

    modules_file: Path = Path("/etc/opsbrain/modules.json")
    backup_status_file: Path = Path("/var/lib/opsbrain/backup/status.json")
    tls_cert_file: Path = Path("/etc/opsbrain/tls/server.crt")

    login_ip_limit: int = Field(default=30, description="Login attempts allowed per IP per window")
    login_ip_window_seconds: int = 300

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
