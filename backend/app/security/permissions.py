"""Permission registry and the built-in roles (PDF §12: Admin, DevOps, NOC, Developer, Viewer, Auditor).

Permissions are coarse, action-oriented strings. Every API route declares the permission it needs;
the UI uses the same strings to hide navigation the user cannot use.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    key: str
    group: str
    description: str


PERMISSIONS: tuple[Permission, ...] = (
    Permission("dashboard.view", "Overview", "View the overview dashboard"),
    Permission("hosts.view", "Hosts", "View hosts, host groups and agents"),
    Permission("hosts.manage", "Hosts", "Add, configure and remove hosts; enable/disable logging or monitoring"),
    Permission("logs.view", "Logging", "Search and stream logs"),
    Permission("logs.manage", "Logging", "Manage log sources and saved searches shared with others"),
    Permission("rules.manage", "Logging", "Create and modify log rules"),
    Permission("metrics.view", "Monitoring", "View metrics, infrastructure, services and databases"),
    Permission("thresholds.manage", "Monitoring", "Modify thresholds and threshold profiles"),
    Permission("alerts.view", "Alerts", "View logging and monitoring alerts"),
    Permission("alerts.manage", "Alerts", "Acknowledge, resolve, silence, assign and escalate alerts"),
    Permission("incidents.view", "Incidents", "View incidents"),
    Permission("incidents.manage", "Incidents", "Create and update incidents"),
    Permission("ai.view", "AI / AIOps", "View AI analyses, anomalies and recommendations"),
    Permission("ai.run", "AI / AIOps", "Run AI analysis and investigations"),
    Permission("automation.view", "Automation", "View automation rules, workflows and executions"),
    Permission("automation.manage", "Automation", "Create and modify automation rules and policies"),
    Permission("automation.approve", "Automation", "Approve or reject pending remediation actions"),
    Permission("automation.execute", "Automation", "Execute remediation actions manually"),
    Permission("reports.view", "Reports", "View and download reports"),
    Permission("reports.manage", "Reports", "Create and schedule reports"),
    Permission("retention.view", "Retention", "View retention policies, archives and storage"),
    Permission("retention.manage", "Retention", "Change retention policies; archive, restore and delete data"),
    Permission("integrations.view", "Integrations", "View integrations"),
    Permission("integrations.manage", "Integrations", "Configure integrations and notification channels"),
    Permission("users.manage", "Administration", "Manage users and roles"),
    Permission("audit.view", "Administration", "View and export the audit log"),
    Permission("settings.view", "Administration", "View system settings and platform health"),
    Permission("settings.manage", "Administration", "Change system settings"),
)

ALL_PERMISSIONS: frozenset[str] = frozenset(p.key for p in PERMISSIONS)

_VIEW = [p.key for p in PERMISSIONS if p.key.endswith(".view")]

ADMIN_ROLE = "Admin"

DEFAULT_ROLES: dict[str, tuple[str, list[str]]] = {
    ADMIN_ROLE: ("Full access, including users, roles and system settings.", sorted(ALL_PERMISSIONS)),
    "DevOps": (
        "Operates the platform: hosts, rules, thresholds, automation, integrations and retention.",
        sorted(
            ALL_PERMISSIONS
            - {"users.manage", "audit.view", "settings.manage"}
        ),
    ),
    "NOC": (
        "Watches and responds: works alerts and incidents, runs AI investigations.",
        sorted(
            {
                "dashboard.view", "hosts.view", "logs.view", "metrics.view", "alerts.view",
                "alerts.manage", "incidents.view", "incidents.manage", "ai.view", "ai.run",
                "automation.view", "reports.view",
            }
        ),
    ),
    "Developer": (
        "Reads logs and metrics for their applications and runs AI log analysis.",
        sorted(
            {
                "dashboard.view", "hosts.view", "logs.view", "metrics.view", "alerts.view",
                "incidents.view", "ai.view", "ai.run", "reports.view",
            }
        ),
    ),
    "Viewer": (
        "Read-only access to operational data.",
        sorted(
            {
                "dashboard.view", "hosts.view", "logs.view", "metrics.view", "alerts.view",
                "incidents.view", "ai.view", "automation.view", "reports.view",
            }
        ),
    ),
    "Auditor": ("Read-only access to everything, including the audit log.", sorted(set(_VIEW))),
}


def validate_permissions(perms: list[str]) -> list[str]:
    unknown = sorted(set(perms) - ALL_PERMISSIONS)
    if unknown:
        raise ValueError(f"Unknown permissions: {', '.join(unknown)}")
    return sorted(set(perms))
