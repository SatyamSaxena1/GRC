import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxying every backend prefix in dev means the app never has to touch CORS
// config on the FastAPI side — the browser only ever talks to localhost:5173.
const BACKEND = "http://localhost:8000";
const PROXIED_PREFIXES = ["/admin", "/firm", "/evidence", "/controls", "/gaps", "/tasks", "/requests", "/audit", "/analytics", "/health", "/notifications", "/export", "/activity", "/glossary"];

// /evidence and /controls happen to double as SPA route prefixes today
// (/evidence/:id, /controls/:id) — but that's exactly the kind of thing a
// future route addition (/tasks/:id, /gaps/:id, ...) could reintroduce without
// anyone remembering to special-case it here. So the bypass below applies to
// every proxied prefix, not just the ones known to collide right now: a real
// browser page navigation (GET, Accept: text/html) should never be routed to
// the JSON API regardless of path — our own client.ts never sends that Accept
// header, so this can't misroute a real app request, only rescue a bare
// page-load (refresh, bookmark, shared link, a redirect that isn't SPA-aware)
// that would otherwise 422 on a missing Authorization header.
function bypassPageNavigations(req: { method?: string; headers: Record<string, string | string[] | undefined> }) {
  const accept = req.headers.accept;
  const wantsHtml = typeof accept === "string" && accept.includes("text/html");
  if (req.method === "GET" && wantsHtml) return "/index.html";
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Vite 5 rejects requests whose Host header it doesn't recognize — needed
    // so a tunnel (ngrok etc.) reaching this dev server isn't blocked as an
    // untrusted host. Fine for local/dev tunneling; not meant for a real
    // production deploy of this dev server.
    allowedHosts: true,
    proxy: Object.fromEntries(
      PROXIED_PREFIXES.map((prefix) => [
        prefix,
        { target: BACKEND, changeOrigin: true, bypass: bypassPageNavigations },
      ])
    ),
  },
});
