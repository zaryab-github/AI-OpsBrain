"""Permission catalogue and the built-in roles.

Adding a permission means: add it here AND add an Alembic migration that inserts the
grants for the built-in roles. The Admin role is a superuser and implicitly has every
permission, including ones added later.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    key: str
    group: str
    description: str


PERMISSIONS: tuple[Permission, ...] = (
    Permission("hosts.view", "Hosts", "View registered hosts and their status"),
    Permission("hosts.configure", "Hosts", "Add, edit and remove hosts; change logging/monitoring capabilities"),
    Permission("logs.view", "Logging", "View and search logs"),
    Permission("metrics.view", "Monitoring", "View metrics and dashboards"),
    Permission("rules.create", "Alerting", "Create and edit log rules and alert rules"),
    Permission("thresholds.modify", "Alerting", "Change thresholds and threshold profiles"),
    Permission("automation.approve", "Automation", "Approve or reject pending remediation actions"),
    Permission("actions.execute", "Automation", "Trigger remediation actions manually"),
    Permission("reports.view", "Reporting", "View and download reports"),
    Permission("users.view", "Administration", "List users"),
    Permission("users.manage", "Administration", "Create, edit, disable users; reset passwords and MFA"),
    Permission("roles.view", "Administration", "List roles and permissions"),
    Permission("roles.manage", "Administration", "Create, edit and delete custom roles"),
    Permission("audit.view", "Administration", "View and export the audit log"),
    Permission("settings.view", "Administration", "View system settings"),
    Permission("settings.manage", "Administration", "Change system settings"),
    Permission("system.view", "Administration", "View platform health and self-monitoring"),
)

PERMISSION_KEYS: frozenset[str] = frozenset(p.key for p in PERMISSIONS)


@dataclass(frozen=True)
class BuiltinRole:
    name: str
    description: str
    permissions: tuple[str, ...]
    superuser: bool = False


BUILTIN_ROLES: tuple[BuiltinRole, ...] = (
    BuiltinRole("Admin", "Full control of the platform", (), superuser=True),
    BuiltinRole(
        "DevOps",
        "Operate hosts, rules, thresholds and automation",
        (
            "hosts.view", "hosts.configure", "logs.view", "metrics.view", "rules.create",
            "thresholds.modify", "automation.approve", "actions.execute", "reports.view",
            "settings.view", "system.view",
        ),
    ),
    BuiltinRole("NOC", "Watch logs, metrics and reports", ("hosts.view", "logs.view", "metrics.view", "reports.view", "system.view")),
    BuiltinRole("Developer", "Read logs, metrics and reports for troubleshooting", ("hosts.view", "logs.view", "metrics.view", "reports.view")),
    BuiltinRole("Viewer", "Read-only dashboards and reports (no log access)", ("hosts.view", "metrics.view", "reports.view")),
    BuiltinRole(
        "Auditor",
        "Read the audit log, users, roles, settings and reports",
        ("hosts.view", "reports.view", "audit.view", "users.view", "roles.view", "settings.view", "system.view"),
    ),
)
