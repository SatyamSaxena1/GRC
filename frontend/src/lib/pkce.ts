// Minimal Authorization Code + PKCE flow for a public SPA client (no client
// secret — Authentik's recommended setup for a browser app). Hand-rolled with
// the Web Crypto API already built into every browser rather than adding an
// OIDC client library for what is a handful of calls.

const VERIFIER_KEY = "grc.oidc.code_verifier";

function base64url(bytes: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(digest);
}

export function oidcConfigured(): boolean {
  const env = import.meta.env;
  return Boolean(env.VITE_OIDC_AUTHORIZE_URL && env.VITE_OIDC_TOKEN_URL && env.VITE_OIDC_CLIENT_ID);
}

/** Redirects the browser to the IdP. Never returns. */
export async function startLogin(): Promise<void> {
  const env = import.meta.env;
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)).buffer);
  sessionStorage.setItem(VERIFIER_KEY, verifier);

  const redirectUri = env.VITE_OIDC_REDIRECT_URI || `${window.location.origin}/oidc-callback`;
  const url = new URL(env.VITE_OIDC_AUTHORIZE_URL as string);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", env.VITE_OIDC_CLIENT_ID as string);
  url.searchParams.set("redirect_uri", redirectUri);
  url.searchParams.set("scope", "openid email profile");
  url.searchParams.set("code_challenge", await challengeFor(verifier));
  url.searchParams.set("code_challenge_method", "S256");
  window.location.assign(url.toString());
}

/** Exchanges an authorization-code callback for tokens. Throws on any failure. */
export async function completeLogin(code: string): Promise<{ accessToken: string; email: string | null }> {
  const env = import.meta.env;
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!verifier) throw new Error("no PKCE verifier for this session — start sign-in again");
  sessionStorage.removeItem(VERIFIER_KEY);

  const redirectUri = env.VITE_OIDC_REDIRECT_URI || `${window.location.origin}/oidc-callback`;
  const res = await fetch(env.VITE_OIDC_TOKEN_URL as string, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code", code, redirect_uri: redirectUri,
      client_id: env.VITE_OIDC_CLIENT_ID as string, code_verifier: verifier,
    }),
  });
  if (!res.ok) throw new Error(`token exchange failed: ${res.status}`);
  const body = await res.json();
  const accessToken = body.access_token as string;
  return { accessToken, email: emailFromToken(accessToken) };
}

/** Reads the email claim for display only — this is never how the backend
 * establishes trust; it verifies the signature itself (app/oidc.py). */
function emailFromToken(token: string): string | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return payload.email ?? null;
  } catch {
    return null;
  }
}
