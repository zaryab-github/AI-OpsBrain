import time

import pyotp
import pytest

from app.security import crypto, mfa
from app.security.passwords import check_password_policy
from app.security.permissions import ADMIN_ROLE, ALL_PERMISSIONS, DEFAULT_ROLES, validate_permissions


def test_password_hash_roundtrip():
    h = crypto.hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert crypto.verify_password(h, "correct horse battery staple")
    assert not crypto.verify_password(h, "wrong")
    assert not crypto.verify_password(None, "anything")
    assert not crypto.verify_password("not-a-hash", "anything")


def test_encrypt_roundtrip_and_tamper():
    token = crypto.encrypt("JBSWY3DPEHPK3PXP")
    assert token != "JBSWY3DPEHPK3PXP"
    assert crypto.decrypt(token) == "JBSWY3DPEHPK3PXP"
    with pytest.raises(ValueError):
        crypto.decrypt(token[:-4] + "AAAA")


def test_token_hash_is_stable_and_not_identity():
    t = crypto.new_token()
    assert crypto.token_hash(t) == crypto.token_hash(t)
    assert crypto.token_hash(t) != t
    assert len(crypto.token_hash(t)) == 64


def test_generated_password_meets_policy():
    for _ in range(50):
        pw = crypto.generate_password()
        assert check_password_policy(pw, username="someone", min_length=12) == []


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("short", "at least 12"),
        ("alice-is-great-2026", "username"),
        ("aaaaaaaaaaaaaaaa", "repetitive"),
        ("MyPassword-for-work", "commonly guessed"),
    ],
)
def test_password_policy_rejections(password, fragment):
    problems = check_password_policy(password, username="alice", min_length=12)
    assert any(fragment in p for p in problems), problems


def test_password_policy_accepts_long_passphrase():
    assert check_password_policy("violet tram under seven bridges", username="alice", min_length=12) == []


def test_totp_verify_and_replay_protection():
    secret = mfa.new_secret()
    code = pyotp.TOTP(secret).now()
    counter = mfa.verify(secret, code, None)
    assert counter is not None
    # Same code again must be rejected once its counter has been used.
    assert mfa.verify(secret, code, counter) is None
    assert mfa.verify(secret, "000000" if code != "000000" else "111111", None) is None
    assert mfa.verify(secret, "abc123", None) is None


def test_totp_allows_one_step_drift():
    secret = mfa.new_secret()
    totp = pyotp.TOTP(secret)
    previous = totp.at(time.time() - 30)
    assert mfa.verify(secret, previous, None) is not None
    too_old = totp.at(time.time() - 120)
    assert mfa.verify(secret, too_old, None) is None


def test_provisioning_uri():
    uri = mfa.provisioning_uri("JBSWY3DPEHPK3PXP", "alice")
    assert uri.startswith("otpauth://totp/AI-OpsBrain:alice?")
    assert "issuer=AI-OpsBrain" in uri


def test_builtin_roles_match_pdf():
    assert set(DEFAULT_ROLES) == {"Admin", "DevOps", "NOC", "Developer", "Viewer", "Auditor"}
    assert set(DEFAULT_ROLES[ADMIN_ROLE][1]) == ALL_PERMISSIONS
    for name, (_, perms) in DEFAULT_ROLES.items():
        assert set(perms) <= ALL_PERMISSIONS, name
    assert "audit.view" in DEFAULT_ROLES["Auditor"][1]
    assert not any(p.endswith((".manage", ".run", ".approve", ".execute")) for p in DEFAULT_ROLES["Auditor"][1])
    assert not any(p.endswith((".manage", ".run", ".approve", ".execute")) for p in DEFAULT_ROLES["Viewer"][1])
    assert "users.manage" not in DEFAULT_ROLES["DevOps"][1]
    assert "automation.approve" in DEFAULT_ROLES["DevOps"][1]


def test_validate_permissions():
    assert validate_permissions(["logs.view", "logs.view", "metrics.view"]) == ["logs.view", "metrics.view"]
    with pytest.raises(ValueError, match="nope.view"):
        validate_permissions(["logs.view", "nope.view"])
