import base64
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from starlette.concurrency import run_in_threadpool

from app.config import get_settings

# OWASP-recommended Argon2id parameters (19 MiB, t=2, p=1) raised to 64 MiB / t=3.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
# Used to keep login timing identical for unknown usernames.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


async def hash_password_async(password: str) -> str:
    """Argon2 is deliberately slow (~0.1 s); run it off the event loop so other requests keep flowing."""
    return await run_in_threadpool(hash_password, password)


async def verify_password_async(password_hash: str | None, password: str) -> bool:
    return await run_in_threadpool(verify_password, password_hash, password)


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    raw = get_settings().secret_key.get_secret_value().encode()
    # Derive a Fernet key from the configured secret so any 32+ byte secret format works.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"opsbrain-fernet:" + raw).digest()))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt value: secret key changed or data corrupted") from exc


def generate_password(length: int = 20) -> str:
    """Random password for temporary credentials; avoids look-alike characters."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_.!@#%"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        classes = [any(c.isupper() for c in pw), any(c.islower() for c in pw), any(c.isdigit() for c in pw)]
        if all(classes):
            return pw
