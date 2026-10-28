import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Plus } from "lucide-react";
import { useState } from "react";

import { get, patch, post } from "../../api/client";
import type { Role, User } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import {
  Badge, Button, Card, ErrorBox, Field, Input, Modal, PageHeader, Spinner, Table, Td, formatTime,
} from "../../components/ui";

interface TempPassword {
  user: User;
  temporary_password: string;
}

function RolePicker({ roles, value, onChange }: { roles: Role[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="grid grid-cols-2 gap-1.5">
      {roles.map((r) => (
        <label key={r.id} className="flex items-start gap-2 text-sm" title={r.description}>
          <input type="checkbox" className="mt-0.5" checked={value.includes(r.name)}
            onChange={(e) => onChange(e.target.checked ? [...value, r.name] : value.filter((x) => x !== r.name))} />
          <span>{r.name}</span>
        </label>
      ))}
    </div>
  );
}

function TempPasswordModal({ data, onClose }: { data: TempPassword | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Modal title="Temporary password" open={data !== null} onClose={onClose}
      footer={<Button onClick={onClose}>Done</Button>}>
      {data && (
        <>
          <p className="text-sm text-slate-600">
            Give this password to <strong>{data.user.username}</strong> through a secure channel. It is shown only
            once. They must choose a new password at first sign-in.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 select-all rounded bg-slate-100 px-2 py-1.5 font-mono text-sm">
              {data.temporary_password}
            </code>
            <Button variant="secondary" onClick={async () => {
              await navigator.clipboard.writeText(data.temporary_password);
              setCopied(true);
            }}>
              <Copy className="h-4 w-4" /> {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </>
      )}
    </Modal>
  );
}

function UserForm({ initial, roles, onSubmit, pending, error, submitLabel, isNew }: {
  initial: { username: string; email: string; full_name: string; roles: string[] };
  roles: Role[];
  onSubmit: (v: { username: string; email: string; full_name: string; roles: string[] }) => void;
  pending: boolean;
  error: unknown;
  submitLabel: string;
  isNew: boolean;
}) {
  const [v, setV] = useState(initial);
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); onSubmit(v); }}>
      <Field label="Username" htmlFor="u-name" hint={isNew ? "Letters, digits, dot, dash or underscore." : undefined}>
        <Input id="u-name" value={v.username} disabled={!isNew} required
          onChange={(e) => setV({ ...v, username: e.target.value })} />
      </Field>
      <Field label="Full name" htmlFor="u-full">
        <Input id="u-full" value={v.full_name} onChange={(e) => setV({ ...v, full_name: e.target.value })} />
      </Field>
      <Field label="Email" htmlFor="u-email">
        <Input id="u-email" type="email" value={v.email} required onChange={(e) => setV({ ...v, email: e.target.value })} />
      </Field>
      <Field label="Roles">
        <RolePicker roles={roles} value={v.roles} onChange={(r) => setV({ ...v, roles: r })} />
      </Field>
      <ErrorBox error={error} />
      <div className="flex justify-end">
        <Button type="submit" loading={pending} disabled={v.roles.length === 0}>{submitLabel}</Button>
      </div>
    </form>
  );
}

export default function Users() {
  const qc = useQueryClient();
  const { auth } = useAuth();
  const users = useQuery({ queryKey: ["users"], queryFn: () => get<User[]>("/users") });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => get<Role[]>("/roles") });
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [temp, setTemp] = useState<TempPassword | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });

  const create = useMutation({
    mutationFn: (v: { username: string; email: string; full_name: string; roles: string[] }) => post<TempPassword>("/users", v),
    onSuccess: (d) => { setCreating(false); setTemp(d); void refresh(); },
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => patch<User>(`/users/${id}`, body),
    onSuccess: () => { setEditing(null); void refresh(); },
  });
  const action = useMutation({
    mutationFn: ({ id, what }: { id: string; what: "reset-password" | "reset-mfa" | "unlock" }) =>
      post<TempPassword | User>(`/users/${id}/${what}`),
    onSuccess: (d) => {
      if ("temporary_password" in d) setTemp(d);
      void refresh();
    },
  });

  const confirmAction = (u: User, what: "reset-password" | "reset-mfa" | "unlock", text: string) => {
    if (window.confirm(text)) action.mutate({ id: u.id, what });
  };

  return (
    <>
      <PageHeader title="Users" description="Accounts that can sign in to the platform."
        actions={<Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> Add user</Button>} />
      <Card>
        <ErrorBox error={users.error ?? action.error} />
        {users.isLoading ? <Spinner /> : (
          <Table head={["User", "Email", "Roles", "Status", "Last sign-in", "Actions"]}>
            {users.data?.map((u) => {
              const locked = u.locked_until && new Date(u.locked_until) > new Date();
              return (
                <tr key={u.id} className={u.is_active ? "" : "opacity-60"}>
                  <Td><div className="font-medium">{u.username}</div><div className="text-xs text-slate-500">{u.full_name}</div></Td>
                  <Td>{u.email}</Td>
                  <Td><div className="flex flex-wrap gap-1">{u.roles.map((r) => <Badge key={r} tone="blue">{r}</Badge>)}</div></Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {u.is_active ? <Badge tone="green">active</Badge> : <Badge>deactivated</Badge>}
                      {locked && <Badge tone="red">locked</Badge>}
                      {u.mfa_enabled && <Badge>2FA</Badge>}
                      {u.must_change_password && <Badge tone="yellow">must change password</Badge>}
                    </div>
                  </Td>
                  <Td className="whitespace-nowrap">{formatTime(u.last_login_at)}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      <Button variant="ghost" onClick={() => setEditing(u)}>Edit</Button>
                      {locked && <Button variant="ghost" onClick={() => action.mutate({ id: u.id, what: "unlock" })}>Unlock</Button>}
                      <Button variant="ghost" onClick={() => confirmAction(u, "reset-password",
                        `Issue a new temporary password for ${u.username}? Their current sessions will be signed out.`)}>
                        Reset password
                      </Button>
                      {u.mfa_enabled && (
                        <Button variant="ghost" onClick={() => confirmAction(u, "reset-mfa",
                          `Remove ${u.username}'s authenticator? They will need to set it up again.`)}>
                          Reset 2FA
                        </Button>
                      )}
                      {u.id !== auth?.user?.id && (
                        <Button variant="ghost" onClick={() => {
                          const verb = u.is_active ? "Deactivate" : "Reactivate";
                          if (window.confirm(`${verb} ${u.username}?`)) update.mutate({ id: u.id, body: { is_active: !u.is_active } });
                        }}>
                          {u.is_active ? "Deactivate" : "Reactivate"}
                        </Button>
                      )}
                    </div>
                  </Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>

      <Modal title="Add user" open={creating} onClose={() => setCreating(false)}>
        {creating && roles.data && (
          <UserForm isNew initial={{ username: "", email: "", full_name: "", roles: ["Viewer"] }} roles={roles.data}
            onSubmit={(v) => create.mutate(v)} pending={create.isPending} error={create.error} submitLabel="Create user" />
        )}
      </Modal>
      <Modal title={`Edit ${editing?.username ?? ""}`} open={editing !== null} onClose={() => setEditing(null)}>
        {editing && roles.data && (
          <UserForm isNew={false} initial={editing} roles={roles.data} submitLabel="Save"
            pending={update.isPending} error={update.error}
            onSubmit={(v) => update.mutate({ id: editing.id, body: { email: v.email, full_name: v.full_name, roles: v.roles } })} />
        )}
      </Modal>
      <TempPasswordModal data={temp} onClose={() => setTemp(null)} />
    </>
  );
}
