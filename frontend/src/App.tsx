import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { useSession } from "./lib/session";
import { LoginPage } from "./pages/Login";
import { OidcCallbackPage } from "./pages/OidcCallback";
import { PitchPage } from "./pages/Pitch";
import { OverviewPage } from "./pages/Overview";
import { EvidenceListPage } from "./pages/EvidenceList";
import { EvidenceDetailPage } from "./pages/EvidenceDetail";
import { ControlsListPage } from "./pages/ControlsList";
import { ControlDetailPage } from "./pages/ControlDetail";
import { GapsListPage } from "./pages/GapsList";
import { TasksListPage } from "./pages/TasksList";
import { AdminPage } from "./pages/Admin";
import { FirmPage } from "./pages/Firm";
import { NotificationsPage } from "./pages/Notifications";
import { ActivityPage } from "./pages/Activity";
import { GlossaryPage } from "./pages/Glossary";
import { AiCompliancePage } from "./pages/AiCompliance";
import { DpdpPage } from "./pages/Dpdp";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { identity } = useSession();
  if (!identity) return <Navigate to="/login" replace />;
  return children;
}

function RoleHome() {
  const { identity } = useSession();
  // A firm-side caller lands on its own console first: which clients am I on.
  // Only once it has opened one (engagementId set) is the auditee-shaped
  // review queue the right home.
  if (identity?.kind === "firm") return <Navigate to="/firm" replace />;
  const isAuditor = identity?.kind === "auditor" || (identity?.kind === "oidc" && Boolean(identity.engagementId));
  const target = identity?.kind === "user" ? "/tasks" : isAuditor ? "/controls" : "/overview";
  return <Navigate to={target} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/pitch" element={<PitchPage />} />
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
        <Route path="/firm" element={<FirmPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/glossary" element={<GlossaryPage />} />
        <Route path="/ai-compliance" element={<AiCompliancePage />} />
        <Route path="/dpdp" element={<DpdpPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
