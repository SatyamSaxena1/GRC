import { useState } from "react";
import {
  ApiError, getConnections, removeChatWebhook, removeGithub, saveChatWebhook, saveGithub, testChatWebhook, testGithub,
  makeUploadToken, removeUpload, type ConnectionView,
} from "../api/client";
import { useApi } from "../lib/useApi";

const STATUS_LABEL: Record<ConnectionView["status"], string> = {
  NONE: "Not connected", UNTESTED: "Saved, not tested yet", OK: "Working", FAILED: "Failed",
};

/** Which clauses a source's evidence counts toward, read from the content packs on the server. A mapping an AI drafted
 *  and no person has reviewed yet is marked, so nobody mistakes it for an expert reading. */
function Feeds({ feeds }: { feeds: ConnectionView["feeds"] }) {
  if (!feeds.length) return null;
  return (
    <details style={{ margin: "8px 0" }}>
      <summary>Counts toward {feeds.length} clause{feeds.length === 1 ? "" : "s"}</summary>
      <ul style={{ fontSize: 13, margin: "6px 0 0 18px" }}>
        {feeds.map((f) => (
          <li key={`${f.framework}-${f.clause}`}>
            <span className="mono">{f.framework} {f.clause}</span> {f.title}
            {!f.reviewed && <span className="muted"> (drafted by AI, awaiting review)</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** A source whose evidence the customer uploads from their own script (ADR-049, ADR-050). The upload token is
 *  shown once; only a fingerprint is kept on the server. */
function UploadCard({ conn, source, title, blurb, permissions, permissionsWhere, script, command, keyOn, busy, run }: {
  conn: ConnectionView; source: "aws" | "m365" | "hrms" | "google-workspace"; title: string; blurb: string; permissions: string; permissionsWhere: string;
  script: string; command: string; keyOn: boolean; busy: boolean; run: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [token, setToken] = useState<string | null>(null);
  return (
    <div className="card" id={source} style={{ marginTop: 16 }}>
      <strong>{title}</strong>
      <p className="stat-sub">{blurb}</p>
      <Feeds feeds={conn.feeds} />
      <p>
        <strong>{STATUS_LABEL[conn.status]}</strong>
        {conn.configured && <span className="muted"> {conn.hint}</span>}
        {conn.last_tested_at && <span className="muted"> last received {new Date(conn.last_tested_at).toLocaleString()}</span>}
      </p>
      {token && (
        <div className="alert alert-info">
          <p>Copy this upload token now. It is shown once and only a fingerprint is kept. Making a new one ends this one.</p>
          <input readOnly value={token} aria-label="Upload token" onFocus={(e) => e.currentTarget.select()} />
          <button className="btn btn-sm" onClick={() => void navigator.clipboard?.writeText(token)}>Copy token</button>
        </div>
      )}
      {conn.configured && (
        <ol style={{ fontSize: 13, margin: "8px 0 8px 18px" }}>
          <li>{permissionsWhere}{permissions ? ` ${permissions}.` : ""}</li>
          <li>Download the script <span className="mono">app/collectors/{script}</span> from the project repository.</li>
          <li>Run it (the token goes in the environment, not on the command line, so it is not left in your shell history or process list): <div className="mono" style={{ whiteSpace: "pre-wrap" }}>{command}</div></li>
          <li>Add <span className="mono">--dry-run</span> first to see the answers without uploading. Run it again whenever you want fresh evidence.</li>
        </ol>
      )}
      <div style={{ marginTop: 8 }}>
        <button className="btn btn-primary" disabled={busy || !keyOn}
          onClick={() => run(async () => { const r = await makeUploadToken(source); setToken(r.new_token); })}>
          {conn.configured ? "Make a new token" : "Create my upload token"}
        </button>{" "}
        {conn.configured && (
          <button className="btn btn-danger" disabled={busy}
            onClick={() => { if (window.confirm("Remove this connection? Uploads with this token will stop working.")) void run(async () => { await removeUpload(source); setToken(null); }); }}>
            Remove
          </button>
        )}
      </div>
    </div>
  );
}

/** What an organisation connects itself (ADR-044). The address is write-only: it is masked while you paste it and the
 *  server never sends it back, only a hint ("discord.com ...Ab12") and the result of the last test. */
export function ConnectionsPage() {
  const state = useApi(() => getConnections(), []);
  const [url, setUrl] = useState("");
  const [ghToken, setGhToken] = useState("");
  const [ghRepos, setGhRepos] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    setBusy(true);
    try { await fn(); state.reload(); } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : (err as Error).message);
    } finally { setBusy(false); }
  };
  if (state.error) return <div className="alert alert-error">{state.error}</div>;
  if (!state.data) return <p className="muted">Loading…</p>;

  const chat = state.data.connections.find((c) => c.kind === "CHAT_WEBHOOK") as ConnectionView;
  const gh = state.data.connections.find((c) => c.kind === "GITHUB_CHANGE_CONTROL");
  const aws = state.data.connections.find((c) => c.kind === "AWS_PUSH");
  const m365 = state.data.connections.find((c) => c.kind === "M365_PUSH");
  const hrms = state.data.connections.find((c) => c.kind === "HRMS_PUSH");
  const gws = state.data.connections.find((c) => c.kind === "GOOGLE_WORKSPACE_PUSH");
  const keyOn = state.data.key_configured;
  const repoList = ghRepos.split(/[\s,]+/).filter(Boolean);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Connections</h2>
          <p>Connect the places your team already works. What you paste here is stored encrypted and never shown again.</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {!keyOn && (
        <div className="alert alert-info">
          Connections are switched off until whoever runs this server sets <code>CONNECTIONS_KEY</code> (a one-time
          setting). Until then nothing can be saved, not even in plain text.
        </div>
      )}

      <div className="card" id="chat-webhook">
        <strong>Team chat: Discord or Slack</strong>
        <p className="stat-sub">
          Your instant alerts (a task assigned, a control locked, evidence requested) and the Monday summary go to this
          channel. The summary is counts only. The "task assigned" alert names the person and the task, so use a
          channel that only your own team can read.
        </p>

        <p>
          <strong>{STATUS_LABEL[chat.status]}</strong>
          {chat.configured && <span className="muted"> {chat.hint}</span>}
          {chat.last_tested_at && <span className="muted"> last tested {new Date(chat.last_tested_at).toLocaleString()}</span>}
        </p>
        {chat.status === "FAILED" && chat.last_error && <p className="error">{chat.last_error}</p>}

        <label htmlFor="chat-url">{chat.configured ? "Replace the address" : "Webhook address"}</label>
        <input id="chat-url" type="password" autoComplete="off" spellCheck={false} value={url} disabled={!keyOn}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://discord.com/api/webhooks/… or https://hooks.slack.com/services/…" />
        <div style={{ marginTop: 8 }}>
          <button className="btn btn-primary" disabled={busy || !keyOn || url.trim().length < 10}
            onClick={() => run(async () => { await saveChatWebhook(url.trim()); setUrl(""); })}>
            {chat.configured ? "Replace" : "Save"}
          </button>{" "}
          {chat.configured && (
            <>
              <button className="btn" disabled={busy || !keyOn} onClick={() => run(() => testChatWebhook())}>Send a test message</button>{" "}
              <button className="btn btn-danger" disabled={busy}
                onClick={() => { if (window.confirm("Remove this connection? Alerts will stop going to this channel.")) void run(() => removeChatWebhook()); }}>
                Remove
              </button>
            </>
          )}
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
          Discord: channel settings, Integrations, Webhooks, New Webhook, Copy Webhook URL. Slack: create an Incoming
          Webhook for the channel and copy its URL. Only Discord and Slack addresses are accepted.
        </p>
      </div>

      {gh && (
        <div className="card" id="github" style={{ marginTop: 16 }}>
          <strong>GitHub: change control evidence</strong>
          <p className="stat-sub">
            Collect how code reaches production (reviews, checks, deployments) from the repositories you name, using a
            token you create. Use a read-only token limited to those repositories. It is stored encrypted, only ever
            sent to GitHub, and never shown again.
          </p>
          <Feeds feeds={gh.feeds} />
          <p>
            <strong>{STATUS_LABEL[gh.status]}</strong>
            {gh.configured && <span className="muted"> {gh.hint}</span>}
            {gh.last_tested_at && <span className="muted"> last tested {new Date(gh.last_tested_at).toLocaleString()}</span>}
          </p>
          {gh.status === "FAILED" && gh.last_error && <p className="error">{gh.last_error}</p>}

          <label htmlFor="gh-token">{gh.configured ? "Replace the token" : "Access token"}</label>
          <input id="gh-token" type="password" autoComplete="off" spellCheck={false} value={ghToken} disabled={!keyOn}
            onChange={(e) => setGhToken(e.target.value)} placeholder="ghp_… or github_pat_…" />
          <label htmlFor="gh-repos" style={{ marginTop: 8 }}>Repositories (owner/name, one per line, up to 10)</label>
          <textarea id="gh-repos" rows={3} value={ghRepos} disabled={!keyOn} onChange={(e) => setGhRepos(e.target.value)}
            placeholder={"acme/api\nacme/web"} />
          <div style={{ marginTop: 8 }}>
            <button className="btn btn-primary" disabled={busy || !keyOn || ghToken.trim().length < 10 || repoList.length === 0}
              onClick={() => run(async () => { await saveGithub(ghToken.trim(), repoList); setGhToken(""); setGhRepos(""); })}>
              {gh.configured ? "Replace" : "Save"}
            </button>{" "}
            {gh.configured && (
              <>
                <button className="btn" disabled={busy || !keyOn} onClick={() => run(() => testGithub())}>Check access</button>{" "}
                <button className="btn btn-danger" disabled={busy}
                  onClick={() => { if (window.confirm("Remove this connection? Evidence will stop being collected from these repositories.")) void run(() => removeGithub()); }}>
                  Remove
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {aws && (
        <UploadCard conn={aws} source="aws" title="AWS: security settings evidence" keyOn={keyOn} busy={busy} run={run}
          blurb="You run a small read-only script in your own AWS account. It checks four things (encryption at rest, MFA on admin users, a logging trail, backups) and sends us only four yes/no answers. We hold no AWS key of yours and call nothing in your account."
          permissions="s3:ListAllMyBuckets, s3:GetEncryptionConfiguration, ec2:GetEbsEncryptionByDefault, ec2:DescribeVolumes, rds:DescribeDBInstances, iam:GetAccountSummary, iam:ListEntitiesForPolicy, iam:GetGroup, iam:ListMFADevices, cloudtrail:DescribeTrails, cloudtrail:GetTrailStatus, backup:ListBackupPlans, backup:ListBackupSelections"
          permissionsWhere="In AWS, give the user or role that will run the script these read-only permissions:"
          script="aws_readonly.py"
          command={`export GRC_UPLOAD_TOKEN=YOUR_TOKEN\npython aws_readonly.py --url ${window.location.origin} --region ap-south-1`} />
      )}
      {m365 && (
        <UploadCard conn={m365} source="m365" title="Microsoft 365: security settings evidence" keyOn={keyOn} busy={busy} run={run}
          blurb="You run a small read-only script against your own Microsoft 365 tenant. It checks two things (every administrator has multi-factor authentication registered, and the directory audit log has recorded activity in the last 30 days) and sends us only two yes/no answers. We hold no Microsoft credential of yours."
          permissions="Microsoft Graph application permission AuditLog.Read.All (admin consent), on an app registration you create"
          permissionsWhere="In Microsoft Entra, create an app registration with a client secret and grant it:"
          script="m365_readonly.py"
          command={`export GRC_UPLOAD_TOKEN=YOUR_TOKEN\npython m365_readonly.py --url ${window.location.origin} --tenant YOUR_TENANT_ID --client-id YOUR_APP_ID`} />
      )}
      {gws && (
        <UploadCard conn={gws} source="google-workspace" title="Google Workspace: security settings evidence" keyOn={keyOn} busy={busy} run={run}
          blurb="You run a small read-only script on your own computer, signed in as a Google Workspace super administrator. It checks two things (every super administrator has 2-step verification enforced, and the admin audit log has recorded activity in the last 30 days) and sends us only two yes/no answers. We hold no Google credential of yours."
          permissions="The scopes admin.directory.user.readonly and admin.reports.audit.readonly, on an OAuth client you create in your own Google Cloud project"
          permissionsWhere="In your Google Cloud console, create an OAuth client and get a read-only access token or refresh token for these two scopes (see the guide in the project repository, docs/operations/gworkspace-upload.md):"
          script="gworkspace_readonly.py"
          command={`export GRC_UPLOAD_TOKEN=YOUR_TOKEN
export GOOGLE_ACCESS_TOKEN=YOUR_GOOGLE_TOKEN
python gworkspace_readonly.py --url ${window.location.origin}`} />
      )}
      {hrms && (
        <UploadCard conn={hrms} source="hrms" title="HR: leavers who still have access" keyOn={keyOn} busy={busy} run={run}
          blurb="You run a small script on your own computer against two lists you export: the people who have left, and the accounts that are still active. It counts the leavers who still have an active account and sends us only that one number. No names or email addresses leave your computer."
          permissions=""
          permissionsWhere="Export two CSV files, each with an email column: leavers.csv from your HR system (people who left in the period) and accounts.csv from your directory (Entra, Google Workspace, Okta or similar: every account that is still active)."
          script="hr_leavers.py"
          command={`export GRC_UPLOAD_TOKEN=YOUR_TOKEN\npython hr_leavers.py --url ${window.location.origin} --leavers leavers.csv --accounts accounts.csv`} />
      )}
    </div>
  );
}
