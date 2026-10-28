import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { post } from "../../api/client";
import type { AuthState } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Button, ErrorBox, Field, Input } from "../../components/ui";
import MfaEnroll from "./MfaEnroll";
import PasswordChangeForm from "./PasswordChangeForm";

const TITLES: Record<string, string> = {
  mfa_required: "Two-factor authentication",
  password_change_required: "Choose a new password",
  mfa_enrollment_required: "Set up two-factor authentication",
};

function PasswordStep({ onDone }: { onDone: (s: AuthState) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => post<AuthState>("/auth/login", { username, password }),
    onSuccess: onDone,
    onError: () => setPassword(""),
  });
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); login.mutate(); }}>
      <Field label="Username or email" htmlFor="login-user">
        <Input id="login-user" autoComplete="username" autoFocus value={username}
          onChange={(e) => setUsername(e.target.value)} required />
      </Field>
      <Field label="Password" htmlFor="login-password">
        <Input id="login-password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} required />
      </Field>
      <ErrorBox error={login.error} />
      <Button type="submit" className="w-full" loading={login.isPending}>Sign in</Button>
    </form>
  );
}

function MfaStep({ onDone }: { onDone: (s: AuthState) => void }) {
  const [code, setCode] = useState("");
  const verify = useMutation({
    mutationFn: () => post<AuthState>("/auth/mfa/verify", { code }),
    onSuccess: onDone,
    onError: () => setCode(""),
  });
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); verify.mutate(); }}>
      <p className="text-sm text-slate-600">Enter the 6-digit code from your authenticator app.</p>
      <Field label="Code" htmlFor="mfa-code">
        <Input id="mfa-code" inputMode="numeric" autoComplete="one-time-code" autoFocus maxLength={6} value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
      </Field>
      <ErrorBox error={verify.error} />
      <Button type="submit" className="w-full" loading={verify.isPending} disabled={code.length !== 6}>Verify</Button>
    </form>
  );
}

export default function Login() {
  const { auth, setAuth, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (auth?.state === "full") return <Navigate to={from} replace />;

  const onDone = (s: AuthState) => {
    setAuth(s);
    if (s.state === "full") navigate(from, { replace: true });
  };
  const state = auth?.state;

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-10 w-10" />
          <h1 className="text-lg font-semibold">{state ? TITLES[state] : "Sign in to AI-OpsBrain"}</h1>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          {!state && <PasswordStep onDone={onDone} />}
          {state === "mfa_required" && <MfaStep onDone={onDone} />}
          {state === "password_change_required" && (
            <>
              <p className="mb-4 text-sm text-slate-600">
                Your password was set by an administrator. Choose your own password to continue.
              </p>
              <PasswordChangeForm onDone={onDone} submitLabel="Save and continue" />
            </>
          )}
          {state === "mfa_enrollment_required" && (
            <>
              <p className="mb-4 text-sm text-slate-600">
                Your account requires two-factor authentication. Set it up once to continue.
              </p>
              <MfaEnroll onDone={onDone} />
            </>
          )}
          {state && (
            <button className="mt-4 w-full text-center text-sm text-slate-500 hover:underline"
              onClick={() => void logout()}>
              Cancel and sign in as someone else
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
