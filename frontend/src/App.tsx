import type { ReactElement } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";
import { Card, PageHeader, Spinner } from "./components/ui";
import AppLayout from "./layout/AppLayout";
import { NAV } from "./layout/nav";
import AuditLogs from "./pages/admin/AuditLogs";
import Roles from "./pages/admin/Roles";
import SystemSettings from "./pages/admin/SystemSettings";
import Users from "./pages/admin/Users";
import Login from "./pages/auth/Login";
import NotYetBuilt from "./pages/NotYetBuilt";
import Overview from "./pages/Overview";
import Profile from "./pages/Profile";

/** Pages that exist. Every other navigation entry renders NotYetBuilt until its phase lands. */
const PAGES: Record<string, () => ReactElement> = {
  "/": Overview,
  "/admin/users": Users,
  "/admin/roles": Roles,
  "/admin/audit": AuditLogs,
  "/admin/settings": SystemSettings,
};

function RequireAuth({ children }: { children: ReactElement }) {
  const { auth, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="p-8"><Spinner /></div>;
  if (!auth || auth.state !== "full") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return children;
}

function RequirePermission({ permission, children }: { permission: string; children: ReactElement }) {
  const { can } = useAuth();
  if (!can(permission)) {
    return (
      <>
        <PageHeader title="No access" />
        <Card>
          <p className="text-sm text-slate-700">
            Your role does not include the <code className="rounded bg-slate-100 px-1">{permission}</code> permission
            needed for this page. Ask an administrator if you need access.
          </p>
        </Card>
      </>
    );
  }
  return children;
}

function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Card><p className="text-sm">This address does not match any page.</p></Card>
    </>
  );
}

export default function App() {
  const items = NAV.flatMap((s) => s.items);
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        {items.map((item) => {
          const Page = PAGES[item.path] ?? NotYetBuilt;
          return (
            <Route key={item.path} path={item.path}
              element={<RequirePermission permission={item.permission}><Page /></RequirePermission>} />
          );
        })}
        <Route path="/profile" element={<Profile />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
