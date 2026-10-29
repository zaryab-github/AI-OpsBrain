import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "../components/Layout";
import { Button, ErrorNote, Field, Input } from "../components/ui";
import { BRAND_ICON } from "../nav";

export default function Login() {
  const { status, login, verifyMfa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const branding = useQuery({ queryKey: ["public"], queryFn: () => api<{ instance_name: string }>("/system/public", { auth: false }) });
  const Brand = BRAND_ICON;
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "authenticated") return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mfaToken) {
        await verifyMfa(mfaToken, code);
        navigate(from, { replace: true });
      } else {
        const next = await login(username, password);
        if (next) setMfaToken(next.mfaToken);
        else navigate(from, { replace: true });
      }
    } catch (err) {
      setError(err);
      // A used-up or expired sign-in step: start over.
      if (mfaToken && err instanceof Error && "code" in err && (err as { code: string }).code === "mfa_token_invalid") {
        setMfaToken(null);
        setCode("");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-bg p-4">
      <div className="absolute right-3 top-3">
        <ThemeToggle />
      </div>
      <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-lg border border-line bg-surface p-6 shadow-sm" aria-label="Sign in">
        <div className="flex items-center gap-2">
          <Brand className="h-6 w-6 text-brand" aria-hidden />
          <h1 className="text-lg font-semibold">{branding.data?.instance_name ?? "AI Observability Platform"}</h1>
        </div>
        {mfaToken ? (
          <>
            <p className="text-sm text-muted">Enter the 6-digit code from your authenticator app, or one of your recovery codes.</p>
            <Field label="Authentication code">
              {(id) => <Input id={id} value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" inputMode="text" autoFocus required />}
            </Field>
          </>
        ) : (
          <>
            <Field label="Username">
              {(id) => <Input id={id} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required />}
            </Field>
            <Field label="Password">
              {(id) => <Input id={id} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />}
            </Field>
          </>
        )}
        <ErrorNote error={error} />
        <Button type="submit" busy={busy} className="w-full">
          {mfaToken ? "Verify" : "Sign in"}
        </Button>
        {mfaToken && (
          <button type="button" className="w-full text-center text-xs text-muted underline" onClick={() => { setMfaToken(null); setCode(""); setError(null); }}>
            Start over
          </button>
        )}
      </form>
    </div>
  );
}
