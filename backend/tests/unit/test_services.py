import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services import audit, platform
from app.services.settings import DEFINITIONS


def test_redact_nested():
    value = {"username": "bob", "password": "x", "nested": {"api_key": "k", "ok": 1}, "list": [{"token": "t"}]}
    assert audit.redact(value) == {"username": "bob", "password": "***", "nested": {"api_key": "***", "ok": 1},
                                   "list": [{"token": "***"}]}


def test_hash_changes_with_content_and_prev():
    fields = {"action": "user.create", "detail": ""}
    h1 = audit.compute_hash(audit.GENESIS_HASH, fields)
    assert h1 == audit.compute_hash(audit.GENESIS_HASH, dict(reversed(list(fields.items()))))
    assert h1 != audit.compute_hash(audit.GENESIS_HASH, {**fields, "detail": "x"})
    assert h1 != audit.compute_hash("1" * 64, fields)


@pytest.mark.parametrize(
    ("key", "good", "bad"),
    [
        ("security.password_min_length", 14, 4),
        ("security.mfa_required", "all", "sometimes"),
        ("security.session_idle_minutes", 60, True),
        ("general.platform_name", "Ops Central", "   "),
    ],
)
def test_setting_validation(key, good, bad):
    d = DEFINITIONS[key]
    assert d.validate(good) == good
    with pytest.raises(ValueError):
        d.validate(bad)


def test_installed_modules_reads_file(tmp_path, monkeypatch):
    f = tmp_path / "modules.json"
    f.write_text(json.dumps({"modules": {"core": {"version": "0.1.0"}, "bogus": {}}}))
    monkeypatch.setattr(platform.get_settings(), "modules_file", f)
    assert platform.installed_modules() == {"core": {"version": "0.1.0"}}
    f.write_text("{not json")
    assert platform.installed_modules() == {}
    f.unlink()
    assert platform.installed_modules() == {}


def test_backup_check_states(tmp_path, monkeypatch):
    f = tmp_path / "status.json"
    monkeypatch.setattr(platform.get_settings(), "backup_status_file", f)
    assert platform._backup().status == "warning"
    now = datetime.now(UTC)
    f.write_text(json.dumps({"last_result": "success", "last_success": now.isoformat()}))
    assert platform._backup().status == "ok"
    f.write_text(json.dumps({"last_result": "success", "last_success": (now - timedelta(hours=50)).isoformat()}))
    assert platform._backup().status == "warning"
    f.write_text(json.dumps({"last_result": "failure", "last_error": "disk full"}))
    check = platform._backup()
    assert check.status == "critical" and "disk full" in check.message


def test_tls_check(tmp_path, monkeypatch):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "opsbrain.test")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + timedelta(days=5)).sign(key, hashes.SHA256()))
    f = tmp_path / "server.crt"
    f.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setattr(platform.get_settings(), "tls_cert_file", f)
    check = platform._tls()
    assert check.status == "critical"
    assert "expires in 4 days" in check.message or "expires in 5 days" in check.message


@pytest.mark.parametrize("addr", ["alice@corp.local", "Bob.Smith@Example.TEST", "ops+alerts@opsbrain.internal",
                                  "x@sub.domain.example.com"])
def test_email_accepts_internal_domains(addr):
    from app.api.schemas import _check_email
    assert _check_email(addr) == addr.lower()


@pytest.mark.parametrize("addr", ["bad@", "@corp.local", "no-at-sign", "a@b", "a b@corp.local", "a@-corp.local",
                                  "a@corp..local", "x" * 65 + "@corp.local"])
def test_email_rejects_malformed(addr):
    from app.api.schemas import _check_email
    with pytest.raises(ValueError):
        _check_email(addr)
