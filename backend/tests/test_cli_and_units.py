from __future__ import annotations

import io
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import cli, security
from app.models import AuditLog, User

from tests.conftest import PASSWORD


def run_cli(monkeypatch, capsys, argv, stdin=""):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.mark.usefixtures("db_clean")
class TestCli:
    def test_has_users_reflects_the_table(self, monkeypatch, capsys, make):
        assert run_cli(monkeypatch, capsys, ["has-users"])[0] == 1
        make.user("alice")
        assert run_cli(monkeypatch, capsys, ["has-users"])[0] == 0

    def test_create_admin_reads_the_password_from_stdin(self, monkeypatch, capsys, db):
        code, out, _ = run_cli(monkeypatch, capsys, ["create-admin", "--username", "Root", "--password-stdin"], PASSWORD + "\n")
        assert code == 0 and PASSWORD not in out
        user = db.execute(select(User).where(User.username == "root")).scalar_one()
        assert user.role.name == "Admin" and user.must_change_password is False
        assert security.verify_password(user.password_hash, PASSWORD)
        row = db.execute(select(AuditLog).where(AuditLog.action == "user.create")).scalar_one()
        assert row.actor_name.startswith("cli:") and PASSWORD not in str(row.new_value)

    def test_generated_password_is_shown_once_and_must_be_changed(self, monkeypatch, capsys, db):
        code, out, _ = run_cli(monkeypatch, capsys, ["create-admin", "--username", "root", "--generate"])
        assert code == 0 and "ONE-TIME PASSWORD" in out
        password = out.split("changed at first sign-in): ")[1].strip()
        user = db.execute(select(User).where(User.username == "root")).scalar_one()
        assert user.must_change_password is True and security.verify_password(user.password_hash, password)

    def test_weak_or_duplicate_admin_is_refused(self, monkeypatch, capsys, make):
        assert run_cli(monkeypatch, capsys, ["create-admin", "--username", "root", "--password-stdin"], "short\n")[0] == 1
        make.user("root")
        code, _, err = run_cli(monkeypatch, capsys, ["create-admin", "--username", "root", "--password-stdin"], PASSWORD + "\n")
        assert code == 1 and "already exists" in err

    def test_reset_password_unlock_and_disable_mfa(self, monkeypatch, capsys, make, db):
        import pyotp
        user = make.user("alice", mfa_secret=pyotp.random_base32())
        user = db.get(User, user.id)
        user.locked_until = datetime(2999, 1, 1, tzinfo=UTC)
        db.commit()
        assert run_cli(monkeypatch, capsys, ["unlock", "--username", "alice"])[0] == 0
        assert run_cli(monkeypatch, capsys, ["disable-mfa", "--username", "alice"])[0] == 0
        assert run_cli(monkeypatch, capsys, ["reset-password", "--username", "alice", "--password-stdin"], "a brand new long passphrase\n")[0] == 0
        db.expire_all()
        user = db.get(User, user.id)
        assert user.locked_until is None and not user.mfa_enabled and user.must_change_password
        actions = {a for (a,) in db.execute(select(AuditLog.action)).all()}
        assert {"user.unlock", "user.reset_mfa", "user.reset_password"} <= actions

    def test_verify_audit_exit_codes(self, monkeypatch, capsys, make):
        from sqlalchemy import text

        from app.db import get_engine
        make.user("alice")
        run_cli(monkeypatch, capsys, ["unlock", "--username", "alice"])
        assert run_cli(monkeypatch, capsys, ["verify-audit"])[0] == 0
        with get_engine().begin() as conn:
            conn.execute(text("SET LOCAL obs.audit_maintenance = 'on'"))
            conn.execute(text("UPDATE audit_log SET result = 'failure' WHERE id = 1"))
        code, _, err = run_cli(monkeypatch, capsys, ["verify-audit"])
        assert code == 2 and "TAMPERING" in err

    def test_selfmon_report_stores_watchdog_checks(self, monkeypatch, capsys, db):
        from app.models import SelfmonCheck
        tsv = "container.api\tok\trunning/healthy\nbackup.recent\twarn\tno backup yet\nbad line\n"
        assert run_cli(monkeypatch, capsys, ["selfmon-report", "--source", "watchdog"], tsv)[0] == 0
        rows = {r.name: r for r in db.execute(select(SelfmonCheck)).scalars()}
        assert set(rows) == {"container.api", "backup.recent"} and rows["backup.recent"].source == "watchdog"
        assert run_cli(monkeypatch, capsys, ["selfmon-report", "--source", "watchdog"], "garbage\n")[0] == 1


class TestSecurityUnits:
    def test_password_hashing_is_argon2id_and_salted(self):
        a, b = security.hash_password("x" * 14), security.hash_password("x" * 14)
        assert a.startswith("$argon2id$") and a != b
        assert security.verify_password(a, "x" * 14) and not security.verify_password(a, "y" * 14)

    def test_missing_user_never_verifies(self):
        assert security.verify_password(None, "dummy-password-for-constant-time-checks") is False

    def test_password_problems(self):
        assert security.password_problems("a long enough passphrase", "bob", 12) == []
        assert security.password_problems("short", "bob", 12)
        assert any("username" in p for p in security.password_problems("bob-is-my-name-1", "bob", 12))

    def test_generated_passwords_are_long_and_distinct(self):
        values = {security.generate_password() for _ in range(50)}
        assert len(values) == 50 and all(len(v) == 20 for v in values)

    def test_totp_accepts_neighbour_windows_and_rejects_replay(self):
        import pyotp
        secret = pyotp.random_base32()
        now = datetime.now(UTC).timestamp()
        step = int(now // 30)
        code = pyotp.TOTP(secret).at(step * 30)
        assert security.check_totp(secret, code, None, now) == step
        assert security.check_totp(secret, code, step, now) is None
        assert security.check_totp(secret, pyotp.TOTP(secret).at((step - 1) * 30), None, now) == step - 1
        assert security.check_totp(secret, pyotp.TOTP(secret).at((step - 3) * 30), None, now) is None
        assert security.check_totp(secret, "abcdef", None, now) is None

    def test_recovery_codes_format_and_hash_normalisation(self):
        codes = security.generate_recovery_codes()
        assert len(codes) == len(set(codes)) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
        assert security.hash_recovery_code(codes[0]) == security.hash_recovery_code(codes[0].lower().replace("-", " "))

    def test_field_encryption_roundtrip_and_tamper(self):
        blob = security.encrypt_field("JBSWY3DPEHPK3PXP")
        assert b"JBSWY3DPEHPK3PXP" not in blob and security.decrypt_field(blob) == "JBSWY3DPEHPK3PXP"
        assert security.decrypt_field(blob[:-3] + b"xxx") is None


class TestConfigValidation:
    def _env(self, monkeypatch, **overrides):
        from app.config import generate_fernet_key
        base = {"OBS_ENV": "production", "OBS_JWT_SECRET": "j" * 40, "OBS_AUDIT_HMAC_KEY": "a" * 40,
                "OBS_METRICS_TOKEN": "m" * 40, "OBS_FIELD_KEY": generate_fernet_key(), "OBS_DB_PASSWORD": "pw",
                "OBS_DATABASE_URL": ""}
        base.update(overrides)
        for k in list(os.environ):
            if k.startswith("OBS_") and k not in base:
                monkeypatch.delenv(k, raising=False)
        for k, v in base.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)

    def test_production_refuses_weak_or_missing_or_reused_secrets(self, monkeypatch):
        from app.config import ConfigError, load_config
        self._env(monkeypatch, OBS_JWT_SECRET="short")
        with pytest.raises(ConfigError, match="shorter"):
            load_config()
        self._env(monkeypatch, OBS_JWT_SECRET=None)
        with pytest.raises(ConfigError, match="missing secret"):
            load_config()
        self._env(monkeypatch, OBS_AUDIT_HMAC_KEY="j" * 40)
        with pytest.raises(ConfigError, match="different"):
            load_config()
        self._env(monkeypatch, OBS_FIELD_KEY="not-a-fernet-key")
        with pytest.raises(ConfigError, match="Fernet"):
            load_config()

    def test_secrets_can_come_from_files(self, monkeypatch, tmp_path):
        from app.config import load_config
        self._env(monkeypatch, OBS_JWT_SECRET=None)
        f = tmp_path / "jwt"
        f.write_text("f" * 48 + "\n")
        monkeypatch.setenv("OBS_JWT_SECRET_FILE", str(f))
        cfg = load_config()
        assert cfg.jwt_secret == "f" * 48 and cfg.cookie_secure is True
