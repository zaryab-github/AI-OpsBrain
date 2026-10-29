import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Lock, Pencil, ShieldOff, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Role, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, ConfirmDialog, Empty, ErrorNote, Field, Input, Modal, PageHeader, SecretBox, Select, Spinner } from "../components/ui";
import { fmtTime } from "../lib/format";

type Dialog =
  | { kind: "create" }
  | { kind: "edit"; user: User }
  | { kind: "reset"; user: User }
  | { kind: "unlock"; user: User }
  | { kind: "mfa"; user: User }
  | { kind: "secret"; title: string; message: string; value: string };

export default function Users() {
  const { can, me } = useAuth();
  const manage = can("users.manage");
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api<Role[]>("/roles"), enabled: can("roles.view") || manage });
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const close = () => setDialog(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="People who can sign in. Accounts are disabled rather than deleted so the audit trail stays complete."
        actions={manage && <Button onClick={() => setDialog({ kind: "create" })}><UserPlus className="h-4 w-4" aria-hidden />Add user</Button>}
      />
      <Card>
        {users.isLoading && <Spinner />}
        <ErrorNote error={users.error} />
        {users.data && users.data.length === 0 && <Empty>No users.</Empty>}
        {users.data && users.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-muted">
                <tr><th className="py-2 pr-4">User</th><th className="pr-4">Role</th><th className="pr-4">Status</th><th className="pr-4">Last sign-in</th>{manage && <th className="text-right">Actions</th>}</tr>
              </thead>
              <tbody>
                {users.data.map((u) => (
                  <tr key={u.id} className="border-t border-line align-top">
                    <td className="py-2 pr-4"><div className="font-medium">{u.username}</div><div className="text-xs text-muted">{u.full_name || u.email || ""}</div></td>
                    <td className="pr-4">{u.role.name}</td>
                    <td className="pr-4 space-x-1">
                      {u.is_active ? <Badge tone="ok">Active</Badge> : <Badge tone="crit">Disabled</Badge>}
                      {u.locked && <Badge tone="warn">Locked</Badge>}
                      {u.mfa_enabled && <Badge tone="brand">2FA</Badge>}
                      {u.must_change_password && <Badge>Password change pending</Badge>}
                    </td>
                    <td className="pr-4">{fmtTime(u.last_login_at)}</td>
                    {manage && (
                      <td className="whitespace-nowrap py-2 text-right">
                        <Button variant="ghost" aria-label={`Edit ${u.username}`} title="Edit" onClick={() => setDialog({ kind: "edit", user: u })}><Pencil className="h-4 w-4" /></Button>
                        <Button variant="ghost" aria-label={`Reset password for ${u.username}`} title="Reset password" onClick={() => setDialog({ kind: "reset", user: u })}><KeyRound className="h-4 w-4" /></Button>
                        {u.locked && <Button variant="ghost" aria-label={`Unlock ${u.username}`} title="Unlock" onClick={() => setDialog({ kind: "unlock", user: u })}><Lock className="h-4 w-4" /></Button>}
                        {u.mfa_enabled && <Button variant="ghost" aria-label={`Remove two-factor authentication for ${u.username}`} title="Remove 2FA" onClick={() => setDialog({ kind: "mfa", user: u })}><ShieldOff className="h-4 w-4" /></Button>}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {dialog?.kind === "create" && roles.data && (
        <UserForm roles={roles.data} onClose={close} onSaved={(secret) => { void refresh(); setDialog(secret ? { kind: "secret", ...secret } : null); }} />
      )}
      {dialog?.kind === "edit" && roles.data && (
        <UserForm roles={roles.data} user={dialog.user} isSelf={dialog.user.id === me?.user.id} onClose={close} onSaved={() => { void refresh(); close(); }} />
      )}
      {dialog?.kind === "reset" && (
        <ActionDialog
          title={`Reset password for ${dialog.user.username}?`}
          body="A new one-time password is generated, all of this user's sessions end, and they must choose their own password at next sign-in."
          confirmLabel="Reset password"
          run={() => api<{ temporary_password: string }>(`/users/${dialog.user.id}/reset-password`, { method: "POST" })}
          onClose={close}
          onDone={(r) => { void refresh(); setDialog({ kind: "secret", title: "One-time password", message: `Give this to ${dialog.user.username} through a secure channel. It is shown only once.`, value: (r as { temporary_password: string }).temporary_password }); }}
        />
      )}
      {dialog?.kind === "unlock" && (
        <ActionDialog title={`Unlock ${dialog.user.username}?`} body="The failed-attempt counter is cleared and the user can try again." confirmLabel="Unlock" run={() => api<void>(`/users/${dialog.user.id}/unlock`, { method: "POST" })} onClose={close} onDone={() => { void refresh(); close(); }} />
      )}
      {dialog?.kind === "mfa" && (
        <ActionDialog danger title={`Remove two-factor authentication for ${dialog.user.username}?`} body="Use this when the user lost their device and recovery codes. Their sessions end and they will need to enrol again." confirmLabel="Remove 2FA" run={() => api<void>(`/users/${dialog.user.id}/reset-mfa`, { method: "POST" })} onClose={close} onDone={() => { void refresh(); close(); }} />
      )}
      {dialog?.kind === "secret" && (
        <Modal title={dialog.title} onClose={close}>
          <div className="space-y-3">
            <p className="text-sm">{dialog.message}</p>
            <SecretBox value={dialog.value} />
            <div className="flex justify-end"><Button onClick={close}>Done</Button></div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ActionDialog({ title, body, confirmLabel, danger, run, onDone, onClose }: { title: string; body: string; confirmLabel: string; danger?: boolean; run: () => Promise<unknown>; onDone: (result: unknown) => void; onClose: () => void }) {
  const m = useMutation({ mutationFn: run, onSuccess: onDone });
  return <ConfirmDialog title={title} body={body} confirmLabel={confirmLabel} danger={danger} busy={m.isPending} error={m.error} onConfirm={() => m.mutate()} onClose={onClose} />;
}

function UserForm({ roles, user, isSelf, onClose, onSaved }: { roles: Role[]; user?: User; isSelf?: boolean; onClose: () => void; onSaved: (secret?: { title: string; message: string; value: string }) => void }) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [roleId, setRoleId] = useState(user?.role.id ?? roles.find((r) => r.name === "Viewer")?.id ?? roles[0]?.id ?? "");
  const [active, setActive] = useState(user?.is_active ?? true);
  const [password, setPassword] = useState("");
  const m = useMutation({
    mutationFn: () =>
      user
        ? api<User>(`/users/${user.id}`, { method: "PATCH", body: { full_name: fullName, email: email || null, role_id: roleId, is_active: active } })
        : api<{ temporary_password: string | null }>("/users", { method: "POST", body: { username, full_name: fullName, email: email || null, role_id: roleId, password: password || null } }),
    onSuccess: (r) => {
      const temp = (r as { temporary_password?: string | null }).temporary_password;
      onSaved(temp ? { title: "One-time password", message: `Give this to ${username} through a secure channel. It is shown only once and must be changed at first sign-in.`, value: temp } : undefined);
    },
  });
  function submit(e: FormEvent) { e.preventDefault(); m.mutate(); }
  return (
    <Modal title={user ? `Edit ${user.username}` : "Add user"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {!user && <Field label="Username" hint="3–32 characters: lowercase letters, digits, . _ -">{(id) => <Input id={id} value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />}</Field>}
        <Field label="Full name">{(id) => <Input id={id} value={fullName} onChange={(e) => setFullName(e.target.value)} />}</Field>
        <Field label="Email">{(id) => <Input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
        <Field label="Role">{(id) => <Select id={id} value={roleId} onChange={(e) => setRoleId(e.target.value)}>{roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select>}</Field>
        {!user && <Field label="Initial password" hint="Leave empty to generate a one-time password. The user must change it at first sign-in.">{(id) => <Input id={id} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />}</Field>}
        {user && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={active} disabled={isSelf} onChange={(e) => setActive(e.target.checked)} />
            Account is active{isSelf && " (you cannot disable yourself)"}
          </label>
        )}
        <ErrorNote error={m.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" busy={m.isPending}>{user ? "Save" : "Create user"}</Button>
        </div>
      </form>
    </Modal>
  );
}
