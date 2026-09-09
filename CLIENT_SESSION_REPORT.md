# Client Test Session — Detailed Report

**Prepared:** 2026-09-09
**Subject:** External client evaluation of the GRC platform via ngrok tunnel
**Tunnel:** `https://critter-kindness-wand.ngrok-free.dev`

---

## 1. Session Identity

| Field | Value |
|---|---|
| Remote IP | `2401:4900:1c66:c7ea:d0e2:6e32:7b02:ccae` (IPv6) |
| Network | `2401:4900::/24` — Reliance Jio, India |
| Browser | Firefox 148.0 on Windows 10 (64‑bit) |
| Tenant | Client's **own** organisation — bootstrapped in‑session (their evidence IDs are not visible to the internal test org, confirming tenant isolation held) |
| Session window | **13:53:40 → 14:48:55 IST** (~55 min wall clock; ~46 min active) |
| Total backend requests | **462** |
| Errors (HTTP ≥ 400) | **0** |
| Slowest response | ~270 ms (`/notifications`) — everything else < 200 ms |

This is the second distinct user on the tunnel. The other IP
(`2401:4900:1c83:…`) was the internal/dev session.

---

## 2. Executive Summary

The client ran a **thorough, self‑directed evaluation** for ~46 minutes. They:

1. Bootstrapped their own org / audit‑firm / engagement (no hand‑holding, no guided tours).
2. **Uploaded two POLICY documents** and watched both process live.
3. Drilled into **13 individual controls** repeatedly (156 requests) — the single biggest activity.
4. Inspected both evidence documents in depth (125 requests) — attributes, gaps, history, versions, live event stream.
5. **Exported the compliance report** (`/export/compliance.csv`).
6. Checked tasks, gaps, activity log, glossary, and the CISO‑sync integration status.
7. Left the tab open idling on notification polling, came back once at 14:39, did a final dashboard check at 14:46, then left.

**Zero errors across 462 requests.** Nothing broke. The platform performed cleanly for the entire evaluation.

---

## 3. Timeline (minute-by-minute)

| Time (IST) | Reqs | What they were doing |
|---|---:|---|
| 13:53 | 1 | Landed, first `/notifications` poll |
| **13:54** | **55** | Bootstrapped org/firm/engagement → **uploaded evidence #1 (13:54:24, POLICY, 202)** → immediately opened its status/attributes/history/versions/event‑stream → pulled the full controls list and opened **13 controls back‑to‑back** → checked tasks |
| 13:55 | 13 | Dashboard, activity log, notifications, evidence list |
| **13:56** | **85** | Heavy evidence‑detail polling (49) while a doc processed + re‑opened all 13 controls (26) → **uploaded evidence #2 (13:56:04, POLICY, 202)** |
| 13:57–13:58 | 14 | Light polling — evidence list, notifications, dashboard |
| **13:59** | **54** | Full sweep again (controls ×26, evidence ×15, gaps, dashboard) → **exported `/export/compliance.csv` (13:59:40)** |
| **14:00** | **100** | Peak minute. Control detail ×52, dashboard ×12, evidence list ×10, controls list ×6, tasks ×6, gaps ×4, **glossary ×2**, activity ×2 |
| 14:01–14:03 | 73 | Another evidence‑processing watch (detail ×30), plus controls sweep ×26 |
| 14:04–14:19 | 30 | **Idle heartbeat** — `/notifications` every ~30 s, tab left open |
| 14:19 → 14:39 | 0 | **~20 min gap** — walked away / tab backgrounded |
| 14:39 | 24 | Came back — re‑opened evidence #1 detail (16), notifications |
| 14:40 → 14:46 | — | ~7 min gap |
| 14:46–14:48 | 6 | Final `/analytics/dashboard` + `/notifications` checks, then stopped |

---

## 4. What they exercised (by volume)

| Area | Requests | Notes |
|---|---:|---|
| **Control detail** | 156 | 13 distinct controls, each re‑opened ~12× across the session |
| **Evidence detail** | 125 | 2 documents — status, attributes, gaps, history, versions, live events |
| **Notifications** | 68 | Steady real‑time polling; also the idle heartbeat |
| **Evidence list** | 36 | Incl. filtered views: `artefact_type=AI_POLICY`, `artefact_type=AI_INVENTORY` |
| **Dashboard / analytics** | 30 | Returned to it repeatedly as a "did anything change" check |
| **Controls list** | 14 | Entry point before drilling in |
| **Tasks** | 12 | `/tasks`, `/tasks?status=OPEN`, `/tasks/owners` |
| **Gaps** | 8 | `/gaps?status=OPEN` |
| **Admin / setup** | 6 | org + audit‑firm + engagement bootstrap (run twice) |
| **Activity log** | 4 | Audit trail review |
| **Glossary** | 2 | `?limit=200` — full term dump |
| **CISO‑sync status** | (in admin) | Checked the external‑integration health endpoint |
| **Export** | 1 | `/export/compliance.csv` — downloaded the compliance report |

---

## 5. Key actions (writes)

| Time | Action | Result |
|---|---|---|
| 13:54:24 | `POST /evidence?artefact_type=POLICY` (doc #1 `92d8d0b2…`) | **202 Accepted** |
| 13:56:04 | `POST /evidence?artefact_type=POLICY` (doc #2 `379f2052…`) | **202 Accepted** |
| 13:59:40 | `GET /export/compliance.csv` | **200 OK** (report downloaded) |

No PATCH / PUT / DELETE — they did not close gaps, assign tasks, record verdicts, or lock controls. Pure evaluation, no state mutation beyond the two uploads.

---

## 6. Behavioural read

- **Experienced evaluator.** Went straight to admin bootstrap, then straight into control internals. No time spent on `/pitch`, and the guided tours (`GettingStartedTour`, `PageTour`) are client‑side only — no evidence they engaged them.
- **The upload → process → inspect loop is what they stress‑tested.** Both uploads were followed by dozens of rapid detail polls watching extraction/evaluation land. This is the product's core value moment and they hammered it twice.
- **Controls are where they spent the most time.** 156 hits on 13 controls means they opened essentially every control in their engagement and kept coming back — comparing verdicts, reading gaps.
- **They cared about the compliance report.** The CSV export is a deliberate "can I get this out to show someone" action.
- **AI framework interest.** Explicit `AI_POLICY` / `AI_INVENTORY` filtered evidence queries — they were probing the NIST AI‑RMF surface specifically.
- **Real‑time matters to them.** Notification polling ran throughout, including a 15‑minute idle heartbeat — they left it open expecting live updates.

---

## 7. Platform health during the session

| Metric | Result |
|---|---|
| Requests served | 462 |
| HTTP errors | 0 |
| 5xx / crashes | 0 |
| Auth failures | 0 |
| Median latency | < 100 ms |
| Max latency | ~270 ms (`/notifications`) |
| Evidence uploads accepted | 2 / 2 |
| CSV export | Succeeded |
| Tenant isolation | Held (their docs invisible to the other org) |

**No problems surfaced.** Nothing to fix from this session on the reliability side.

---

## 8. Suggested follow-ups

1. Ask the client directly what the two policy documents were and whether the extracted attributes / gaps matched their expectations — they inspected results heavily but we can't see verdict quality from access logs alone.
2. They exported the CSV — worth asking if the format/columns were what they needed.
3. They never mutated state (no gap closure, no task assignment). A guided "now fix a gap and watch it clear" step in a follow‑up demo would show the loop closing.
4. The 20‑minute idle gap mid‑session suggests an interruption, not a drop‑off — the session resumed cleanly.
