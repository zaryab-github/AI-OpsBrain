"""Password hashing, tokens, TOTP and field encryption."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_config

# ---------------------------------------------------------------- passwords

_hasher = PasswordHasher()  # argon2id, RFC 9106 low-memory profile (t=3, m=64 MiB, p=4)
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-checks")

# A deliberately short list: the real defence is the length requirement plus the lockout.
_COMMON = frozenset(
    """password passw0rd p@ssw0rd p@ssword 123456789012 1234567890123 qwertyuiop12 qwerty123456
    administrator admin123456 welcome12345 letmein12345 changeme1234 iloveyou1234 monkey123456
    password1234 password12345 password123456 qwertyuiopas 111111111111 000000000000
    abc123456789 trustno1trustno1 correcthorsebattery""".split()
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-ish time: verifies against a dummy hash when the user does not exist."""
    target = password_hash or _DUMMY_HASH
    try:
        ok = _hasher.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, username: str, min_length: int) -> list[str]:
    problems: list[str] = []
    if len(password) < min_length:
        problems.append(f"must be at least {min_length} characters")
    if len(password) > 256:
        problems.append("must be at most 256 characters")
    lowered = password.lower()
    if username and username.lower() in lowered:
        problems.append("must not contain the username")
    if lowered in _COMMON or len(set(password)) < 5:
        problems.append("is too common or too repetitive")
    return problems


def generate_password(length: int = 20) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------- tokens


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, sha256_hex(raw)


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID


def issue_access_token(user_id: uuid.UUID, session_id: uuid.UUID, minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, get_config().jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> AccessClaims:
    """Raises jwt.ExpiredSignatureError / jwt.InvalidTokenError."""
    data = jwt.decode(
        token,
        get_config().jwt_secret,
        algorithms=["HS256"],
        options={"require": ["exp", "sub", "sid", "typ"]},
    )
    if data.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return AccessClaims(uuid.UUID(data["sub"]), uuid.UUID(data["sid"]))


def issue_mfa_token(user_id: uuid.UUID, minutes: int = 5) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "typ": "mfa", "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(payload, get_config().jwt_secret, algorithm="HS256")


def decode_mfa_token(token: str) -> uuid.UUID:
    data = jwt.decode(
        token, get_config().jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub", "typ"]}
    )
    if data.get("typ") != "mfa":
        raise jwt.InvalidTokenError("wrong token type")
    return uuid.UUID(data["sub"])


# ---------------------------------------------------------------- field encryption (TOTP secrets)


def _fernet() -> Fernet:
    return Fernet(get_config().field_key.encode())


def encrypt_field(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode())


def decrypt_field(blob: bytes) -> str | None:
    try:
        return _fernet().decrypt(blob).decode()
    except InvalidToken:
        return None


# ---------------------------------------------------------------- TOTP + recovery codes

TOTP_INTERVAL = 30


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def check_totp(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """Return the matched time step (to store against replay), or None when the code is wrong.

    Accepts the previous, current and next 30-second window (clock drift), and refuses a
    step that was already used.
    """
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL)
    ts = now if now is not None else datetime.now(UTC).timestamp()
    base_step = int(ts // TOTP_INTERVAL)
    for step in (base_step - 1, base_step, base_step + 1):
        if last_step is not None and step <= last_step:
            continue
        expected = totp.at(step * TOTP_INTERVAL)
        if hmac.compare_digest(expected, code):
            return step
    return None


_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_recovery_codes(count: int = 10) -> list[str]:
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    normalized = code.strip().upper().replace("-", "").replace(" ", "")
    key = get_config().field_key.encode()
    return hmac.new(key, normalized.encode(), hashlib.sha256).hexdigest()
