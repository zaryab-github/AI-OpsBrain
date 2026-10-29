"""core: users, roles, sessions, audit log, settings, self-monitoring

Revision ID: 0001
Revises:
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Snapshot of the Phase 1 catalogue. Migrations are immutable history, so this is
# deliberately NOT imported from app.rbac.
PHASE1_ROLES = {
    "Admin": ("Full control of the platform", True, []),
    "DevOps": ("Operate hosts, rules, thresholds and automation", False, [
        "hosts.view", "hosts.configure", "logs.view", "metrics.view", "rules.create", "thresholds.modify",
        "automation.approve", "actions.execute", "reports.view", "settings.view", "system.view"]),
    "NOC": ("Watch logs, metrics and reports", False, ["hosts.view", "logs.view", "metrics.view", "reports.view", "system.view"]),
    "Developer": ("Read logs, metrics and reports for troubleshooting", False, ["hosts.view", "logs.view", "metrics.view", "reports.view"]),
    "Viewer": ("Read-only dashboards and reports (no log access)", False, ["hosts.view", "metrics.view", "reports.view"]),
    "Auditor": ("Read the audit log, users, roles, settings and reports", False, [
        "hosts.view", "reports.view", "audit.view", "users.view", "roles.view", "settings.view", "system.view"]),
}


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.String(255), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid, sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission", sa.String(64), primary_key=True),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("username", sa.String(32), nullable=False, unique=True),
        sa.Column("email", sa.String(254)),
        sa.Column("full_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("role_id", sa.Uuid, sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("mfa_secret_enc", sa.LargeBinary),
        sa.Column("mfa_recovery", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("mfa_last_step", sa.BigInteger),
        sa.Column("failed_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("username = lower(username)", name="ck_users_username_lower"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Uuid, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("family_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(255)),
    )
    op.create_index("ix_sessions_family", "sessions", ["family_id"])
    op.create_index("ix_sessions_user", "sessions", ["user_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid),
        sa.Column("actor_name", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(48)),
        sa.Column("resource_id", sa.String(64)),
        sa.Column("resource_name", sa.String(128)),
        sa.Column("host_id", sa.String(64)),
        sa.Column("old_value", postgresql.JSONB),
        sa.Column("new_value", postgresql.JSONB),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.CheckConstraint("result in ('success','failure','denied')", name="ck_audit_result"),
    )
    op.create_index("ix_audit_ts", "audit_log", ["ts"])
    op.create_index("ix_audit_action", "audit_log", ["action"])
    op.create_index("ix_audit_actor", "audit_log", ["actor_name"])
    # Append-only: the application can INSERT, but not UPDATE, DELETE or TRUNCATE. A deliberate,
    # audited maintenance job (retention, Phase 9) must SET LOCAL obs.audit_maintenance = 'on'.
    op.execute("""
        CREATE FUNCTION audit_log_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF current_setting('obs.audit_maintenance', true) = 'on' THEN
            RETURN COALESCE(NEW, OLD);
          END IF;
          RAISE EXCEPTION 'audit_log is append-only';
        END $$;
    """)
    op.execute("CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log "
               "FOR EACH ROW EXECUTE FUNCTION audit_log_guard()")
    op.execute("CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
               "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_guard()")

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(96), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(64)),
    )
    op.create_table(
        "selfmon_checks",
        sa.Column("name", sa.String(96), primary_key=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )

    roles = sa.table("roles", sa.column("id", sa.Uuid), sa.column("name", sa.String), sa.column("description", sa.String),
                     sa.column("is_system", sa.Boolean), sa.column("is_superuser", sa.Boolean))
    grants = sa.table("role_permissions", sa.column("role_id", sa.Uuid), sa.column("permission", sa.String))
    for name, (description, superuser, permissions) in PHASE1_ROLES.items():
        role_id = uuid.uuid4()
        op.bulk_insert(roles, [{"id": role_id, "name": name, "description": description,
                                "is_system": True, "is_superuser": superuser}])
        if permissions:
            op.bulk_insert(grants, [{"role_id": role_id, "permission": p} for p in permissions])


def downgrade() -> None:
    # Destroys all users, roles and the audit log. Never run this on a live system.
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_guard()")
    for table in ("selfmon_checks", "system_settings", "audit_log", "sessions", "users", "role_permissions", "roles"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
