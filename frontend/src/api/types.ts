export type AuthStateName =
  | "full"
  | "mfa_required"
  | "mfa_enrollment_required"
  | "password_change_required";

export interface User {
  id: string;
  username: string;
  email: string;
  full_name: string;
  is_active: boolean;
  mfa_enabled: boolean;
  must_change_password: boolean;
  roles: string[];
  locked_until: string | null;
  last_login_at: string | null;
  created_at: string;
}

export interface AuthState {
  state: AuthStateName;
  user: User | null;
  permissions: string[];
  mfa_required_by_policy: boolean;
}

export interface Role {
  id: string;
  name: string;
  description: string;
  is_system: boolean;
  permissions: string[];
  user_count: number;
}

export interface Permission {
  key: string;
  group: string;
  description: string;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor_id: string | null;
  actor_name: string;
  actor_ip: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  host_id: string | null;
  old_value: unknown;
  new_value: unknown;
  result: "success" | "failure" | "denied";
  detail: string;
  hash: string;
}

export interface AuditPage {
  items: AuditEntry[];
  next_before_id: number | null;
}

export interface SettingItem {
  key: string;
  group: string;
  label: string;
  description: string;
  type: "int" | "bool" | "str" | "enum";
  value: unknown;
  default: unknown;
  minimum: number | null;
  maximum: number | null;
  choices: string[];
}

export interface ModuleInfo {
  key: string;
  name: string;
  description: string;
  installed: boolean;
  info: Record<string, unknown> | null;
}

export interface HealthCheck {
  component: string;
  status: "ok" | "warning" | "critical" | "unknown";
  message: string;
  detail: Record<string, unknown> | null;
}

export interface SessionInfo {
  id: string;
  ip: string | null;
  user_agent: string;
  created_at: string;
  last_seen_at: string;
  current: boolean;
}
