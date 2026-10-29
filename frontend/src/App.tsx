import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RequireAuth, RequirePermission } from "./components/guards";
import AuditLogs from "./pages/AuditLogs";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import Overview from "./pages/Overview";
import Profile, { ForcedMfaSetup, ForcedPasswordChange } from "./pages/Profile";
import Roles from "./pages/Roles";
import SystemSettings from "./pages/SystemSettings";
import Users from "./pages/Users";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="account" element={<Profile />} />
          <Route path="account/password" element={<ForcedPasswordChange />} />
          <Route path="account/mfa" element={<ForcedMfaSetup />} />
          <Route path="admin/users" element={<RequirePermission anyOf={["users.view", "users.manage"]}><Users /></RequirePermission>} />
          <Route path="admin/roles" element={<RequirePermission anyOf={["roles.view", "roles.manage"]}><Roles /></RequirePermission>} />
          <Route path="admin/audit" element={<RequirePermission anyOf={["audit.view"]}><AuditLogs /></RequirePermission>} />
          <Route path="admin/settings" element={<RequirePermission anyOf={["settings.view", "settings.manage", "system.view"]}><SystemSettings /></RequirePermission>} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}
