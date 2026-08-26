import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { useSession } from "./lib/session";
import { LoginPage } from "./pages/Login";
import { OidcCallbackPage } from "./pages/OidcCallback";
import { OverviewPage } from "./pages/Overview";
import { EvidenceListPage } from "./pages/EvidenceList";
import { EvidenceDetailPage } from "./pages/EvidenceDetail";
import { ControlsListPage } from "./pages/ControlsList";
import { ControlDetailPage } from "./pages/ControlDetail";
import { GapsListPage } from "./pages/GapsList";
import { TasksListPage } from "./pages/TasksList";
import { AdminPage } from "./pages/Admin";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { identity } = useSession();
  if (!identity) return <Navigate to="/login" replace />;
  return children;
}

function RoleHome() {
  const { identity } = useSession();
  const isAuditor = identity?.kind === "auditor" || (identity?.kind === "oidc" && Boolean(identity.engagementId));
  const target = identity?.kind === "user" ? "/tasks" : isAuditor ? "/controls" : "/overview";
  return <Navigate to={target} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/oidc-callback" element={<OidcCallbackPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<RoleHome />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/evidence" element={<EvidenceListPage />} />
        <Route path="/evidence/:id" element={<EvidenceDetailPage />} />
        <Route path="/controls" element={<ControlsListPage />} />
        <Route path="/controls/:id" element={<ControlDetailPage />} />
        <Route path="/gaps" element={<GapsListPage />} />
        <Route path="/tasks" element={<TasksListPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
