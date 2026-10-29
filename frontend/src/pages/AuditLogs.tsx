import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Download, ShieldCheck } from "lucide-react";
import { Fragment, useState, type FormEvent } from "react";
import { api, download } from "../api/client";
import type { AuditEntry, AuditPage, ChainResult } from "../api/types";
import { Badge, Button, Card, Empty, ErrorNote, Input, PageHeader, Select, Spinner } from "../components/ui";
import { fmtTime } from "../lib/format";

interface Filters { q: string; actor: string; action: string; result: string; since: string; until: string }
const EMPTY: Filters = { q: "", actor: "", action: "", result: "", since: "", until: "" };

function toQuery(f: Filters) {
  return {
    q: f.q, actor: f.actor, action: f.action, result: f.result,
    since: f.since ? new Date(f.since).toISOString() : undefined,
    until: f.until ? new Date(f.until).toISOString() : undefined,
  };
}

function Json({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-muted">—</span>;
  return <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-subtle p-2 font-mono text-xs">{JSON.stringify(value, null, 2)}</pre>;
}

export default function AuditLogs() {
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [open, setOpen] = useState<number | null>(null);
  const query = useInfiniteQuery({
    queryKey: ["audit", applied],
    queryFn: ({ pageParam }) => api<AuditPage>("/audit", { query: { ...toQuery(applied), limit: 50, before_id: pageParam } }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before_id ?? undefined,
  });
  const verify = useMutation({ mutationFn: () => api<ChainResult>("/audit/verify") });
  const exportCsv = useMutation({ mutationFn: () => download("/audit/export.csv", toQuery(applied), "audit-log.csv") });
  const items: AuditEntry[] = query.data?.pages.flatMap((p) => p.items) ?? [];
  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  function submit(e: FormEvent) { e.preventDefault(); setApplied(draft); setOpen(null); }

  return (
    <div>
      <PageHeader
        title="Audit Logs"
        subtitle="Who did what, when, to which resource, and the result. Entries are append-only and hash-chained."
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" busy={verify.isPending} onClick={() => verify.mutate()}><ShieldCheck className="h-4 w-4" aria-hidden />Verify integrity</Button>
            <Button variant="secondary" busy={exportCsv.isPending} onClick={() => exportCsv.mutate()}><Download className="h-4 w-4" aria-hidden />Export CSV</Button>
          </div>
        }
      />
      {verify.data && (
        <div role="status" className={`mb-4 rounded-md border px-3 py-2 text-sm ${verify.data.ok ? "border-ok/40 bg-ok/10 text-ok" : "border-crit/40 bg-crit/10 text-crit"}`}>
          {verify.data.ok ? `Integrity verified: ${verify.data.checked} entries, no tampering detected.` : `TAMPERING SUSPECTED at entry #${verify.data.first_bad_id}: ${verify.data.reason}`}
        </div>
      )}
      <ErrorNote error={verify.error ?? exportCsv.error} />

      <Card className="mb-5">
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Filters">
          <Input aria-label="Search" placeholder="Search text" value={draft.q} onChange={set("q")} />
          <Input aria-label="Actor" placeholder="Actor (exact username)" value={draft.actor} onChange={set("actor")} />
          <Input aria-label="Action" placeholder="Action prefix, e.g. user." value={draft.action} onChange={set("action")} />
          <Select aria-label="Result" value={draft.result} onChange={set("result")}>
            <option value="">Any result</option><option value="success">Success</option><option value="failure">Failure</option><option value="denied">Denied</option>
          </Select>
          <Input aria-label="From" type="datetime-local" value={draft.since} onChange={set("since")} />
          <Input aria-label="To" type="datetime-local" value={draft.until} onChange={set("until")} />
          <div className="flex gap-2 lg:col-span-2">
            <Button type="submit">Apply filters</Button>
            <Button type="button" variant="secondary" onClick={() => { setDraft(EMPTY); setApplied(EMPTY); }}>Clear</Button>
          </div>
        </form>
      </Card>

      <Card>
        {query.isLoading && <Spinner />}
        <ErrorNote error={query.error} />
        {!query.isLoading && items.length === 0 && <Empty>No audit entries match.</Empty>}
        {items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-muted"><tr><th className="w-6" /><th className="py-2 pr-4">Time</th><th className="pr-4">Actor</th><th className="pr-4">Action</th><th className="pr-4">Resource</th><th className="pr-4">Result</th><th>Address</th></tr></thead>
              <tbody>
                {items.map((e) => (
                  <Fragment key={e.id}>
                    <tr className="cursor-pointer border-t border-line hover:bg-subtle" onClick={() => setOpen(open === e.id ? null : e.id)}>
                      <td>
                        <button type="button" aria-expanded={open === e.id} aria-label={`Details of entry ${e.id}`} className="p-1">
                          {open === e.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        </button>
                      </td>
                      <td className="whitespace-nowrap py-2 pr-4">{fmtTime(e.ts)}</td>
                      <td className="pr-4">{e.actor_name}</td>
                      <td className="pr-4 font-mono text-xs">{e.action}</td>
                      <td className="pr-4">{e.resource_name ?? e.resource_id ?? "—"}</td>
                      <td className="pr-4"><Badge tone={e.result === "success" ? "ok" : e.result === "denied" ? "warn" : "crit"}>{e.result}</Badge></td>
                      <td>{e.ip ?? "—"}</td>
                    </tr>
                    {open === e.id && (
                      <tr className="bg-subtle/50">
                        <td />
                        <td colSpan={6} className="space-y-3 py-3 pr-4">
                          <div className="grid gap-3 md:grid-cols-2">
                            <div><div className="mb-1 text-xs font-semibold uppercase text-muted">Old value</div><Json value={e.old_value} /></div>
                            <div><div className="mb-1 text-xs font-semibold uppercase text-muted">New value</div><Json value={e.new_value} /></div>
                          </div>
                          {e.detail && <p className="text-sm"><span className="text-muted">Detail: </span>{e.detail}</p>}
                          <p className="text-xs text-muted">Entry #{e.id}{e.resource_type ? ` · ${e.resource_type}` : ""}{e.host_id ? ` · host ${e.host_id}` : ""}</p>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {query.hasNextPage && (
          <div className="mt-4 text-center">
            <Button variant="secondary" busy={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>Load older entries</Button>
          </div>
        )}
      </Card>
    </div>
  );
}
