import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

type Handler = (init: RequestInit | undefined) => { status?: number; body: unknown };

/** Route-table fetch mock: keys are "METHOD /api/v1/path" (query string ignored). */
export function mockFetch(routes: Record<string, Handler>) {
  const calls: { method: string; path: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "https://opsbrain.test");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path: url.pathname, init });
    const handler = routes[`${method} ${url.pathname}`];
    if (!handler) return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 });
    const { status = 200, body } = handler(init);
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

export function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const viewer = {
  state: "full",
  user: {
    id: "u1", username: "vera", email: "vera@example.test", full_name: "Vera", is_active: true, mfa_enabled: false,
    must_change_password: false, roles: ["Viewer"], locked_until: null, last_login_at: null, created_at: "2026-10-01T00:00:00Z",
  },
  permissions: ["dashboard.view", "hosts.view", "logs.view", "metrics.view"],
  mfa_required_by_policy: false,
};

export const modules = {
  version: "0.1.0",
  modules: [
    { key: "core", name: "Core platform", description: "", installed: true, info: {} },
    { key: "logging", name: "Logging", description: "", installed: false, info: null },
    { key: "monitoring", name: "Monitoring", description: "", installed: false, info: null },
  ],
};
