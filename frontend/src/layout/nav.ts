import {
  Activity,
  Archive,
  Bot,
  Cable,
  FileBarChart,
  LayoutDashboard,
  type LucideIcon,
  ScrollText,
  Server,
  Settings2,
  Siren,
  Workflow,
} from "lucide-react";

/** Navigation from the architecture document §13. `phase` marks pages whose backend is not built yet. */
export interface NavItem {
  label: string;
  path: string;
  permission: string;
  phase?: number;
}

export interface NavSection {
  key: string;
  label: string;
  icon: LucideIcon;
  /** Server module that must be installed for this section to work. */
  module?: string;
  /** Logging and Monitoring are independent workspaces that can open in their own window. */
  workspace?: boolean;
  items: NavItem[];
}

export const NAV: NavSection[] = [
  {
    key: "overview",
    label: "Overview",
    icon: LayoutDashboard,
    items: [{ label: "Overview", path: "/", permission: "dashboard.view" }],
  },
  {
    key: "hosts",
    label: "Host Management",
    icon: Server,
    items: [
      { label: "Hosts", path: "/hosts", permission: "hosts.view", phase: 2 },
      { label: "Add Host", path: "/hosts/new", permission: "hosts.manage", phase: 2 },
      { label: "Host Groups", path: "/hosts/groups", permission: "hosts.view", phase: 2 },
      { label: "Agents", path: "/hosts/agents", permission: "hosts.view", phase: 2 },
    ],
  },
  {
    key: "logging",
    label: "Logging",
    icon: ScrollText,
    module: "logging",
    workspace: true,
    items: [
      { label: "Logging Dashboard", path: "/logging", permission: "logs.view", phase: 3 },
      { label: "Hosts", path: "/logging/hosts", permission: "logs.view", phase: 3 },
      { label: "Applications", path: "/logging/applications", permission: "logs.view", phase: 3 },
      { label: "Log Sources", path: "/logging/sources", permission: "logs.view", phase: 3 },
      { label: "Live Logs", path: "/logging/live", permission: "logs.view", phase: 3 },
      { label: "Log Explorer", path: "/logging/explorer", permission: "logs.view", phase: 3 },
      { label: "Log Patterns", path: "/logging/patterns", permission: "logs.view", phase: 3 },
      { label: "Log Rules", path: "/logging/rules", permission: "logs.view", phase: 5 },
      { label: "Log Alerts", path: "/logging/alerts", permission: "alerts.view", phase: 5 },
      { label: "AI Log Analysis", path: "/logging/ai", permission: "ai.view", phase: 6 },
      { label: "Logging Reports", path: "/logging/reports", permission: "reports.view", phase: 8 },
      { label: "Logging Retention", path: "/logging/retention", permission: "retention.view", phase: 9 },
    ],
  },
  {
    key: "monitoring",
    label: "Monitoring",
    icon: Activity,
    module: "monitoring",
    workspace: true,
    items: [
      { label: "Monitoring Dashboard", path: "/monitoring", permission: "metrics.view", phase: 4 },
      { label: "Hosts", path: "/monitoring/hosts", permission: "metrics.view", phase: 4 },
      { label: "Infrastructure", path: "/monitoring/infrastructure", permission: "metrics.view", phase: 4 },
      { label: "Applications", path: "/monitoring/applications", permission: "metrics.view", phase: 4 },
      { label: "Services", path: "/monitoring/services", permission: "metrics.view", phase: 4 },
      { label: "Databases", path: "/monitoring/databases", permission: "metrics.view", phase: 4 },
      { label: "Metrics", path: "/monitoring/metrics", permission: "metrics.view", phase: 4 },
      { label: "Thresholds", path: "/monitoring/thresholds", permission: "metrics.view", phase: 5 },
      { label: "Monitoring Alerts", path: "/monitoring/alerts", permission: "alerts.view", phase: 5 },
      { label: "AI Monitoring Analysis", path: "/monitoring/ai", permission: "ai.view", phase: 6 },
      { label: "Monitoring Reports", path: "/monitoring/reports", permission: "reports.view", phase: 8 },
      { label: "Monitoring Retention", path: "/monitoring/retention", permission: "retention.view", phase: 9 },
    ],
  },
  {
    key: "ai",
    label: "AI / AIOps",
    icon: Bot,
    module: "ai",
    items: [
      { label: "AI Dashboard", path: "/ai", permission: "ai.view", phase: 6 },
      { label: "Anomaly Detection", path: "/ai/anomalies", permission: "ai.view", phase: 6 },
      { label: "Root Cause Analysis", path: "/ai/rca", permission: "ai.view", phase: 6 },
      { label: "Risk Classification", path: "/ai/risk", permission: "ai.view", phase: 6 },
      { label: "Recommendations", path: "/ai/recommendations", permission: "ai.view", phase: 6 },
      { label: "AI Reports", path: "/ai/reports", permission: "reports.view", phase: 8 },
    ],
  },
  {
    key: "automation",
    label: "Automation",
    icon: Workflow,
    module: "automation",
    items: [
      { label: "Pending Approvals", path: "/automation/approvals", permission: "automation.view", phase: 7 },
      { label: "Automation Rules", path: "/automation/rules", permission: "automation.view", phase: 7 },
      { label: "n8n Workflows", path: "/automation/workflows", permission: "automation.view", phase: 7 },
      { label: "Executions", path: "/automation/executions", permission: "automation.view", phase: 7 },
      { label: "Action History", path: "/automation/history", permission: "automation.view", phase: 7 },
    ],
  },
  {
    key: "incidents",
    label: "Incidents",
    icon: Siren,
    items: [{ label: "Incidents", path: "/incidents", permission: "incidents.view", phase: 7 }],
  },
  {
    key: "reports",
    label: "Reports",
    icon: FileBarChart,
    items: [
      { label: "Logging Reports", path: "/reports/logging", permission: "reports.view", phase: 8 },
      { label: "Monitoring Reports", path: "/reports/monitoring", permission: "reports.view", phase: 8 },
      { label: "Alert Reports", path: "/reports/alerts", permission: "reports.view", phase: 8 },
      { label: "Incident Reports", path: "/reports/incidents", permission: "reports.view", phase: 8 },
      { label: "AI Reports", path: "/reports/ai", permission: "reports.view", phase: 8 },
      { label: "Scheduled Reports", path: "/reports/scheduled", permission: "reports.view", phase: 8 },
    ],
  },
  {
    key: "retention",
    label: "Retention & Archive",
    icon: Archive,
    items: [{ label: "Retention & Archive", path: "/retention", permission: "retention.view", phase: 9 }],
  },
  {
    key: "integrations",
    label: "Integrations",
    icon: Cable,
    items: [{ label: "Integrations", path: "/integrations", permission: "integrations.view", phase: 9 }],
  },
  {
    key: "admin",
    label: "Administration",
    icon: Settings2,
    items: [
      { label: "Users", path: "/admin/users", permission: "users.manage" },
      { label: "Roles & RBAC", path: "/admin/roles", permission: "users.manage" },
      { label: "Audit Logs", path: "/admin/audit", permission: "audit.view" },
      { label: "System Settings", path: "/admin/settings", permission: "settings.view" },
    ],
  },
];

export function findNav(path: string): { section: NavSection; item: NavItem } | null {
  for (const section of NAV) {
    for (const item of section.items) {
      if (item.path === path) return { section, item };
    }
  }
  return null;
}
