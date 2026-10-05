import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, listFirmEngagements, type FirmEngagement, type Identity } from "../api/client";
import { completeLogin } from "../lib/pkce";
import { useSession } from "../lib/session";

type Oidc = Extract<Identity, { kind: "oidc" }>;

/** Landing point for the IdP redirect (VITE_OIDC_REDIRECT_URI). Exchanges the
 * code for a token, then asks the backend who this is — nobody types an id:
 *   - an auditee-side user goes straight in (the firm console answers 403);
 *   - a firm admin goes to the firm console;
 *   - an auditor is put into their one client, or picks among the clients they
 *     are staffed on (the backend only ever lists those). */
export function OidcCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { setIdentity } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [choice, setChoice] = useState<{ base: Oidc; engagements: FirmEngagement[] } | null>(null);

  const finish = (identity: Oidc, to: string) => {
    setIdentity(identity);
    navigate(to);
  };

  useEffect(() => {
    const code = params.get("code");
    if (!code) {
      setError("no authorization code in callback URL");
      return;
    }
    (async () => {
      const { accessToken, email } = await completeLogin(code);
      const base: Oidc = { kind: "oidc", token: accessToken, label: email ?? "SSO user" };
      let firmView: Awaited<ReturnType<typeof listFirmEngagements>>;
      try {
        firmView = await listFirmEngagements(base);
      } catch (err) {
        if (err instanceof ApiError && err.status === 403) return finish(base, "/overview");
        throw err;
      }
      const signedIn: Oidc = { ...base, role: firmView.role };
      if (firmView.role === "FIRM_ADMIN") return finish(signedIn, "/firm");
      const open = firmView.engagements.filter((e) => e.status === "ACTIVE");
      if (open.length === 1) return finish({ ...signedIn, engagementId: open[0].id }, "/controls");
      setChoice({ base: signedIn, engagements: open });
    })().catch((err) => setError((err as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  if (!choice) {
    return <div className="login-shell"><div className="card login-card">Signing you in…</div></div>;
  }

  return (
    <div className="login-shell">
      <div className="card login-card">
        <h1>Which client are you reviewing?</h1>
        {choice.engagements.length === 0 ? (
          <p className="muted">
            You are not staffed on any client yet. Ask your firm admin to add you to an engagement,
            then sign in again.
          </p>
        ) : (
          <div className="form-grid">
            {choice.engagements.map((e) => (
              <button key={e.id} className="btn btn-primary"
                      onClick={() => finish({ ...choice.base, engagementId: e.id }, "/controls")}>
                {e.org_name}
                <span className="muted"> — {e.frameworks.join(", ")} · {e.progress.open_gaps} open gaps</span>
              </button>
            ))}
          </div>
        )}
        <button className="btn" style={{ marginTop: 12 }} onClick={() => navigate("/login")}>Back to sign in</button>
      </div>
    </div>
  );
}
