import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { get, put } from "../../api/client";
import type { SettingItem } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Button, Card, ErrorBox, Input, PageHeader, Select, Spinner } from "../../components/ui";
import { PlatformHealth } from "../Overview";

const ENUM_LABELS: Record<string, string> = {
  none: "Nobody (optional for everyone)",
  admins: "Users who can manage users or settings",
  all: "Everyone",
};

function SettingRow({ s, editable }: { s: SettingItem; editable: boolean }) {
  const qc = useQueryClient();
  const [value, setValue] = useState<unknown>(s.value);
  const save = useMutation({
    mutationFn: () => put<SettingItem>(`/settings/${s.key}`, { value }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
  const changed = JSON.stringify(value) !== JSON.stringify(s.value);
  return (
    <div className="grid gap-2 border-b border-slate-100 py-3 md:grid-cols-[1fr_16rem_auto] md:items-center">
      <div>
        <div className="text-sm font-medium">{s.label}</div>
        <div className="text-xs text-slate-500">{s.description} Default: {String(s.default)}.</div>
        <ErrorBox error={save.error} />
      </div>
      {s.type === "enum" ? (
        <Select aria-label={s.label} disabled={!editable} value={String(value)} onChange={(e) => setValue(e.target.value)}>
          {s.choices.map((c) => <option key={c} value={c}>{ENUM_LABELS[c] ?? c}</option>)}
        </Select>
      ) : s.type === "bool" ? (
        <input type="checkbox" aria-label={s.label} disabled={!editable} checked={Boolean(value)}
          onChange={(e) => setValue(e.target.checked)} />
      ) : (
        <Input aria-label={s.label} disabled={!editable} type={s.type === "int" ? "number" : "text"}
          min={s.minimum ?? undefined} max={s.maximum ?? undefined} value={String(value)}
          onChange={(e) => setValue(s.type === "int" ? Number(e.target.value) : e.target.value)} />
      )}
      <div className="w-16">
        {editable && changed && <Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button>}
      </div>
    </div>
  );
}

export default function SystemSettings() {
  const { can } = useAuth();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => get<SettingItem[]>("/settings") });
  const groups = new Map<string, SettingItem[]>();
  for (const s of settings.data ?? []) groups.set(s.group, [...(groups.get(s.group) ?? []), s]);
  return (
    <>
      <PageHeader title="System Settings" description="Every change is recorded in the audit log." />
      <div className="grid gap-4 xl:grid-cols-[1fr_24rem]">
        <div className="space-y-4">
          <ErrorBox error={settings.error} />
          {settings.isLoading && <Spinner />}
          {[...groups.entries()].map(([group, items]) => (
            <Card key={group} title={group}>
              {items.map((s) => <SettingRow key={`${s.key}:${JSON.stringify(s.value)}`} s={s} editable={can("settings.manage")} />)}
            </Card>
          ))}
        </div>
        <Card title="Platform health">
          <PlatformHealth />
        </Card>
      </div>
    </>
  );
}
