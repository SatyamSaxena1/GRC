import { useState } from "react";
import {
  ApiError, getConnections, removeChatWebhook, removeGithub, saveChatWebhook, saveGithub, testChatWebhook, testGithub,
  makeAwsToken, removeAws, type ConnectionView,
} from "../api/client";
import { useApi } from "../lib/useApi";

const STATUS_LABEL: Record<ConnectionView["status"], string> = {
  NONE: "Not connected", UNTESTED: "Saved, not tested yet", OK: "Working", FAILED: "Failed",
};

/** What an organisation connects itself (ADR-044). The address is write-only: it is masked while you paste it and the
 *  server never sends it back, only a hint ("discord.com ...Ab12") and the result of the last test. */
export function ConnectionsPage() {
  const state = useApi(() => getConnections(), []);
  const [url, setUrl] = useState("");
  const [ghToken, setGhToken] = useState("");
  const [ghRepos, setGhRepos] = useState("");
  const [awsToken, setAwsToken] = useState<string | null>(null);
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
  const aws = state.data.connections.find((c) => c.kind === "AWS_READONLY");
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
        <div className="card" id="aws" style={{ marginTop: 16 }}>
          <strong>AWS: security settings evidence</strong>
          <p className="stat-sub">
            You run a small read-only script in your own AWS account. It checks four things (encryption at rest, MFA on
            admin users, a logging trail, backups) and sends us only four yes/no answers. We hold no AWS key of yours and
            call nothing in your account.
          </p>
          <p>
            <strong>{STATUS_LABEL[aws.status]}</strong>
            {aws.configured && <span className="muted"> {aws.hint}</span>}
            {aws.last_tested_at && <span className="muted"> last received {new Date(aws.last_tested_at).toLocaleString()}</span>}
          </p>

          {awsToken && (
            <div className="alert alert-info">
              <p>Copy this upload token now. It is shown once and only a fingerprint is kept. Making a new one ends this one.</p>
              <input readOnly value={awsToken} aria-label="Upload token" onFocus={(e) => e.currentTarget.select()} />
              <button className="btn btn-sm" onClick={() => void navigator.clipboard?.writeText(awsToken)}>Copy token</button>
            </div>
          )}
          {aws.configured && (
            <ol style={{ fontSize: 13, margin: "8px 0 8px 18px" }}>
              <li>In AWS, give the user or role that will run the script these read-only permissions: s3:ListAllMyBuckets,
                s3:GetEncryptionConfiguration, ec2:GetEbsEncryptionByDefault, rds:DescribeDBInstances, iam:GetAccountSummary,
                iam:ListEntitiesForPolicy, iam:GetGroup, iam:ListMFADevices, cloudtrail:DescribeTrails,
                cloudtrail:GetTrailStatus, backup:ListBackupPlans.</li>
              <li>Download the script: <span className="mono">app/collectors/aws_readonly.py</span> from the project repository
                (needs Python and boto3).</li>
              <li>Run it where your AWS credentials are set:
                <div className="mono">python aws_readonly.py --url {window.location.origin} --region ap-south-1 --token YOUR_TOKEN</div></li>
              <li>Add <span className="mono">--dry-run</span> first to see the answers without uploading. Run it again whenever you want fresh evidence.</li>
            </ol>
          )}
          <div style={{ marginTop: 8 }}>
            <button className="btn btn-primary" disabled={busy || !keyOn}
              onClick={() => run(async () => { const r = await makeAwsToken(); setAwsToken(r.new_token); })}>
              {aws.configured ? "Make a new token" : "Create my upload token"}
            </button>{" "}
            {aws.configured && (
              <button className="btn btn-danger" disabled={busy}
                onClick={() => { if (window.confirm("Remove this connection? Uploads with this token will stop working.")) void run(async () => { await removeAws(); setAwsToken(null); }); }}>
                Remove
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
