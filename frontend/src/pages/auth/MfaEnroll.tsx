import { useMutation } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useRef, useState } from "react";

import { post } from "../../api/client";
import type { AuthState } from "../../api/types";
import { Button, ErrorBox, Field, Input, Spinner } from "../../components/ui";

/** Authenticator-app enrolment, used both during sign-in and from My account. */
export default function MfaEnroll({ onDone }: { onDone: (state: AuthState) => void }) {
  const [secret, setSecret] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const setup = useMutation({
    mutationFn: () => post<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup"),
    onSuccess: async (d) => {
      setSecret(d.secret);
      setQr(await QRCode.toDataURL(d.otpauth_uri, { margin: 1, width: 192 }));
    },
  });
  const enable = useMutation({
    mutationFn: () => post<AuthState>("/auth/mfa/enable", { code }),
    onSuccess: onDone,
  });
  const started = useRef(false);
  const { mutate: startSetup } = setup;
  useEffect(() => {
    // Exactly one setup request: a second one would replace the pending secret on the server.
    if (started.current) return;
    started.current = true;
    startSetup();
  }, [startSetup]);

  if (setup.isPending) return <Spinner label="Preparing authenticator setup…" />;
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); enable.mutate(); }}>
      <ErrorBox error={setup.error} />
      <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-600">
        <li>Open an authenticator app (Microsoft Authenticator, Google Authenticator, 1Password, …).</li>
        <li>Scan the QR code, or type the key shown below it.</li>
        <li>Enter the 6-digit code the app shows.</li>
      </ol>
      {qr && <img src={qr} alt="Authenticator QR code" className="mx-auto h-48 w-48 rounded border border-slate-200" />}
      {secret && (
        <p className="break-all text-center font-mono text-xs text-slate-600" aria-label="Setup key">
          {secret.match(/.{1,4}/g)?.join(" ")}
        </p>
      )}
      <Field label="6-digit code" htmlFor="enroll-code">
        <Input id="enroll-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
      </Field>
      <ErrorBox error={enable.error} />
      <Button type="submit" className="w-full" loading={enable.isPending} disabled={code.length !== 6 || !secret}>
        Turn on two-factor authentication
      </Button>
    </form>
  );
}
