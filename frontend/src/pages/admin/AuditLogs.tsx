import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { Download, ShieldCheck } from "lucide-react";
import { Fragment, useState } from "react";

import { get, post, qs } from "../../api/client";
import type { AuditPage } from "../../api/types";
import {
  Badge, Button, Card, Empty, ErrorBox, Input, PageHeader, Select, Spinner, Table, Td, formatTime, statusTone,
} from "../../components/ui";

interface Filters {
  actor: string;
  action: string;
  resource_type: string;
  result: string;
  since: string;
  until: string;
  q: string;
}

const EMPTY: Filters = { actor: "", action: "", resource_type: "", result: "", since: "", until: "", q: "" };

function toParams(f: Filters) {
  return {
    ...f,
    since: f.since ? new Date(f.since).toISOString() : undefined,
    until: f.until ? new Date(f.until).toISOString() : undefined,
  };
}

function Json({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-slate-400">—</span>;
  return <pre className="max-w-md overflow-x-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-[11px]">
    {JSON.stringify(value, null, 2)}
  </pre>;
}

export default function AuditLogs() {
  const [form, setForm] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [expanded, setExpanded] = useState<number | null>(null);
  const pages = useInfiniteQuery({
    queryKey: ["audit", applied],
    queryFn: ({ pageParam }) => get<AuditPage>(`/audit${qs({ ...toParams(applied), before_id: pageParam, limit: 100 })}`),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before_id ?? undefined,
  });
  const verify = useMutation({
    mutationFn: () => post<{ ok: boolean; checked: number; message: string }>("/audit/verify"),
  });
  const rows = pages.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <>
      <PageHeader title="Audit Logs"
        description="Every change and sign-in: who, what, when, which resource or host, old and new value, and result."
        actions={<>
          <Button variant="secondary" loading={verify.isPending} onClick={() => verify.mutate()}>
            <ShieldCheck className="h-4 w-4" /> Verify integrity
          </Button>
          <a href={`/api/v1/audit/export.csv${qs(toParams(applied))}`}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50">
            <Download className="h-4 w-4" /> Export CSV
          </a>
        </>} />
      {verify.data && (
        <div className={`mb-4 rounded-md border px-3 py-2 text-sm ${verify.data.ok ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800"}`}>
          {verify.data.ok ? "Hash chain intact. " : "Integrity check FAILED. "}{verify.data.message}
        </div>
      )}
      <ErrorBox error={verify.error} />
      <Card className="mb-4">
        <form className="grid gap-2 md:grid-cols-4 lg:grid-cols-8"
          onSubmit={(e) => { e.preventDefault(); setApplied(form); }}>
          <Input placeholder="User" aria-label="User" value={form.actor} onChange={(e) => setForm({ ...form, actor: e.target.value })} />
          <Input placeholder="Action (e.g. user.)" aria-label="Action" value={form.action}
            onChange={(e) => setForm({ ...form, action: e.target.value })} />
          <Input placeholder="Resource type" aria-label="Resource type" value={form.resource_type}
            onChange={(e) => setForm({ ...form, resource_type: e.target.value })} />
          <Select aria-label="Result" value={form.result} onChange={(e) => setForm({ ...form, result: e.target.value })}>
            <option value="">Any result</option>
            <option value="success">success</option>
            <option value="failure">failure</option>
            <option value="denied">denied</option>
          </Select>
          <Input type="datetime-local" aria-label="From" value={form.since} onChange={(e) => setForm({ ...form, since: e.target.value })} />
          <Input type="datetime-local" aria-label="To" value={form.until} onChange={(e) => setForm({ ...form, until: e.target.value })} />
          <Input placeholder="Search text" aria-label="Search text" value={form.q} onChange={(e) => setForm({ ...form, q: e.target.value })} />
          <div className="flex gap-2">
            <Button type="submit">Filter</Button>
            <Button type="button" variant="ghost" onClick={() => { setForm(EMPTY); setApplied(EMPTY); }}>Clear</Button>
          </div>
        </form>
      </Card>
      <Card>
        <ErrorBox error={pages.error} />
        {pages.isLoading ? <Spinner /> : rows.length === 0 ? <Empty>No audit entries match.</Empty> : (
          <Table head={["Time", "User", "IP", "Action", "Resource", "Host", "Result", "Detail"]}>
            {rows.map((r) => (
              <Fragment key={r.id}>
                <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setExpanded(expanded === r.id ? null : r.id)}>
                  <Td className="whitespace-nowrap">{formatTime(r.ts)}</Td>
                  <Td>{r.actor_name}</Td>
                  <Td className="text-slate-500">{r.actor_ip ?? "—"}</Td>
                  <Td className="font-mono text-xs">{r.action}</Td>
                  <Td>{r.resource_type}{r.resource_id ? <span className="block max-w-[14rem] truncate font-mono text-[11px] text-slate-500">{r.resource_id}</span> : null}</Td>
                  <Td>{r.host_id ?? "—"}</Td>
                  <Td><Badge tone={statusTone(r.result)}>{r.result}</Badge></Td>
                  <Td className="max-w-xs truncate text-slate-600">{r.detail}</Td>
                </tr>
                {expanded === r.id && (
                  <tr className="bg-slate-50/50">
                    <td colSpan={8} className="px-3 py-2">
                      <div className="grid gap-3 md:grid-cols-2">
                        <div><div className="mb-1 text-xs font-semibold text-slate-500">Old value</div><Json value={r.old_value} /></div>
                        <div><div className="mb-1 text-xs font-semibold text-slate-500">New value</div><Json value={r.new_value} /></div>
                      </div>
                      <p className="mt-2 text-xs text-slate-600">{r.detail}</p>
                      <p className="mt-1 font-mono text-[11px] text-slate-400">#{r.id} · hash {r.hash}</p>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </Table>
        )}
        {pages.hasNextPage && (
          <div className="mt-3 text-center">
            <Button variant="secondary" loading={pages.isFetchingNextPage} onClick={() => pages.fetchNextPage()}>Load older entries</Button>
          </div>
        )}
      </Card>
    </>
  );
}
