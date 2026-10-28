import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleSlash } from "lucide-react";

import { get } from "../api/client";
import { useModules } from "../api/hooks";
import type { HealthCheck } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Card, ErrorBox, PageHeader, Spinner, statusTone } from "../components/ui";

const COMPONENT_LABELS: Record<string, string> = {
  api: "API",
  database: "Database (PostgreSQL)",
  redis: "Queue / cache (Valkey)",
  worker: "Background worker",
  audit_chain: "Audit log integrity",
  backup: "Backups",
  tls: "TLS certificate",
};

export function PlatformHealth() {
  const health = useQuery({
    queryKey: ["system", "health"],
    queryFn: () => get<{ overall: string; checks: HealthCheck[] }>("/system/health"),
    refetchInterval: 30_000,
  });
  if (health.isLoading) return <Spinner />;
  if (health.error) return <ErrorBox error={health.error} />;
  return (
    <ul className="divide-y divide-slate-100">
      {health.data!.checks.map((c) => (
        <li key={c.component} className="flex items-start justify-between gap-3 py-2">
          <div>
            <div className="text-sm font-medium">{COMPONENT_LABELS[c.component] ?? c.component}</div>
            <div className="text-xs text-slate-500">{c.message}</div>
          </div>
          <Badge tone={statusTone(c.status)}>{c.status}</Badge>
        </li>
      ))}
    </ul>
  );
}

export default function Overview() {
  const { can } = useAuth();
  const modules = useModules();
  return (
    <>
      <PageHeader
        title="Overview"
        description="Infrastructure, alert and AI summaries appear here as the Host Management, Logging, Monitoring and AI modules are added."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Platform modules">
          {modules.isLoading && <Spinner />}
          <ErrorBox error={modules.error} />
          <ul className="divide-y divide-slate-100">
            {modules.data?.modules.map((m) => (
              <li key={m.key} className="flex items-start gap-3 py-2">
                {m.installed ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" aria-label="installed" />
                ) : (
                  <CircleSlash className="mt-0.5 h-4 w-4 text-slate-400" aria-label="not installed" />
                )}
                <div className="flex-1">
                  <div className="text-sm font-medium">{m.name}</div>
                  <div className="text-xs text-slate-500">{m.description}</div>
                </div>
                <Badge tone={m.installed ? "green" : "gray"}>{m.installed ? "installed" : "not installed"}</Badge>
              </li>
            ))}
          </ul>
          {modules.data && <p className="mt-3 text-xs text-slate-500">Platform version {modules.data.version}</p>}
        </Card>
        {can("settings.view") && (
          <Card title="Platform health">
            <PlatformHealth />
          </Card>
        )}
      </div>
    </>
  );
}
