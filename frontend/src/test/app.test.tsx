import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { NAV } from "../layout/nav";
import { mockFetch, modules, renderApp, viewer } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "opsbrain_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("navigation", () => {
  it("contains every section and page from the architecture document §13", () => {
    expect(NAV.map((s) => s.label)).toEqual([
      "Overview", "Host Management", "Logging", "Monitoring", "AI / AIOps", "Automation", "Incidents",
      "Reports", "Retention & Archive", "Integrations", "Administration",
    ]);
    const count = (key: string) => NAV.find((s) => s.key === key)!.items.length;
    expect(count("hosts")).toBe(4);
    expect(count("logging")).toBe(12);
    expect(count("monitoring")).toBe(12);
    expect(count("ai")).toBe(6);
    expect(count("automation")).toBe(5);
    expect(count("reports")).toBe(6);
    expect(count("admin")).toBe(4);
    const paths = NAV.flatMap((s) => s.items.map((i) => i.path));
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("marks only Logging and Monitoring as separate workspaces", () => {
    expect(NAV.filter((s) => s.workspace).map((s) => s.key)).toEqual(["logging", "monitoring"]);
  });
});

describe("api client", () => {
  it("sends the CSRF cookie value on mutations and not on reads", async () => {
    document.cookie = "opsbrain_csrf=tok123";
    const calls = mockFetch({
      "POST /api/v1/x": () => ({ body: {} }),
      "GET /api/v1/x": () => ({ body: {} }),
    });
    await api("/x", { method: "POST", json: { a: 1 } });
    await api("/x");
    expect(new Headers(calls[0].init?.headers).get("X-CSRF-Token")).toBe("tok123");
    expect(new Headers(calls[1].init?.headers).get("X-CSRF-Token")).toBeNull();
  });

  it("turns FastAPI validation errors into readable messages", async () => {
    mockFetch({
      "POST /api/v1/x": () => ({ status: 422, body: { detail: [{ loc: ["body", "email"], msg: "invalid email" }] } }),
    });
    await expect(api("/x", { method: "POST", json: {} })).rejects.toThrow("email: invalid email");
  });
});

describe("sign-in flow", () => {
  it("walks password → two-factor code → overview", async () => {
    let signedIn = false;
    const calls = mockFetch({
      "GET /api/v1/auth/me": () => (signedIn ? { body: viewer } : { status: 401, body: { detail: "Not signed in" } }),
      "POST /api/v1/auth/login": () => ({ body: { ...viewer, state: "mfa_required", permissions: [] } }),
      "POST /api/v1/auth/mfa/verify": () => {
        signedIn = true;
        return { body: viewer };
      },
      "GET /api/v1/system/modules": () => ({ body: modules }),
      "GET /api/v1/settings/public": () => ({ body: { platform_name: "AI-OpsBrain" } }),
    });
    renderApp("/");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username or email"), "vera");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.type(await screen.findByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(await screen.findByText("Core platform")).toBeInTheDocument();
    const login = calls.find((c) => c.path === "/api/v1/auth/login")!;
    expect(JSON.parse(String(login.init?.body))).toEqual({ username: "vera", password: "correct horse battery" });
  });

  it("shows the server's error on a wrong password", async () => {
    mockFetch({
      "GET /api/v1/auth/me": () => ({ status: 401, body: { detail: "Not signed in" } }),
      "POST /api/v1/auth/login": () => ({ status: 401, body: { detail: "Invalid username or password, or the account is locked." } }),
    });
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username or email"), "vera");
    await user.type(screen.getByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password");
  });
});

describe("authorisation in the UI", () => {
  it("hides admin navigation and blocks admin pages for a Viewer", async () => {
    mockFetch({
      "GET /api/v1/auth/me": () => ({ body: viewer }),
      "GET /api/v1/system/modules": () => ({ body: modules }),
      "GET /api/v1/settings/public": () => ({ body: { platform_name: "AI-OpsBrain" } }),
    });
    renderApp("/admin/users");
    expect(await screen.findByRole("heading", { name: "No access" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Administration/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Logging/ })).toBeInTheDocument();
  });

  it("is honest about pages that are not built yet", async () => {
    mockFetch({
      "GET /api/v1/auth/me": () => ({ body: viewer }),
      "GET /api/v1/system/modules": () => ({ body: modules }),
      "GET /api/v1/settings/public": () => ({ body: { platform_name: "AI-OpsBrain" } }),
    });
    renderApp("/logging/explorer");
    expect(await screen.findByText(/not available in this release yet/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/opsbrainctl install logging/)).toBeInTheDocument());
  });
});
