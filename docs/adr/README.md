# Architecture Decision Records

| ADR | Decision | Status |
|-----|----------|--------|
| [001](001-postgres-rls-tenancy.md) | PostgreSQL + RLS for tenant isolation | Accepted |
| [002](002-pgvector-before-vector-db.md) | pgvector before any external vector DB | Accepted (deferred build) |
| [003](003-s3-compatible-storage.md) | S3-compatible evidence storage behind an interface | Accepted |
| [004](004-deterministic-rules-before-llm.md) | Deterministic rules decide compliance; the LLM only extracts facts | Accepted |
| [005](005-ollama-model-gateway.md) | Local Ollama behind a ModelGateway interface | Accepted |
| [006](006-async-job-framework.md) | Background jobs: FastAPI BackgroundTasks now, Dramatiq when it stops fitting | Accepted |
| [007](007-modular-monolith.md) | Modular monolith, not microservices | Accepted |
| [008](008-native-extraction-before-vlm.md) | Native text extraction before any VLM call | Accepted |
| [009](009-domain-events-deferred.md) | Domain events / outbox deferred until a consumer exists | Accepted (deferred build) |
| [010](010-ciso-assistant-integration.md) | Push closed verdicts/gaps into CISO Assistant, don't build risk/policy/vendor here | Accepted |
| [011](011-oidc-auth.md) | OIDC auth alongside the stub identity scheme | Accepted |
| [012](012-auditor-only-ai-nutshell.md) | Auditor-only AI narration of the verdict, redacted by field not by object | Accepted |
| [013](013-organization-defined-commitments.md) | A policy's own stated cadence becomes the org's evidence requirement | Accepted |
| [014](014-live-pipeline-events.md) | Stream pipeline progress to the browser, without becoming the deferred event bus | Accepted |
| [015](015-glossary-layers.md) | Layered glossary: curated entries win, reference corpora are imported not scraped | Accepted |
| [016](016-ai-rmf-starter-pack.md) | AI RMF as a content pack: a new UCO domain, and only the subcategories evidence can settle | Accepted |
| [017](017-compliance-officer-persona.md) | The compliance officer is `ORG_ADMIN`; add only a read-only `COMPLIANCE_VIEWER` role | Accepted |
| [018](018-model-boundary.md) | The model may witness, doubt, suggest or narrate — never decide | Proposed |
| [019](019-how-this-repo-is-built.md) | How this repo is built: agent output is testimony, checks that can fail decide, a human seals one decision at a time | Proposed |
| [020](020-change-control-evidence.md) | Change-control evidence from clients' repositories: read Git, never replace it | Proposed |
| [021](021-gap-exceptions.md) | Gap exceptions that cannot quietly widen: rule- and value-bound, expiring, decided by an auditor | Proposed |
| [022](022-verdict-provenance.md) | Verdict provenance: every computed verdict names its rule, engine, build and inputs, and can be replayed | Proposed |
| [023](023-auditor-held-checkpoints.md) | Auditor-held signed checkpoints of the audit chain, verifiable offline | Proposed |
| [024](024-pre-merge-change-gate.md) | A pre-merge change-control gate that runs the audit's own rules in the client's CI | Proposed |
| [025](025-jev-class-decision-model.md) | Typed decisions get their own Jev-class model, measured on our own cases | Proposed |
| [026](026-ai-code-review-evidence.md) | AI code review is evidence, not approval | Proposed |
| [027](027-grc-reviews-code.md) | GRC reviews code: Review Standards, a rule engine, and what it may read and keep | Proposed |
| [028](028-code-review-github-app.md) | The code-review GitHub App: tenant binding, durable jobs, check outcomes | Proposed |
| [029](029-verdict-register.md) | Verdict register: a locked verdict is reopened and replaced, never edited | Proposed |
| [030](030-connector-evidence-gaps.md) | Connector evidence gaps: "could not collect" is not "found nothing" | Proposed |
| [031](031-outbound-webhook-notifications.md) | Outbound notifications through one optional webhook | Proposed |
| [032](032-auditor-findings.md) | Auditor findings on a control: raise, respond, close, reopen, all audited | Proposed |
| [033](033-weak-key-check.md) | Check the keys, not the paperwork: a weak-key collector | Proposed |
| [034](034-iso42001-eu-ai-act-packs.md) | ISO/IEC 42001 and EU AI Act packs, with source-text ingestion | Proposed |
| [035](035-advisory-draft-review.md) | Advisory help for reviewing drafted pack requirements | Proposed |
| [036](036-user-management.md) | Team management: change roles, switch someone off without losing history | Accepted |
| [037](037-connector-evidence-in-framework-controls.md) | Connector evidence counts toward ISO 27001, SOC 2 and PCI DSS controls | Accepted |
| [038](038-policy-templates.md) | Policy templates whose figures come from the rules | Accepted |
| [039](039-trust-page.md) | An opt-in, counts-only trust page | Accepted |
| [040](040-questionnaire-answers.md) | Questionnaire answers: status from verdicts, the model only words it | Accepted |
| [041](041-weekly-report.md) | The weekly report: counts only, delivered once a week | Accepted |
| [042](042-vendor-risk.md) | Vendor risk: a register with a rule-decided tier and review date | Accepted |
| [043](043-vendor-reports.md) | A vendor's security report is the proof | Accepted |
| [044](044-connections.md) | Connections an organisation sets up itself (slice 1: chat webhook) | Accepted |
| [045](045-github-connection.md) | An organisation connects its own GitHub for change-control evidence | Accepted |
| [046](046-accept-smaller-scope.md) | A person may accept a smaller repository scope | Accepted |
| [047](047-invite-creates-login.md) | Inviting someone also creates their login, with no password chosen by anyone | Accepted |
| [048](048-aws-connection.md) | Connect AWS through a cross-account role (never used) | Superseded by 049 |
| [049](049-aws-by-upload.md) | AWS evidence arrives from the customer's own script | Accepted |
| [050](050-m365-by-upload.md) | Microsoft 365 evidence arrives from the customer's own script | Accepted |
| [051](051-hr-leavers-by-upload.md) | HR leaver evidence is reconciled on the customer's computer | Accepted |
| [052](052-email-welcome-and-support-reply.md) | An email client, used first for a personalised welcome (in PR 101) | Accepted |
| [054](054-plans-and-limits.md) | Plans and limits, set by hand, with no payment code | Accepted |
| [055](055-google-workspace-by-upload.md) | Google Workspace evidence arrives from the customer's own script | Accepted |
| [056](056-policy-library.md) | A policy library with approval and each person's own acceptance | Accepted |
| [057](057-risk-register.md) | A risk register where fixed rules score and a person signs | Accepted |
| [058](058-first-week-checklist-and-drift.md) | A first-week checklist read from real data, and drift counted from a verdict history | Accepted |
