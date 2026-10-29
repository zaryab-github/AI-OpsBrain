export interface RoleRef { id: string; name: string }

export interface User {
  id: string;
  username: string;
  email: string | null;
  full_name: string;
  role: RoleRef;
  is_active: boolean;
  must_change_password: boolean;
  mfa_enabled: boolean;
  locked: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface Me {
  user: User;
  permissions: string[];
  superuser: boolean;
  password_change_required: boolean;
  mfa_enrollment_required: boolean;
  instance_name: string;
}

export interface LoginResult {
  status: "ok" | "mfa_required";
  access_token: string | null;
  expires_in: number | null;
  mfa_token: string | null;
  me: Me | null;
}

export interface TokenResult { access_token: string; expires_in: number; me: Me }

export interface Role {
  id: string;
  name: string;
  description: string;
  is_system: boolean;
  is_superuser: boolean;
  permissions: string[];
  user_count: number;
}

export interface Permission { key: string; group: string; description: string }

export interface AuditEntry {
  id: number;
  ts: string;
  actor_name: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  resource_name: string | null;
  host_id: string | null;
  old_value: unknown;
  new_value: unknown;
  result: "success" | "failure" | "denied";
  detail: string | null;
  ip: string | null;
}

export interface AuditPage { items: AuditEntry[]; next_before_id: number | null }
export interface ChainResult { ok: boolean; checked: number; first_bad_id: number | null; reason: string | null }

export interface Setting {
  key: string;
  group: string;
  description: string;
  type: "int" | "bool" | "str";
  value: string | number | boolean;
  default: string | number | boolean;
  minimum: number | null;
  maximum: number | null;
}

export interface Check {
  name: string;
  source: string;
  status: "ok" | "warn" | "crit";
  detail: string;
  checked_at: string | null;
  stale: boolean;
}

export interface Status { overall: "ok" | "warn" | "crit"; version: string; checks: Check[] }

export interface SessionInfo {
  id: string;
  created_at: string;
  last_used_at: string | null;
  ip: string | null;
  user_agent: string | null;
  current: boolean;
}
