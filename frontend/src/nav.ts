import { Activity, ClipboardList, Home, Settings, ShieldCheck, Users, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Any one of these permissions makes the item visible. Empty = always visible. */
  anyOf: string[];
}

export interface NavSection {
  title: string | null;
  items: NavItem[];
}

/**
 * Only pages that exist are listed here. As each module (Hosts, Logging, Monitoring, ...) is
 * delivered, its pages are added to this list; nothing is shown for features that are not built.
 */
export const NAVIGATION: NavSection[] = [
  { title: null, items: [{ to: "/", label: "Overview", icon: Home, anyOf: [] }] },
  {
    title: "Administration",
    items: [
      { to: "/admin/users", label: "Users", icon: Users, anyOf: ["users.view", "users.manage"] },
      { to: "/admin/roles", label: "Roles & RBAC", icon: ShieldCheck, anyOf: ["roles.view", "roles.manage"] },
      { to: "/admin/audit", label: "Audit Logs", icon: ClipboardList, anyOf: ["audit.view"] },
      { to: "/admin/settings", label: "System Settings", icon: Settings, anyOf: ["settings.view", "settings.manage", "system.view"] },
    ],
  },
];

export const BRAND_ICON = Activity;

export function visibleSections(can: (p: string) => boolean): NavSection[] {
  return NAVIGATION.map((s) => ({
    ...s,
    items: s.items.filter((i) => i.anyOf.length === 0 || i.anyOf.some(can)),
  })).filter((s) => s.items.length > 0);
}
