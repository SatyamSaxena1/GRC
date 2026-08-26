import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { completeLogin } from "../lib/pkce";
import { useSession } from "../lib/session";

/** Landing point for the Authentik redirect (VITE_OIDC_REDIRECT_URI). Exchanges
 * the code for a token, then asks for an engagement id only if this identity
 * turns out to be an auditor — the backend is the one that actually knows the
 * role (see app/oidc.py); this page just gives the auditor a place to enter it. */
export function OidcCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { setIdentity } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [pendingToken, setPendingToken] = useState<{ token: string; email: string | null } | null>(null);
  const [engagementId, setEngagementId] = useState("");

  useEffect(() => {
    const code = params.get("code");
    if (!code) {
      setError("no authorization code in callback URL");
      return;
    }
    completeLogin(code)
      .then(({ accessToken, email }) => setPendingToken({ token: accessToken, email }))
      .catch((err) => setError((err as Error).message));
  }, [params]);

  if (error) {
    return (
      <div className="login-shell">
        <div className="card login-card">
          <div className="alert alert-error">{error}</div>
          <button className="btn btn-primary" onClick={() => navigate("/login")}>Back to sign in</button>
        </div>
      </div>
    );
  }

  if (!pendingToken) {
    return <div className="login-shell"><div className="card login-card">Signing you in…</div></div>;
  }

  const enter = (asAuditor: boolean) => {
    setIdentity({
      kind: "oidc", token: pendingToken.token,
      label: pendingToken.email ?? "SSO user",
      engagementId: asAuditor ? engagementId.trim() : undefined,
    });
    navigate(asAuditor ? "/controls" : "/overview");
  };

  return (
    <div className="login-shell">
      <div className="card login-card">
        <h1>Signed in as {pendingToken.email ?? "unknown"}</h1>
        <p className="muted">
          If this identity is an auditor, an engagement id is required — the backend rejects
          an auditor request without one (see docs/adr/011-oidc-auth.md).
        </p>
        <div className="form-grid">
          <div>
            <label>Engagement id (auditors only)</label>
            <input value={engagementId} onChange={(e) => setEngagementId(e.target.value)}
                  placeholder="leave blank if you are not an auditor" />
          </div>
          {engagementId.trim() ? (
            <button className="btn btn-primary" onClick={() => enter(true)}>Continue as auditor</button>
          ) : (
            <button className="btn btn-primary" onClick={() => enter(false)}>Continue</button>
          )}
        </div>
      </div>
    </div>
  );
}
