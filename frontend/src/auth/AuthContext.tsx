import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, onSessionChange, refreshSession, setAccessToken } from "../api/client";
import type { LoginResult, Me } from "../api/types";

type Status = "loading" | "anonymous" | "authenticated";

interface AuthState {
  status: Status;
  me: Me | null;
  can: (permission: string) => boolean;
  login: (username: string, password: string) => Promise<{ mfaToken: string } | null>;
  verifyMfa: (mfaToken: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
  reloadMe: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    let cancelled = false;
    const off = onSessionChange((s) => {
      if (cancelled) return;
      if (s) {
        setMe(s.me);
        setStatus("authenticated");
      } else {
        setMe(null);
        setStatus("anonymous");
      }
    });
    // Restore the session from the HttpOnly refresh cookie, if there is one.
    void refreshSession().then((s) => {
      if (!cancelled && !s) setStatus("anonymous");
    });
    return () => {
      cancelled = true;
      off();
    };
  }, []);

  const finish = useCallback((result: LoginResult) => {
    if (result.access_token && result.me) {
      setAccessToken(result.access_token);
      setMe(result.me);
      setStatus("authenticated");
    }
  }, []);

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await api<LoginResult>("/auth/login", { method: "POST", body: { username, password }, auth: false });
      if (result.status === "mfa_required" && result.mfa_token) return { mfaToken: result.mfa_token };
      finish(result);
      return null;
    },
    [finish],
  );

  const verifyMfa = useCallback(
    async (mfaToken: string, code: string) => {
      finish(await api<LoginResult>("/auth/mfa/verify", { method: "POST", body: { mfa_token: mfaToken, code }, auth: false }));
    },
    [finish],
  );

  const logout = useCallback(async () => {
    try {
      await fetch("/api/v1/auth/logout", { method: "POST", headers: { "X-OBS-CSRF": "1" }, credentials: "same-origin" });
    } finally {
      setAccessToken(null);
      setMe(null);
      setStatus("anonymous");
    }
  }, []);

  const reloadMe = useCallback(async () => {
    setMe(await api<Me>("/auth/me"));
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      status,
      me,
      can: (p) => !!me && (me.superuser || me.permissions.includes(p)),
      login,
      verifyMfa,
      logout,
      reloadMe,
    }),
    [status, me, login, verifyMfa, logout, reloadMe],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
