import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Permission, Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, ConfirmDialog, ErrorNote, Field, Input, Modal, PageHeader, Spinner, cx } from "../components/ui";
import { groupBy } from "../lib/format";

export default function Roles() {
  const { can } = useAuth();
  const manage = can("roles.manage");
  const qc = useQueryClient();
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api<Role[]>("/roles") });
  const permissions = useQuery({ queryKey: ["permissions"], queryFn: () => api<Permission[]>("/permissions") });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Role | "new" | null>(null);
  const [deleting, setDeleting] = useState<Role | null>(null);

  const selected = roles.data?.find((r) => r.id === selectedId) ?? roles.data?.[0];
  const groups = useMemo(() => groupBy(permissions.data ?? [], (p) => p.group), [permissions.data]);

  const del = useMutation({
    mutationFn: (id: string) => api<void>(`/roles/${id}`, { method: "DELETE" }),
    onSuccess: () => { setDeleting(null); setSelectedId(null); void qc.invalidateQueries({ queryKey: ["roles"] }); },
  });

  if (roles.isLoading || permissions.isLoading) return <Spinner />;
  return (
    <div>
      <PageHeader
        title="Roles & RBAC"
        subtitle="A role is a set of permissions. Built-in roles are fixed; create a custom role for anything different."
        actions={manage && <Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" aria-hidden />New role</Button>}
      />
      <ErrorNote error={roles.error ?? permissions.error} />
      <div className="grid gap-5 md:grid-cols-[16rem_1fr]">
        <Card className="h-fit">
          <ul aria-label="Roles" className="-m-2 space-y-0.5">
            {roles.data?.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(r.id)}
                  aria-current={selected?.id === r.id}
                  className={cx("flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm", selected?.id === r.id ? "bg-brand/10 font-medium text-brand" : "hover:bg-subtle")}
                >
                  <span>{r.name}</span>
                  <span className="text-xs text-muted">{r.user_count} user{r.user_count === 1 ? "" : "s"}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        {selected && (
          <Card
            title={selected.name}
            actions={
              manage && !selected.is_system ? (
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setEditing(selected)}>Edit</Button>
                  <Button variant="danger" onClick={() => setDeleting(selected)}>Delete</Button>
                </div>
              ) : (
                <Badge>{selected.is_system ? "Built-in" : "Custom"}</Badge>
              )
            }
          >
            <p className="mb-4 text-sm text-muted">{selected.description || "No description."}</p>
            {selected.is_superuser && <p className="mb-4 rounded-md bg-brand/10 px-3 py-2 text-sm text-brand">Administrators implicitly hold every permission, including ones added in future releases.</p>}
            <div className="space-y-4">
              {Object.entries(groups).map(([group, perms]) => (
                <fieldset key={group}>
                  <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{group}</legend>
                  <ul className="space-y-1">
                    {perms.map((p) => {
                      const has = selected.permissions.includes(p.key);
                      return (
                        <li key={p.key} className="flex items-start gap-2 text-sm">
                          <span aria-label={has ? "granted" : "not granted"} className={cx("mt-0.5 inline-block h-4 w-4 shrink-0 rounded-full border text-center text-[10px] leading-[14px]", has ? "border-ok bg-ok/15 text-ok" : "border-line text-transparent")}>✓</span>
                          <span><code className="font-mono text-xs">{p.key}</code> <span className="text-muted">— {p.description}</span></span>
                        </li>
                      );
                    })}
                  </ul>
                </fieldset>
              ))}
            </div>
          </Card>
        )}
      </div>

      {editing && permissions.data && (
        <RoleForm
          permissions={permissions.data}
          role={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={(r) => { setEditing(null); setSelectedId(r.id); void qc.invalidateQueries({ queryKey: ["roles"] }); }}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete role ${deleting.name}?`}
          body={deleting.user_count > 0 ? `${deleting.user_count} user(s) still have this role. Move them to another role first.` : "This removes the role definition. It cannot be undone."}
          confirmLabel="Delete role" danger busy={del.isPending} error={del.error}
          onConfirm={() => del.mutate(deleting.id)} onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}

function RoleForm({ permissions, role, onClose, onSaved }: { permissions: Permission[]; role?: Role; onClose: () => void; onSaved: (r: Role) => void }) {
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [granted, setGranted] = useState<Set<string>>(new Set(role?.permissions ?? []));
  const groups = useMemo(() => groupBy(permissions, (p) => p.group), [permissions]);
  const m = useMutation({
    mutationFn: () => {
      const body = { name, description, permissions: [...granted] };
      return role ? api<Role>(`/roles/${role.id}`, { method: "PUT", body }) : api<Role>("/roles", { method: "POST", body });
    },
    onSuccess: onSaved,
  });
  const toggle = (key: string) => setGranted((prev) => { const next = new Set(prev); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  function submit(e: FormEvent) { e.preventDefault(); m.mutate(); }
  return (
    <Modal title={role ? `Edit ${role.name}` : "New role"} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={64} autoFocus />}</Field>
        <Field label="Description">{(id) => <Input id={id} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={255} />}</Field>
        <div className="max-h-72 space-y-3 overflow-y-auto rounded-md border border-line p-3">
          {Object.entries(groups).map(([group, perms]) => (
            <fieldset key={group}>
              <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{group}</legend>
              {perms.map((p) => (
                <label key={p.key} className="flex items-start gap-2 py-0.5 text-sm">
                  <input type="checkbox" checked={granted.has(p.key)} onChange={() => toggle(p.key)} className="mt-1" />
                  <span><code className="font-mono text-xs">{p.key}</code> <span className="text-muted">— {p.description}</span></span>
                </label>
              ))}
            </fieldset>
          ))}
        </div>
        <ErrorNote error={m.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" busy={m.isPending}>{role ? "Save role" : "Create role"}</Button>
        </div>
      </form>
    </Modal>
  );
}
