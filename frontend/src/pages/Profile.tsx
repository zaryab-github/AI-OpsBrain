import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { SessionInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, ConfirmDialog, Empty, ErrorNote, Field, Input, PageHeader, SecretBox, Spinner } from "../components/ui";
import { fmtTime } from "../lib/format";

export function PasswordForm({ onDone, requireCurrent = true }: { onDone: () => void; requireCurrent?: boolean }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const mutation = useMutation({
    mutationFn: () => api<void>("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } }),
    onSuccess: onDone,
  });
  const mismatch = confirm !== "" && confirm !== next;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!mismatch) mutation.mutate();
  }
  return (
    <form onSubmit={submit} className="max-w-md space-y-4" aria-label="Change password">
      {requireCurrent && (
        <Field label="Current password">
          {(id) => <Input id={id} type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />}
        </Field>
      )}
      <Field label="New password" hint="At least 12 characters. A passphrase of several words works well.">
        {(id) => <Input id={id} type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />}
      </Field>
      <Field label="Repeat the new password" error={mismatch ? "The passwords do not match." : undefined}>
        {(id) => <Input id={id} type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />}
      </Field>
      <ErrorNote error={mutation.error} />
      <Button type="submit" busy={mutation.isPending} disabled={mismatch}>
        Change password
      </Button>
    </form>
  );
}

export function ForcedPasswordChange() {
  const { reloadMe, me } = useAuth();
  const navigate = useNavigate();
  return (
    <div>
      <PageHeader title="Choose a new password" subtitle={me?.user.must_change_password ? "You must set your own password before you can continue." : undefined} />
      <Card>
        <PasswordForm
          onDone={() => {
            void reloadMe().then(() => navigate("/", { replace: true }));
          }}
        />
      </Card>
    </div>
  );
}

interface Enrollment { secret: string; otpauth_uri: string }

export function MfaPanel({ onChanged }: { onChanged?: () => void }) {
  const { me, reloadMe } = useAuth();
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [qr, setQr] = useState<string>("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [dPassword, setDPassword] = useState("");
  const [dCode, setDCode] = useState("");

  useEffect(() => {
    if (enrollment) void QRCode.toDataURL(enrollment.otpauth_uri, { margin: 1, width: 192 }).then(setQr);
  }, [enrollment]);

  const start = useMutation({ mutationFn: () => api<Enrollment>("/auth/mfa/enroll", { method: "POST" }), onSuccess: setEnrollment });
  const enable = useMutation({
    mutationFn: () => api<{ recovery_codes: string[] }>("/auth/mfa/enable", { method: "POST", body: { code } }),
    onSuccess: (r) => {
      setRecovery(r.recovery_codes);
      setEnrollment(null);
      setCode("");
      void reloadMe();
    },
  });
  const disable = useMutation({
    mutationFn: () => api<void>("/auth/mfa/disable", { method: "POST", body: { password: dPassword, code: dCode } }),
    onSuccess: () => {
      setDisabling(false);
      setDPassword("");
      setDCode("");
      void reloadMe();
      onChanged?.();
    },
  });

  if (recovery) {
    return (
      <div className="space-y-3">
        <p className="text-sm">
          Two-factor authentication is on. Save these <strong>recovery codes</strong> somewhere safe. Each works once if you lose your phone. They will not be shown again.
        </p>
        <pre className="select-all rounded-md border border-line bg-subtle p-3 font-mono text-sm" aria-label="Recovery codes">{recovery.join("\n")}</pre>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => void navigator.clipboard?.writeText(recovery.join("\n"))}>Copy</Button>
          <Button onClick={() => { setRecovery(null); onChanged?.(); }}>I have saved them</Button>
        </div>
      </div>
    );
  }

  if (me?.user.mfa_enabled) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2"><Badge tone="ok">On</Badge><span className="text-sm">Two-factor authentication protects your account.</span></div>
        {disabling ? (
          <form className="max-w-md space-y-3" onSubmit={(e) => { e.preventDefault(); disable.mutate(); }}>
            <Field label="Password">{(id) => <Input id={id} type="password" value={dPassword} onChange={(e) => setDPassword(e.target.value)} required />}</Field>
            <Field label="Current authenticator code" hint="Use a code that you have not used in the last minute.">{(id) => <Input id={id} value={dCode} onChange={(e) => setDCode(e.target.value)} inputMode="numeric" required />}</Field>
            <ErrorNote error={disable.error} />
            <div className="flex gap-2">
              <Button type="submit" variant="danger" busy={disable.isPending}>Turn off</Button>
              <Button type="button" variant="secondary" onClick={() => setDisabling(false)}>Cancel</Button>
            </div>
          </form>
        ) : (
          <Button variant="secondary" onClick={() => setDisabling(true)}>Turn off two-factor authentication</Button>
        )}
      </div>
    );
  }

  if (enrollment) {
    return (
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); enable.mutate(); }}>
        <p className="text-sm">Scan this QR code with an authenticator app (Google Authenticator, Microsoft Authenticator, Aegis, 1Password, …), then enter the 6-digit code it shows.</p>
        {qr && <img src={qr} alt="QR code for the authenticator app" width={192} height={192} className="rounded border border-line bg-white p-1" />}
        <details className="text-sm">
          <summary className="cursor-pointer text-muted">Can't scan? Enter the key manually</summary>
          <div className="mt-2"><SecretBox value={enrollment.secret} /></div>
        </details>
        <Field label="6-digit code">
          {(id) => <Input id={id} value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={8} className="max-w-[10rem]" required />}
        </Field>
        <ErrorNote error={enable.error} />
        <Button type="submit" busy={enable.isPending}>Turn on</Button>
      </form>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2"><Badge>Off</Badge><span className="text-sm">Add a second step to your sign-in with an authenticator app.</span></div>
      <ErrorNote error={start.error} />
      <Button onClick={() => start.mutate()} busy={start.isPending}>Set up two-factor authentication</Button>
    </div>
  );
}

export function ForcedMfaSetup() {
  const { me, reloadMe } = useAuth();
  const navigate = useNavigate();
  return (
    <div>
      <PageHeader title="Set up two-factor authentication" subtitle="Your administrator requires everyone to use an authenticator app." />
      <Card>
        <MfaPanel onChanged={() => void reloadMe().then(() => me && navigate("/", { replace: true }))} />
      </Card>
    </div>
  );
}

function Sessions() {
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api<SessionInfo[]>("/auth/sessions") });
  const [ending, setEnding] = useState<SessionInfo | null>(null);
  const end = useMutation({
    mutationFn: (id: string) => api<void>(`/auth/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => { setEnding(null); void qc.invalidateQueries({ queryKey: ["sessions"] }); },
  });
  if (sessions.isLoading) return <Spinner />;
  if (sessions.error) return <ErrorNote error={sessions.error} />;
  if (!sessions.data?.length) return <Empty>No active sessions.</Empty>;
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-muted"><tr><th className="py-2 pr-4">Started</th><th className="pr-4">Last active</th><th className="pr-4">Address</th><th className="pr-4">Browser</th><th /></tr></thead>
          <tbody>
            {sessions.data.map((s) => (
              <tr key={s.id} className="border-t border-line">
                <td className="py-2 pr-4">{fmtTime(s.created_at)}</td>
                <td className="pr-4">{fmtTime(s.last_used_at)}</td>
                <td className="pr-4">{s.ip ?? "—"}</td>
                <td className="max-w-xs truncate pr-4" title={s.user_agent ?? ""}>{s.user_agent ?? "—"}</td>
                <td className="text-right">{s.current ? <Badge tone="brand">This session</Badge> : <Button variant="secondary" onClick={() => setEnding(s)}>Sign out</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ending && (
        <ConfirmDialog title="Sign out this session?" body="The device using it will have to sign in again." confirmLabel="Sign out" danger busy={end.isPending} error={end.error} onConfirm={() => end.mutate(ending.id)} onClose={() => setEnding(null)} />
      )}
    </>
  );
}

export default function Profile() {
  const { me } = useAuth();
  const [changed, setChanged] = useState(false);
  if (!me) return null;
  return (
    <div className="space-y-5">
      <PageHeader title="My account" />
      <Card title="Profile">
        <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-muted">Username</dt><dd>{me.user.username}</dd></div>
          <div><dt className="text-muted">Role</dt><dd>{me.user.role.name}</dd></div>
          <div><dt className="text-muted">Name</dt><dd>{me.user.full_name || "—"}</dd></div>
          <div><dt className="text-muted">Email</dt><dd>{me.user.email ?? "—"}</dd></div>
          <div><dt className="text-muted">Last sign-in</dt><dd>{fmtTime(me.user.last_login_at)}</dd></div>
        </dl>
      </Card>
      <Card title="Password">
        {changed && <p role="status" className="mb-3 text-sm text-ok">Password changed. Your other sessions were signed out.</p>}
        <PasswordForm onDone={() => setChanged(true)} />
      </Card>
      <Card title="Two-factor authentication"><MfaPanel /></Card>
      <Card title="Active sessions"><Sessions /></Card>
    </div>
  );
}
