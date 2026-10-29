import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Setting, Status } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Button, Card, ErrorNote, Field, Input, PageHeader, Spinner, StatusBadge, cx } from "../components/ui";
import { fmtAgo, groupBy } from "../lib/format";

type Draft = Record<string, string | number | boolean>;

function SettingsForm({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Setting[]>("/settings") });
  const [draft, setDraft] = useState<Draft>({});
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (settings.data) setDraft(Object.fromEntries(settings.data.map((s) => [s.key, s.value])));
  }, [settings.data]);
  const changes = useMemo(() => {
    const out: Draft = {};
    settings.data?.forEach((s) => { if (draft[s.key] !== undefined && draft[s.key] !== s.value) out[s.key] = draft[s.key]!; });
    return out;
  }, [settings.data, draft]);
  const save = useMutation({
    mutationFn: () => api<Setting[]>("/settings", { method: "PATCH", body: { changes } }),
    onSuccess: (data) => { qc.setQueryData(["settings"], data); setSaved(true); void qc.invalidateQueries({ queryKey: ["status"] }); },
  });
  if (settings.isLoading) return <Spinner />;
  if (settings.error) return <ErrorNote error={settings.error} />;
  const groups = groupBy(settings.data ?? [], (s) => s.group);
  return (
    <form onSubmit={(e) => { e.preventDefault(); setSaved(false); save.mutate(); }} className="space-y-5" aria-label="Settings">
      {Object.entries(groups).map(([group, items]) => (
        <Card key={group} title={group}>
          <div className="space-y-4">
            {items.map((s) => (
              <div key={s.key}>
                {s.type === "bool" ? (
                  <label className="flex items-start gap-3 text-sm">
                    <input type="checkbox" className="mt-1" disabled={!canEdit} checked={Boolean(draft[s.key])} onChange={(e) => setDraft({ ...draft, [s.key]: e.target.checked })} />
                    <span><span className="block font-medium">{s.key}</span><span className="text-muted">{s.description}</span></span>
                  </label>
                ) : (
                  <Field label={s.key} hint={s.description + (s.minimum !== null && s.maximum !== null ? ` (${s.minimum}–${s.maximum})` : "")}>
                    {(id) => (
                      <Input
                        id={id}
                        disabled={!canEdit}
                        type={s.type === "int" ? "number" : "text"}
                        min={s.minimum ?? undefined}
                        max={s.maximum ?? undefined}
                        value={String(draft[s.key] ?? "")}
                        onChange={(e) => setDraft({ ...draft, [s.key]: s.type === "int" ? Number(e.target.value) : e.target.value })}
                        className="max-w-md"
                      />
                    )}
                  </Field>
                )}
              </div>
            ))}
          </div>
        </Card>
      ))}
      <ErrorNote error={save.error} />
      {saved && <p role="status" className="text-sm text-ok">Settings saved and recorded in the audit log.</p>}
      {canEdit && <Button type="submit" busy={save.isPending} disabled={Object.keys(changes).length === 0}>Save changes</Button>}
    </form>
  );
}

function Health() {
  const status = useQuery({ queryKey: ["status"], queryFn: () => api<Status>("/system/status"), refetchInterval: 30_000 });
  if (status.isLoading) return <Spinner />;
  if (status.error) return <ErrorNote error={status.error} />;
  const s = status.data!;
  return (
    <Card
      title="Self-monitoring"
      actions={<div className="flex items-center gap-3"><StatusBadge status={s.overall} /><Button variant="secondary" onClick={() => void status.refetch()} busy={status.isFetching}><RefreshCw className="h-4 w-4" aria-hidden />Refresh</Button></div>}
    >
      <p className="mb-3 text-sm text-muted">Version {s.version}. Checks run in the backend, the worker and the host watchdog, independently of any Monitoring module.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-muted"><tr><th className="py-2 pr-4">Check</th><th className="pr-4">Status</th><th className="pr-4">Source</th><th className="pr-4">Detail</th><th>Updated</th></tr></thead>
          <tbody>
            {s.checks.map((c) => (
              <tr key={c.name} className="border-t border-line align-top">
                <td className="py-2 pr-4 font-mono text-xs">{c.name}</td>
                <td className="pr-4"><StatusBadge status={c.status} /></td>
                <td className="pr-4">{c.source}</td>
                <td className={cx("pr-4", c.stale && "text-warn")}>{c.detail}</td>
                <td className="whitespace-nowrap">{fmtAgo(c.checked_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default function SystemSettings() {
  const { can } = useAuth();
  const tabs = [
    can("settings.view") || can("settings.manage") ? ({ id: "settings", label: "Settings" } as const) : null,
    can("system.view") ? ({ id: "health", label: "System health" } as const) : null,
  ].filter((t): t is { id: "settings" | "health"; label: string } => t !== null);
  const [tab, setTab] = useState<"settings" | "health">(tabs[0]?.id ?? "settings");
  return (
    <div>
      <PageHeader title="System Settings" subtitle="Security policy, self-monitoring and platform health." />
      <div role="tablist" aria-label="System settings" className="mb-5 flex gap-1 border-b border-line">
        {tabs.map((t) => (
          <button key={t.id} role="tab" type="button" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={cx("-mb-px border-b-2 px-4 py-2 text-sm", tab === t.id ? "border-brand font-medium text-brand" : "border-transparent text-muted hover:text-ink")}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "settings" ? <SettingsForm canEdit={can("settings.manage")} /> : <Health />}
    </div>
  );
}
