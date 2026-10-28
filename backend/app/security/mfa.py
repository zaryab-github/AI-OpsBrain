import time

import pyotp

ISSUER = "AI-OpsBrain"


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def verify(secret: str, code: str, last_counter: int | None) -> int | None:
    """Check a TOTP code, allowing one 30 s step of clock drift either way.

    Returns the matched time-step counter, or None. A counter at or below `last_counter` is rejected
    so the same code cannot be replayed within its validity window.
    """
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now_counter = int(time.time()) // totp.interval
    for counter in (now_counter - 1, now_counter, now_counter + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if pyotp.utils.strings_equal(totp.generate_otp(counter), code):
            return counter
    return None
