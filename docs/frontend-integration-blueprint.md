# GRC frontend integration blueprint

## Purpose

Build a role-aware web application over the existing FastAPI backend, inspired by the *interaction patterns* observed in the supplied compliance portal: recent-project cards, a project-scoped workspace, concise health/progress widgets, timeline views, and filterable work queues. Do not copy its branding, wording, visual assets, or proprietary workflow details.

The product remains differentiated by its evidence-first Unified Control Framework (UCO) model: upload once, evaluate against many frameworks, explain every result, and let a human auditor lock the conclusion.

## Inputs used

- The supplied concept note defines the intended multi-tenant GRC/TPRM product: audit-firm delivery, auditee workspaces, UCO mapping, evidence intelligence, risk/TPRM, and executive reporting.
- The current backend is a focused evidence-compliance slice. It already supports organisations, audit firms, engagements, scoped access, evidence upload/versioning, extraction, deterministic evaluation, gaps/tasks, auditor verdicts/locks, immutable audit events, reuse analytics, and framework readiness.
- The reference portal was explored only as an authenticated visual product reference. Observed patterns: Recent Projects cards, a project dashboard, scoped navigation, progress/health cards, activity/timeline charts, notifications, and a searchable/filterable gap list with due date, assignee, and status.

## Product translation

Use **workspace** in the UI where the reference product uses a project. A workspace is an organisation plus a framework/audit engagement scope; it is not a new backend tenant.

```text
Platform / firm workspace
  -> Organisation workspace
     -> Framework workspace
        -> Control workspace
           -> Evidence, findings, tasks, audit history
```

This aligns with the current schema:

| UI concept | Existing backend model/API | Frontend responsibility |
| --- | --- | --- |
| Organisation workspace | `Organization`, admin routes | Org switcher, membership-aware entry point |
| Audit scope | `Engagement`, `EngagementAllocation` | Framework/audit-period context and auditor navigation |
| Compliance work item | `OrgControl`, `/controls` | Control list, owner queue, status summary |
| Evidence | `Evidence`, `/evidence` | Upload, processing state, quality/provenance, version timeline |
| Evaluation | `EvidenceControlLink`, `/evidence/{id}/evaluations` | Verdict, framework mapping, gap rationale, auditor review |
| Remediation | `GapRow`, `TaskRow`, `/gaps`, `/tasks` | Work queue, due dates, filters, ownership, escalation |
| Audit trail | `AuditEvent`, history routes | Read-only chronological timeline |
| Portfolio metrics | `/analytics/reuse`, `/analytics/readiness/*` | Executive dashboard and cross-framework readiness |

## Recommended application shell

### Global shell

- Left rail: Home, Organisations, My Work, Activity, Calendar, Reports.
- Top bar: global search, organisation/workspace switcher, notifications, profile.
- Main content: breadcrumb `Organisation / Framework / Control` and contextual actions.
- Route guards must be driven by API authorisation outcomes, never by hidden navigation alone.

### Workspace shell

When a user opens an organisation/framework workspace, show a local left rail:

1. Overview
2. Controls
3. Evidence
4. Gaps & Tasks
5. Audit review (auditors and managers only)
6. Activity / History
7. Settings (admins only)

Later modules from the concept note—Risk, Vendors/TPRM, Policies, Asset Scope, and Reports—should become additional top-level workspace areas only when their backend modules exist.

## MVP screens and API integration

### 1. Recent work / organisation dashboard

Show cards for the user’s visible organisations or engagements, each with framework labels, readiness, open gaps, overdue tasks, and last activity. This follows the useful “Recent Projects” scan pattern without duplicating its design.

**Backend today:** organisation and engagement administration plus `GET /analytics/reuse`, `GET /analytics/readiness`, `GET /gaps`, and `GET /tasks`.

**Small backend addition needed:** a single `GET /workspaces` read model returning only authorised organisation/engagement summaries. Avoid making the browser fan out across many organisations.

### 2. Framework workspace overview

Show four decision cards: compliance readiness, evidence freshness/quality, open remediation work, and evidence reuse saved. Below them, show a readiness-by-framework bar chart, task trend, and recent audit activity.

**Backend today:** readiness and reuse endpoints; controls, gaps, tasks, and history routes.

**Small backend addition needed:** `GET /dashboard` (or `GET /workspaces/{id}/dashboard`) that assembles these values server-side with a stable payload. Charts should consume this compact DTO, not query raw tables from the browser.

### 3. Control workbench

Show a control list with framework, clause, verdict, owner, evidence count, open gap count, freshness state, and lock state. Selecting a control opens a detail page with evidence, evaluation explanation, gaps, timeline, and audit actions.

**Backend today:** `GET /controls`, `GET /controls/{id}`, `/controls/{id}/evidence`, `/controls/{id}/history`, and `POST /controls/{id}/submit`.

**Gap to close:** the control-list payload needs derived status/count fields and pagination/filtering. Add these to the read endpoint rather than materialising a separate frontend-only status model.

### 4. Evidence centre

The upload page should show validation state, processing progress, extracted attributes with page provenance, quality score, framework-by-framework verdicts, and an immutable version timeline. The primary call-to-action for a failing item is **Upload revised version**.

**Backend today:** `POST /evidence`, `POST /evidence/{id}/versions`, status/attributes/evaluations/history/versions/detail reads.

**Frontend behaviour:** after the upload returns `202`, poll `GET /evidence/{id}/status` until `READY`, `FAILED`, or `NEEDS_REVIEW`; never imply a pass while extraction is still running.

### 5. Gaps and tasks queue

Use the reference app’s strongest workflow pattern: a compact table with search and filters for status, priority, assignee, framework, due date, and ageing. A row opens the related control/evidence context, not a detached ticket.

**Backend today:** `GET /gaps` and `GET /tasks` support status and preserve the evidence/control relation.

**Gaps to close:** add owner assignment, due-date updates, priority/criticality, pagination, server-side filters, and task mutation endpoints. Do not build an independent task subsystem; tasks remain created from gaps.

### 6. Auditor review and lock

Present a dedicated review layout: control context, evidence preview/provenance, deterministic gap explanation, verdict controls, mandatory auditor remarks, history, and lock/unlock state. Once locked, render the workspace read-only except for a formal unlock request flow.

**Backend today:** audit verdict, lock, unlock routes; link-level lock data and history.

**Gaps to close:** add a policy that prevents the uploader from recording the auditor verdict, and model formal auditor comments/unlock requests before exposing those UI actions.

## Frontend architecture

Use a conventional TypeScript SPA (React is a good fit) against the FastAPI REST API. Keep the frontend thin:

```text
React route + feature component
  -> typed API client
     -> FastAPI router
        -> existing service/evaluator/authorisation layer
           -> PostgreSQL / object storage / model gateway
```

- Generate or maintain TypeScript types from FastAPI OpenAPI; do not duplicate Pydantic schemas by hand.
- Put fetch/query caching in one API client layer; cache immutable/read-heavy data briefly and invalidate evidence/control queries after mutations.
- Keep evaluation logic on the server. The UI may format a gap explanation but must never recompute a verdict.
- Use server-provided permissions and `404`/`403` responses as the source of truth. Frontend route guards improve usability but do not grant access.
- Upload directly to the existing evidence endpoint initially. Introduce presigned object-storage upload only when document size or throughput requires it.
- Prefer polling for the current in-process job model. Replace it with SSE/websockets only after the backend gains a durable worker/event system.

## API contract priorities

Implement these read models before building complex screens:

1. `GET /workspaces` — authorised organisation/engagement cards for recent work.
2. `GET /workspaces/{workspace_id}/dashboard` — overview metrics and chart series.
3. Extend `GET /controls` — filters, pagination, owner, evidence/gap counts, derived status, lock state.
4. Extend `GET /gaps` and `GET /tasks` — pagination, framework/owner/due-date/priority filters.
5. Task mutations — assign, set due date, update status; each action writes an audit event.
6. Read-only activity feed — queryable audit-event summaries scoped by authorisation.

Each endpoint should return presentation-ready data at its boundary. That prevents a dashboard from assembling sensitive cross-tenant information in the browser and keeps the UI simple.

## Delivery sequence

### Phase 1: frontend over the current vertical slice

- Authentication adapter and organisation/workspace context.
- Recent-work cards, framework overview, controls, evidence centre, gaps/tasks queue.
- Evidence processing state, provenance, version history, auditor review/lock views.
- Dashboard/read-model endpoints and task-filter/mutation APIs.

### Phase 2: complete the concept note’s core platform

- Production identity: MFA, OIDC/SAML, SCIM, role/permission administration.
- Proper UCO-first schema and content-studio/versioned framework packs.
- Durable async processing, retries, notifications, document search, reports.
- Scope/asset register, policy workflow, risk register and treatment.

### Phase 3: TPRM and executive delivery

- Vendor register, tiering, assessments, external respondent portal, evidence review.
- Audit-firm portfolio view, report generation, CISO dashboards, maturity trends.
- Connector ingestion and governed AI-assistance features from the concept note.

## Explicit non-goals for the first frontend release

- Recreating the reference portal pixel-for-pixel.
- Building vendor questionnaires, risk heat maps, policies, or reports before their backend domain and permissions exist.
- Moving deterministic evaluation, cross-framework mapping, or authorisation into client code.
- Replacing the current modular monolith with microservices merely to support a frontend.

## Acceptance checks

- A control owner sees only assigned controls and related evidence/tasks.
- An auditor sees an auditee only through an active, framework-scoped engagement.
- An upload visibly advances from accepted to terminal processing state and never reports an unverified pass.
- A new evidence version preserves prior history, resolves applicable gaps, and cannot overwrite an auditor-locked verdict.
- Dashboard metrics match the existing analytics/evaluator outputs.
- Every state-changing action has an auditable actor, request ID, timestamp, and before/after state where applicable.

## Reference-site functional atlas

The following sections were inspected from the project dashboard and its global navigation. The observations describe visible behavior only; they are not a specification of the reference site's internal implementation.

### Global navigation

| Area | Observed behavior | Translation for our platform |
| --- | --- | --- |
| Home / recent projects | Recent engagement cards show organisation, framework, progress, health, tasks and issues | `GET /workspaces`; cards should emphasize readiness, open gaps, stale evidence and reuse |
| Organisations | Portfolio-style organisation cards with project, event, task, message and notification counts | Audit-firm portfolio view; postpone until the workspace API and production tenancy are ready |
| Activity feed | Cross-project chronological activity surface | Authorised projection of `AuditEvent`; start read-only |
| Saved filters | Large reusable filter form and saved-filter list | Saved views are useful later; first ship URL query parameters and browser-local presets |
| Global calendar | Events and task deadlines across projects | Aggregate task due dates and audit periods; no separate calendar engine initially |
| Search | Global entry point | Search controls, evidence metadata and tasks only after server-side indexed search exists |
| Notifications | High-volume notification counter and drawer entry point | Add after durable jobs and notification preferences; do not derive alerts solely in the browser |

### Project dashboard

The dashboard combines overall health, milestone completion, tasks due, monthly activity, planned-versus-actual work and a project timeline. It also exposes project users and alerts.

For our platform, the useful equivalent is a decision dashboard rather than a generic project-management dashboard:

- Readiness by subscribed framework
- PASS / PARTIAL / FAIL / NO EVIDENCE control distribution
- Open, overdue and recently resolved gaps
- Evidence freshness and quality distribution
- Evidence reuse and estimated effort saved
- Audit-period progress and recent immutable activity
- Controls awaiting auditee submission or auditor verdict

### Calendar

The project calendar provides a scoped schedule, while the global calendar combines work across projects. Our first version can compute calendar entries from existing fields:

- `TaskRow.due_at`
- `Engagement.period_start` and `Engagement.period_end`
- evidence review/expiry dates once those are normalized into queryable fields

Return these through a read-only `GET /calendar?from=&to=` endpoint. Add event creation only when there is a real event domain; task deadlines should continue to be edited through task APIs.

### Milestones

The reference project has a milestone overview and quarter sections (Q1-Q4). A quarter page behaves like a work queue with status, priority, assignee, bulk assignment and submit-for-review transitions.

Our equivalent should be **audit phases**, not hard-coded quarters:

```text
Planning -> Evidence collection -> Auditee review -> Auditor fieldwork
         -> Remediation -> QA/sign-off -> Closed
```

Add `AuditPhase` only when phase tracking is required. Until then, calculate lightweight progress from control/task states and the engagement period. Quarters can be optional labels or date filters, not schema columns.

### Prerequisites

Visible prerequisite categories include company details, web applications, external networks and internal networks. Each opens the same ticket-style queue and captures scoped facts needed before evidence review begins.

This maps to the concept note's Scope & Asset Register module, which is not in the current backend. The minimum model is:

```text
ScopeItem
  id, org_id, engagement_id?, kind, name, attributes_json,
  owner_user_id?, status, created_at, updated_at
```

Start with `kind` values for `ENTITY`, `LOCATION`, `BUSINESS_UNIT`, `APPLICATION`, `NETWORK` and `DATA_STORE`. Extracted evidence scope should be compared against these records by the evaluator. Do not copy the reference product's ticket representation for structured company and asset data.

### Actions / gap points

Gap points are presented as a searchable table with total/closed counts, status, priority, assignee, due date, pagination, bulk selection and per-row state changes. This is the closest reference pattern to our existing `/gaps` and `/tasks` domain.

Implement with:

- `GapRow` as the immutable compliance deficiency and explanation
- `TaskRow` as the mutable remediation work item
- filters for framework, clause, kind, status, owner, priority, due range and evidence version
- explicit task mutation endpoints for assignment, due date, priority and status
- automatic closure only through new evidence when the deterministic evaluator confirms resolution
- an audit event for every manual mutation

Do not let users manually erase or mark a `GapRow` resolved independently of evidence/auditor workflow.

### Evidence categories

The reference project separates PCI environment information, policies/procedures, technical evidence, sample reports and log evidence. Each category uses the common ticket queue with counts and workflow state.

Our backend already has `Evidence.artefact_type`; evolve this into content-pack-driven evidence types rather than hard-coded sidebar categories. A recommended information architecture is:

```text
Evidence centre
  All evidence
  Policies & procedures
  Technical configuration
  Operating records & logs
  Assessments & reports
  Certificates & attestations
```

Filters should come from backend metadata. One artefact may serve several controls and frameworks but should keep one canonical evidence record and version lineage.

### Documents / deliverables

The reference site has quarterly deliverable folders plus final deliverables. Deliverable pages again use ticket-like items, such as assessment and penetration-test reports.

For our platform, separate source evidence from generated deliverables:

- **Evidence** is uploaded, versioned, evaluated and reusable.
- **Deliverable** is a generated/exported audit artefact assembled from locked data.

Add a `ReportRun`/`Deliverable` model only when report generation is implemented. Store template/version, input snapshot, output object key, checksum, generation status and actor. Generated reports must never masquerade as source evidence.

### Internal and web-application penetration testing

The reference navigation models internal PT and web-app PT as dedicated workstreams with initial-test/finding groups. This is useful for audit delivery but is outside the current evidence slice.

Initially, treat penetration-test reports as evidence and their deficiencies as gaps/tasks. Add a specialist vulnerability model only when the product must manage scan findings, retests, CVSS, affected assets and technical closure independently of compliance controls:

```text
Assessment -> Finding -> FindingAsset -> Retest -> Closure
```

Avoid embedding a vulnerability-management platform inside the first GRC frontend.

### Project settings

The inspected settings expose category selection, project users/roles and report download. The category page can enable many modules, including prerequisites, actions, evidence, work papers, risk, vendor management, documents and several security-assessment types.

Our navigation should be capability-driven from tenant entitlements and backend permissions, not manually assembled per project. Project-user management maps partially to `User`, `Engagement`, `EngagementAllocation` and `ControlAssignment`, but needs production identity, invitations and atomic permissions before a real administration screen is safe.

## Shared interaction pattern

The reference site gains consistency by representing most project work as one ticket-list pattern. We should reuse the interaction design without flattening the domain:

| Shared UI capability | Domain-specific record |
| --- | --- |
| Search, filter, paginate, bulk-select | Controls, tasks, scope items, findings, deliverables |
| Status chip and transition menu | Server-authorized state machine per record type |
| Priority and due date | Primarily `TaskRow`; not every evidence/control record |
| Assignee | `ControlAssignment`, task owner or audit allocation depending on context |
| Comments and attachments | Future generic collaboration records linked to a typed entity |
| Timeline | `AuditEvent` projection plus domain events |

Build one reusable frontend `WorkQueue` component and a small set of typed column/action configurations. Do not build one generic backend `Ticket` table: control, evidence, gap, task, scope and finding lifecycles have materially different rules.

## Proposed frontend routes

```text
/
/workspaces
/workspaces/:workspaceId/overview
/workspaces/:workspaceId/calendar
/workspaces/:workspaceId/controls
/workspaces/:workspaceId/controls/:controlId
/workspaces/:workspaceId/evidence
/workspaces/:workspaceId/evidence/:evidenceId
/workspaces/:workspaceId/gaps
/workspaces/:workspaceId/tasks
/workspaces/:workspaceId/activity
/workspaces/:workspaceId/settings
```

Later routes should be added only with their backend domains:

```text
/workspaces/:workspaceId/scope
/workspaces/:workspaceId/risks
/workspaces/:workspaceId/vendors
/workspaces/:workspaceId/audits
/workspaces/:workspaceId/reports
```

## Backend fit and implementation status

| Capability | Current status | Minimum implementation |
| --- | --- | --- |
| Organisation and audit engagement | Partial | Add authorised list/detail read APIs and workspace DTO |
| Framework/control workspace | Partial | Enrich `/controls` with filters, pagination and summary counts |
| Evidence pipeline and versions | Implemented, incl. `GET /evidence` list+filters | Download authorization still open |
| Deterministic verdicts and gaps | Implemented slice | Preserve server ownership of all verdict computation |
| Remediation queue | Read-only partial | Add task mutations, priority, due date, ownership and audit events |
| Auditor verdict and locking | Implemented slice | Add comments, segregation of duties and formal unlock requests |
| Dashboard analytics | Partial | Add one scoped dashboard aggregation endpoint |
| Activity timeline | Entity history only | Add authorised workspace-level audit-event feed |
| Calendar | Not implemented | Read projection from tasks, evidence freshness and engagement dates |
| Scope/assets/prerequisites | Not implemented | Add `ScopeItem` domain and evaluation integration |
| Deliverables/reports | Not implemented | Add versioned report templates and immutable generated outputs later |
| Risk, TPRM, policy management | Not implemented | Build as later bounded modules per the concept note |
| Penetration-test workflow | Not implemented | Keep as evidence/gaps until specialist workflow is justified |
| Production identity/notifications | Stub/not implemented | OIDC/SAML/MFA, invitations, durable jobs and preference-aware notifications |

## Next implementation slice

The shortest path to a credible frontend is one vertical workflow:

1. Add `GET /workspaces`, an enriched paginated `GET /controls`, `GET /evidence`, and scoped dashboard/activity read models.
2. Add task priority/owner/due-date fields plus narrow mutation endpoints and audit events.
3. Build the application shell, recent-work dashboard, control workbench, evidence centre and gaps/tasks queue.
4. Reuse one typed `WorkQueue` component across controls, gaps and tasks.
5. Validate role isolation with org admin, control owner and auditor browser journeys.

This covers the strongest reference-site workflows using the backend that already exists. Scope/assets, report generation, risk, TPRM and specialist penetration testing should follow as separate slices rather than empty navigation placeholders.
