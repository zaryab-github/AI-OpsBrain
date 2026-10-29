import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { AuditPage, Status } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Card, ErrorNote, PageHeader, Spinner, StatusBadge } from "../components/ui";
import { fmtAgo } from "../lib/format";

function PlatformHealth() {
  const status = useQuery({ queryKey: ["status"], queryFn: () => api<Status>("/system/status"), refetchInterval: 30_000 });
  if (status.isLoading) return <Spinner />;
  if (status.error) return <ErrorNote error={status.error} />;
  const s = status.data!;
  const problems = s.checks.filter((c) => c.status !== "ok");
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <StatusBadge status={s.overall} />
        <span className="text-sm text-muted">Platform version {s.version}</span>
      </div>
      {problems.length === 0 ? (
        <p className="text-sm">All {s.checks.length} self-monitoring checks are passing.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {problems.map((c) => (
            <li key={c.name} className="flex items-start gap-2">
              <StatusBadge status={c.status} />
              <span><strong>{c.name}</strong> — {c.detail}</span>
            </li>
          ))}
        </ul>
      )}
      <Link to="/admin/settings" className="inline-block text-sm text-brand underline">Open system health</Link>
    </div>
  );
}

function RecentActivity() {
  const audit = useQuery({ queryKey: ["audit", "recent"], queryFn: () => api<AuditPage>("/audit", { query: { limit: 8 } }), refetchInterval: 30_000 });
  if (audit.isLoading) return <Spinner />;
  if (audit.error) return <ErrorNote error={audit.error} />;
  return (
    <ul className="divide-y divide-line text-sm">
      {audit.data!.items.map((e) => (
        <li key={e.id} className="flex items-center justify-between gap-3 py-2">
          <span className="min-w-0 truncate"><strong>{e.actor_name}</strong> · {e.action}{e.resource_name ? ` · ${e.resource_name}` : ""}</span>
          <span className="flex shrink-0 items-center gap-2">
            {e.result !== "success" && <Badge tone={e.result === "denied" ? "warn" : "crit"}>{e.result}</Badge>}
            <span className="text-xs text-muted">{fmtAgo(e.ts)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function Overview() {
  const { me, can } = useAuth();
  return (
    <div className="space-y-5">
      <PageHeader title="Overview" subtitle={`Signed in as ${me?.user.username} (${me?.user.role.name})`} />
      <div className="grid gap-5 lg:grid-cols-2">
        {can("system.view") && <Card title="Platform health"><PlatformHealth /></Card>}
        {can("audit.view") && (
          <Card title="Recent activity" actions={<Link to="/admin/audit" className="text-sm text-brand underline">All audit logs</Link>}>
            <RecentActivity />
          </Card>
        )}
        <Card title="Infrastructure">
          <p className="text-sm text-muted">
            No infrastructure modules are installed yet. Host management, Logging and Monitoring appear here and in the menu once their modules are installed on this platform.
          </p>
        </Card>
      </div>
    </div>
  );
}
