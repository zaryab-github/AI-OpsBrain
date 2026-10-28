import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { del, get, post } from "../api/client";
import type { AuthState, SessionInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, ErrorBox, Field, Input, Modal, PageHeader, Table, Td, formatTime } from "../components/ui";
import MfaEnroll from "./auth/MfaEnroll";
import PasswordChangeForm from "./auth/PasswordChangeForm";

export default function Profile() {
  const { auth, setAuth } = useAuth();
  const qc = useQueryClient();
  const [enrolling, setEnrolling] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [pw, setPw] = useState("");
  const [saved, setSaved] = useState(false);
  const sessions = useQuery({ queryKey: ["my-sessions"], queryFn: () => get<SessionInfo[]>("/auth/sessions") });
  const revoke = useMutation({
    mutationFn: (id: string) => del(`/auth/sessions/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-sessions"] }),
  });
  const disable = useMutation({
    mutationFn: () => post<AuthState>("/auth/mfa/disable", { password: pw }),
    onSuccess: (s) => {
      setAuth(s);
      setDisabling(false);
      setPw("");
    },
  });
  const user = auth?.user;
  if (!user) return null;

  return (
    <>
      <PageHeader title="My account" description={`${user.username} · ${user.email}`} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Password">
          {saved && <p className="mb-3 text-sm text-emerald-700">Password changed. Your other sessions were signed out.</p>}
          <PasswordChangeForm onDone={(s) => { setAuth(s); setSaved(true); void sessions.refetch(); }} />
        </Card>
        <Card title="Two-factor authentication">
          <div className="space-y-3 text-sm">
            <p>
              Status: {user.mfa_enabled ? <Badge tone="green">on</Badge> : <Badge>off</Badge>}
              {auth.mfa_required_by_policy && <span className="ml-2 text-slate-500">Required for your account.</span>}
            </p>
            {!user.mfa_enabled && <Button onClick={() => setEnrolling(true)}>Set up authenticator app</Button>}
            {user.mfa_enabled && !auth.mfa_required_by_policy && (
              <Button variant="secondary" onClick={() => setDisabling(true)}>Turn off</Button>
            )}
          </div>
        </Card>
        <Card title="Active sessions" className="lg:col-span-2">
          <ErrorBox error={sessions.error ?? revoke.error} />
          <Table head={["Signed in", "Last active", "IP address", "Browser", ""]}>
            {sessions.data?.map((s) => (
              <tr key={s.id}>
                <Td>{formatTime(s.created_at)}</Td>
                <Td>{formatTime(s.last_seen_at)}</Td>
                <Td>{s.ip ?? "—"}</Td>
                <Td className="max-w-xs truncate text-slate-500">{s.user_agent}</Td>
                <Td>
                  {s.current ? <Badge tone="blue">this session</Badge> : (
                    <Button variant="ghost" onClick={() => revoke.mutate(s.id)}>Sign out</Button>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
      <Modal title="Set up two-factor authentication" open={enrolling} onClose={() => setEnrolling(false)}>
        {enrolling && <MfaEnroll onDone={(s) => { setAuth(s); setEnrolling(false); }} />}
      </Modal>
      <Modal title="Turn off two-factor authentication" open={disabling} onClose={() => setDisabling(false)}
        footer={<Button variant="danger" loading={disable.isPending} onClick={() => disable.mutate()}>Turn off</Button>}>
        <Field label="Confirm with your password" htmlFor="mfa-off-pw">
          <Input id="mfa-off-pw" type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
        </Field>
        <ErrorBox error={disable.error} />
      </Modal>
    </>
  );
}
