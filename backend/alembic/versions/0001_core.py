"""Core schema: users, roles, sessions, settings, append-only audit log.

Revision ID: 0001_core
Revises:
Create Date: 2026-10-28
"""
import os
import re
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op
from app.security.permissions import DEFAULT_ROLES

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("OPSBRAIN_DB_APP_ROLE", "opsbrain_app")
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", APP_ROLE):
    raise ValueError("OPSBRAIN_DB_APP_ROLE must be a plain lower-case identifier")


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("permissions", pg.ARRAY(sa.String(64)), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("mfa_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("mfa_secret_enc", sa.Text),
        sa.Column("mfa_last_counter", sa.Integer),
        sa.Column("failed_logins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("username = lower(username)", name="username_lowercase"),
        sa.CheckConstraint("email = lower(email)", name="email_lowercase"),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", pg.UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
    )
    op.create_table(
        "sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("mfa_pending_secret_enc", sa.Text),
        sa.Column("ip", pg.INET),
        sa.Column("user_agent", sa.String(512), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", pg.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", pg.UUID(as_uuid=True)),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_id", pg.UUID(as_uuid=True)),
        sa.Column("actor_name", sa.String(128), nullable=False),
        sa.Column("actor_ip", pg.INET),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("host_id", sa.String(128)),
        sa.Column("old_value", pg.JSONB),
        sa.Column("new_value", pg.JSONB),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.CheckConstraint("result IN ('success', 'failure', 'denied')", name="result_valid"),
    )
    for col in ("ts", "actor_id", "action", "resource_type", "host_id", "result"):
        op.create_index(f"ix_audit_log_{col}", "audit_log", [col])

    # Append-only enforcement for every role, including the owner.
    op.execute("""
        CREATE FUNCTION audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP;
        END $$;
    """)
    op.execute("CREATE TRIGGER audit_log_no_modify BEFORE UPDATE OR DELETE ON audit_log "
               "FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()")
    op.execute("CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
               "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable()")

    roles = sa.table("roles", sa.column("id", pg.UUID(as_uuid=True)), sa.column("name", sa.String),
                     sa.column("description", sa.Text), sa.column("is_system", sa.Boolean),
                     sa.column("permissions", pg.ARRAY(sa.String)))
    op.bulk_insert(roles, [
        {"id": uuid.uuid4(), "name": name, "description": desc, "is_system": True, "permissions": perms}
        for name, (desc, perms) in DEFAULT_ROLES.items()
    ])

    # Least privilege for the runtime role (created by the Postgres init script in production).
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
                REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {APP_ROLE};
                REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {APP_ROLE};
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError("The core schema cannot be downgraded; restore from backup instead.")
