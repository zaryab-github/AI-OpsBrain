import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { post } from "../../api/client";
import type { AuthState } from "../../api/types";
import { Button, ErrorBox, Field, Input } from "../../components/ui";

export default function PasswordChangeForm({ onDone, submitLabel = "Change password" }: {
  onDone: (state: AuthState) => void;
  submitLabel?: string;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const change = useMutation({
    mutationFn: () => post<AuthState>("/auth/password", { current_password: current, new_password: next }),
    onSuccess: (s) => {
      setCurrent("");
      setNext("");
      setConfirm("");
      onDone(s);
    },
  });
  const mismatch = confirm.length > 0 && next !== confirm;
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (!mismatch) change.mutate(); }}>
      <Field label="Current password" htmlFor="pw-current">
        <Input id="pw-current" type="password" autoComplete="current-password" value={current}
          onChange={(e) => setCurrent(e.target.value)} required />
      </Field>
      <Field label="New password" htmlFor="pw-new"
        hint="At least 12 characters. A few unrelated words make a strong, memorable password.">
        <Input id="pw-new" type="password" autoComplete="new-password" value={next}
          onChange={(e) => setNext(e.target.value)} required />
      </Field>
      <Field label="Confirm new password" htmlFor="pw-confirm">
        <Input id="pw-confirm" type="password" autoComplete="new-password" value={confirm}
          onChange={(e) => setConfirm(e.target.value)} required />
      </Field>
      {mismatch && <p className="text-sm text-red-700">The new passwords do not match.</p>}
      <ErrorBox error={change.error} />
      <Button type="submit" loading={change.isPending} disabled={mismatch || !next}>{submitLabel}</Button>
    </form>
  );
}
