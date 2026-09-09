import { useNavigate } from "react-router-dom";
import { listNotifications, type NotificationItem } from "../api/client";
import { useApi } from "../lib/useApi";
import { DataTable, type Column } from "../components/DataTable";
import { Badge } from "../components/Badge";
import { PageTour } from "../components/PageTour";

const TOUR_STEPS = [
  {
    title: "Everything open, in one place",
    body: "Open tasks, evidence and unlock requests from your auditor, and evidence quietly going stale — combined into one feed so you don't have to check four different pages.",
    target: ".page-header",
  },
  {
    title: "Severity at a glance",
    body: "High-severity items (expired evidence, failed processing) need attention first. Medium covers things approaching a deadline. Info is a request from your auditor awaiting a reply.",
    target: ".data-table, .empty-state",
  },
  {
    title: "Click through to act",
    body: "Clicking a row takes you straight to the task, control, or evidence item it's about — this page is a router, not a destination.",
    target: ".data-table",
  },
] as const;

// No persisted read/unread state — this is "what's open right now," not "what
// changed since you last looked." See app/routers/notifications.py's docstring
// for why that's a deliberate v1 cut, not an oversight.
export function NotificationsPage() {
  const navigate = useNavigate();
  const notifications = useApi(() => listNotifications(), []);

  const columns: Column<NotificationItem>[] = [
    { key: "severity", header: "", render: (n) => <Badge value={n.severity.toUpperCase()} /> },
    { key: "message", header: "Notification", render: (n) => n.message },
    { key: "at", header: "When", render: (n) => new Date(n.at).toLocaleString() },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Notifications</h2>
          <p>Everything open right now that needs a look — tasks, requests from your auditor, and evidence going stale.</p>
        </div>
        <PageTour id="notifications" steps={TOUR_STEPS} />
      </div>
      {notifications.error && <div className="alert alert-error">{notifications.error}</div>}
      <DataTable
        columns={columns}
        rows={notifications.data?.items ?? []}
        onRowClick={(n) => navigate(n.link)}
        emptyLabel="Nothing needs your attention right now."
      />
    </div>
  );
}
