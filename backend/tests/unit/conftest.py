import os

# Unit tests never touch a database or Valkey; these values only satisfy settings validation.
os.environ.setdefault("OPSBRAIN_DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("OPSBRAIN_REDIS_URL", "redis://127.0.0.1:1/0")
os.environ.setdefault("OPSBRAIN_SECRET_KEY", "unit-test-secret-key-0123456789abcdef")
os.environ.setdefault("OPSBRAIN_ENV", "test")
