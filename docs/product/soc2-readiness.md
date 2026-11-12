# Our own SOC 2: where we stand, and what to decide

Written 12 Nov 2026. This is a readiness check of **our own company and the live service**, not of the product's rules. It
is based on this repository, the live site's responses, and a run of the product against an empty organisation. Nothing was
changed on the live site to produce it, except that I sent eight wrong operator keys to it to test whether anything slowed
them down (nothing did; see "Fixed").

SOC 2 is a report from an independent audit firm that our controls are in place (Type 1: on one day) or worked over a
period (Type 2: usually 3 to 12 months). We have not started either, and this document does not start one.

## 1. What the product shows for the frameworks

Run against a fresh organisation subscribed to ISO 27001, SOC 2 and DPDP:

| Framework | Clauses listed | Judged by a rule from evidence | Met by a named person's statement |
|---|---|---|---|
| ISO 27001:2022 | 93 | 12 | 81 |
| SOC 2 (Security criteria) | 32 of 33 (CC7.5 is in draft PR 109) | 11 | 21 |
| DPDP | 9 | 9 | 0 |

Most of the work for ourselves is therefore **statements with proof behind them**, not rules, until more rules are written.

## 2. The company and the service: what we have and what is missing

| Area | What we have today | What is missing, in plain words |
|---|---|---|
| Change management | Every change is a reviewed pull request with a CI gate; deploys go through a hook after tests pass; branch rules exist | Nothing urgent. This is our strongest area |
| Access to production | Operator key; Auth0 login for people; row-level security between customers | Confirm multi-factor sign-in is **enforced** on the Auth0 tenant and on the Render, Supabase and GitHub accounts. I could not check it, and no document in the repo says it is |
| Hosting and uptime | Render free instance, Cloudflare in front | Free instances sleep after idle and can delay a request by 50+ seconds, with no uptime promise. Customers need a plan with a stated availability |
| Database and backups | Supabase project `grc-prod` | Backups and a **tested restore** are not documented anywhere. I have not checked the Supabase plan. `render.yaml` still describes a Render free database that is deleted after 30 days, which may not match what is live: check |
| Logging | The app's own audit log is hash-chained and tamper-evident | The request access log is written to a file on the server's temporary disk, which is lost on every deploy. DPDP asks for logs kept at least a year. Logs need to go to a durable place |
| Vulnerabilities | Tests and a change-control gate | **No dependency or code scanning in CI** (no Dependabot, pip-audit, npm audit or similar). Cheap to add |
| Secrets | Held in Render's environment settings | No written rotation schedule. The operator key, the connections key and the database login need one |
| Incident response | A template policy exists | Our own approved plan, a contact route, and a practice run (a "tabletop") written down |
| Vendors | A vendor register exists in the product | Enter our own suppliers (Render, Supabase, Cloudflare, Auth0, GitHub, Brevo, OpenRouter), with each one's security report on file |
| People | Training module (new), policy acceptance per person | Background checks, signed confidentiality terms, a joining and leaving checklist |
| Risk | Risk register with heat map | Record our own top risks and review them on a date |
| Policies | Templates for access, passwords, encryption, incident response, retention | Write ours from the templates, approve them, and have each person accept them |
| Physical | None needed: we have no office or servers | Rely on the hosts' own reports and say so |

## 3. Fixed in this session (separate PR, ADR-065)

- **Security headers.** The live site sent none of the standard browser protections. They are added now: no content-type
  guessing, framing only by ourselves, a safe referrer policy, camera/microphone/location denied, and a one-year HTTPS-only
  rule. I checked that nothing in the app uses what they block.
- **Operator key limit.** Eight wrong keys in a row all got a plain refusal with no limit. After ten wrong tries from one
  address in five minutes, further tries are refused. The address comes from Cloudflare's own header, not one a caller can
  write.

## 4. Still open, in the order I would do them

1. **Content-Security-Policy**, run in report-only mode first, because the 3D sign-in page and inline styles would break
   under a strict one.
2. **Backups and a written restore test**, then paid tiers for hosting and the database (needs your decision, below).
3. **Dependency and code scanning in CI**, so known-vulnerable packages fail the build.
4. **Durable logs**: send request logs to a service that keeps them for a year.
5. **Confirm multi-factor sign-in** on every admin account of ours, and write down how often secrets are rotated.
6. **Our own organisation in the product**, with these policies approved and these controls attested, so the product is
   our evidence. This needs the operator key and an Auth0 login, as the demo organisation did.

## 5. Decisions only you can make

1. **Type 1 first, or Type 2?** Type 1 is faster and a good first step; most buyers eventually want Type 2.
2. **Scope.** I suggest the Security criteria only to start (the common ones), not availability, confidentiality or privacy.
3. **Hosting budget.** Paid Render and Supabase tiers, with backups switched on.
4. **The audit firm.** Ask two or three firms that work with startups for a quote; I do not know current prices.
5. **When.** The research said to wait until a deal is blocked by it. A reasonable middle path is to do items 1 to 5 above
   now (cheap, and useful anyway) and decide on the audit when the first buyer asks.

## 6. What I did not do

- No live organisation was created for ourselves, and nothing was changed in Render, Supabase, Auth0 or GitHub settings.
- I could not check: Auth0 and account multi-factor settings, the Supabase plan, whether backups run, or Render's log
  retention. Each needs a look in that service's dashboard.
