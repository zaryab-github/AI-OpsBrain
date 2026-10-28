import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { del, get, patch, post } from "../../api/client";
import type { Permission, Role } from "../../api/types";
import { Badge, Button, Card, ErrorBox, Field, Input, Modal, PageHeader, Spinner } from "../../components/ui";

/** Permission matrix: rows are permissions grouped by area, columns are roles. */
export default function Roles() {
  const qc = useQueryClient();
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => get<Role[]>("/roles") });
  const perms = useQuery({ queryKey: ["permissions"], queryFn: () => get<Permission[]>("/roles/permissions") });
  const [draft, setDraft] = useState<Record<string, string[]>>({});
  const [creating, setCreating] = useState(false);
  const [newRole, setNewRole] = useState({ name: "", description: "" });

  const groups = useMemo(() => {
    const g = new Map<string, Permission[]>();
    for (const p of perms.data ?? []) g.set(p.group, [...(g.get(p.group) ?? []), p]);
    return [...g.entries()];
  }, [perms.data]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["roles"] });
  const save = useMutation({
    mutationFn: async () => {
      for (const [id, permissions] of Object.entries(draft)) await patch(`/roles/${id}`, { permissions });
    },
    onSuccess: () => { setDraft({}); void refresh(); },
  });
  const create = useMutation({
    mutationFn: () => post<Role>("/roles", { ...newRole, permissions: ["dashboard.view"] }),
    onSuccess: () => { setCreating(false); setNewRole({ name: "", description: "" }); void refresh(); },
  });
  const remove = useMutation({ mutationFn: (id: string) => del(`/roles/${id}`), onSuccess: () => void refresh() });

  const current = (r: Role) => draft[r.id] ?? r.permissions;
  const toggle = (r: Role, key: string) => {
    const list = current(r);
    setDraft({ ...draft, [r.id]: list.includes(key) ? list.filter((p) => p !== key) : [...list, key] });
  };
  const dirty = Object.keys(draft).length > 0;

  if (roles.isLoading || perms.isLoading) return <Spinner />;
  return (
    <>
      <PageHeader title="Roles & RBAC" description="What each role is allowed to do. Admin always has every permission."
        actions={<>
          {dirty && <Button variant="secondary" onClick={() => setDraft({})}>Discard changes</Button>}
          {dirty && <Button loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button>}
          {!dirty && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New role</Button>}
        </>} />
      <ErrorBox error={roles.error ?? perms.error ?? save.error ?? remove.error} />
      <Card>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="px-2 py-2 text-left text-xs font-semibold uppercase text-slate-500">Permission</th>
                {roles.data?.map((r) => (
                  <th key={r.id} className="px-2 py-2 text-center align-bottom" title={r.description}>
                    <div className="font-semibold">{r.name}</div>
                    <div className="text-[11px] font-normal text-slate-500">
                      {r.user_count} user{r.user_count === 1 ? "" : "s"}
                    </div>
                    {!r.is_system && (
                      <button className="text-[11px] font-normal text-red-600 hover:underline"
                        onClick={() => window.confirm(`Delete role ${r.name}?`) && remove.mutate(r.id)}>delete</button>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.map(([group, items]) => (
                <Fragment key={group}>
                  <tr><td colSpan={(roles.data?.length ?? 0) + 1}
                    className="bg-slate-50 px-2 py-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{group}</td></tr>
                  {items.map((p) => (
                    <tr key={p.key} className="border-b border-slate-100">
                      <td className="px-2 py-1.5">
                        <div>{p.description}</div>
                        <div className="font-mono text-[11px] text-slate-400">{p.key}</div>
                      </td>
                      {roles.data?.map((r) => (
                        <td key={r.id} className="px-2 py-1.5 text-center">
                          <input type="checkbox" aria-label={`${r.name}: ${p.key}`}
                            checked={r.name === "Admin" || current(r).includes(p.key)}
                            disabled={r.name === "Admin"} onChange={() => toggle(r, p.key)} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="mt-3 text-xs text-slate-500">
        Built-in roles: <Badge>Admin</Badge> <Badge>DevOps</Badge> <Badge>NOC</Badge> <Badge>Developer</Badge>{" "}
        <Badge>Viewer</Badge> <Badge>Auditor</Badge>. Their permissions can be adjusted (except Admin); they cannot be deleted.
      </p>
      <Modal title="New role" open={creating} onClose={() => setCreating(false)}
        footer={<Button loading={create.isPending} disabled={!newRole.name} onClick={() => create.mutate()}>Create</Button>}>
        <Field label="Name" htmlFor="role-name">
          <Input id="role-name" value={newRole.name} onChange={(e) => setNewRole({ ...newRole, name: e.target.value })} />
        </Field>
        <Field label="Description" htmlFor="role-desc">
          <Input id="role-desc" value={newRole.description}
            onChange={(e) => setNewRole({ ...newRole, description: e.target.value })} />
        </Field>
        <p className="text-xs text-slate-500">The role starts with “View the overview dashboard”. Tick more permissions in the matrix after creating it.</p>
        <ErrorBox error={create.error} />
      </Modal>
    </>
  );
}
