import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Spinner } from "./ui";

/** Everything below requires a signed-in user; pending password change / MFA enrolment is enforced first. */
export function RequireAuth() {
  const { status, me } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Spinner label="Restoring your session" />;
  if (status === "anonymous" || !me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (me.password_change_required && location.pathname !== "/account/password") return <Navigate to="/account/password" replace />;
  if (!me.password_change_required && me.mfa_enrollment_required && location.pathname !== "/account/mfa") return <Navigate to="/account/mfa" replace />;
  return <Outlet />;
}

export function RequirePermission({ anyOf, children }: { anyOf: string[]; children: React.ReactNode }) {
  const { can } = useAuth();
  if (!anyOf.some(can)) {
    return (
      <div role="alert" className="rounded-lg border border-line bg-surface p-6">
        <h1 className="text-lg font-semibold">Access denied</h1>
        <p className="mt-1 text-sm text-muted">Your role does not include permission to view this page. Ask an administrator if you need it.</p>
      </div>
    );
  }
  return <>{children}</>;
}
