import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RequireAuth, RequirePermission } from "./guards";

const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth.value }));

const baseMe = { password_change_required: false, mfa_enrollment_required: false };

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<div>login page</div>} />
        <Route path="/account/password" element={<div>change password page</div>} />
        <Route path="/account/mfa" element={<div>mfa page</div>} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<div>home</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("RequireAuth", () => {
  beforeEach(() => {
    auth.value = {};
  });

  it("sends anonymous visitors to the login page", () => {
    auth.value = { status: "anonymous", me: null };
    renderAt("/");
    expect(screen.getByText("login page")).toBeInTheDocument();
  });

  it("waits while the session is being restored", () => {
    auth.value = { status: "loading", me: null };
    renderAt("/");
    expect(screen.queryByText("home")).not.toBeInTheDocument();
    expect(screen.queryByText("login page")).not.toBeInTheDocument();
  });

  it("forces a password change before anything else", () => {
    auth.value = { status: "authenticated", me: { ...baseMe, password_change_required: true, mfa_enrollment_required: true } };
    renderAt("/");
    expect(screen.getByText("change password page")).toBeInTheDocument();
  });

  it("forces MFA enrolment once the password is changed", () => {
    auth.value = { status: "authenticated", me: { ...baseMe, mfa_enrollment_required: true } };
    renderAt("/");
    expect(screen.getByText("mfa page")).toBeInTheDocument();
  });

  it("lets a fully set-up user through", () => {
    auth.value = { status: "authenticated", me: baseMe };
    renderAt("/");
    expect(screen.getByText("home")).toBeInTheDocument();
  });
});

describe("RequirePermission", () => {
  it("renders children when any listed permission is held", () => {
    auth.value = { can: (p: string) => p === "audit.view" };
    render(<RequirePermission anyOf={["users.view", "audit.view"]}><p>secret</p></RequirePermission>);
    expect(screen.getByText("secret")).toBeInTheDocument();
  });

  it("shows an access-denied message otherwise", () => {
    auth.value = { can: () => false };
    render(<RequirePermission anyOf={["users.view"]}><p>secret</p></RequirePermission>);
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Access denied");
  });
});
