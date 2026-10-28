import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";

import { ApiError, get, post } from "../api/client";
import type { AuthState } from "../api/types";

interface AuthContextValue {
  auth: AuthState | null;
  loading: boolean;
  can: (permission: string) => boolean;
  setAuth: (state: AuthState | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["auth"],
    queryFn: async () => {
      try {
        return await get<AuthState>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });

  const setAuth = useCallback((s: AuthState | null) => qc.setQueryData(["auth"], s), [qc]);
  const logout = useCallback(async () => {
    try {
      await post("/auth/logout");
    } finally {
      qc.clear();
      qc.setQueryData(["auth"], null);
    }
  }, [qc]);

  const value = useMemo<AuthContextValue>(() => {
    const perms = new Set(data?.state === "full" ? data.permissions : []);
    return {
      auth: data ?? null,
      loading: isLoading,
      can: (p: string) => perms.has(p),
      setAuth,
      logout,
    };
  }, [data, isLoading, setAuth, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
