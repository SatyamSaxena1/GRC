# Concept-note alignment

This repository targets the concept note's **Suggested MVP Cut Line** (items 41-45), not the full twelve-module platform. The current thin slice should prove those five capabilities completely before Phase 2 modules are added.

## Protected MVP capabilities

| Concept-note requirement | Current implementation | User-facing surface | Status |
|---|---|---|---|
| Unified Control Framework with verified cross-framework mappings | Versioned YAML content packs in `app/content/`; deterministic rules in `app/evaluate.py` | Controls and framework readiness | Implemented for the ISO 27001 and PCI DSS sample packs; expert content expansion remains |
| Evidence upload, extraction and versioning | Upload pipeline, immutable versions, provenance, quality scoring and status APIs | Evidence centre and evidence detail | Implemented thin slice |
| Cross-framework reuse with accept/partial/reject and actionable re-upload requests | One artefact is evaluated against every subscribed framework; gaps and tasks are generated from failed conditions | Overview, Evidence, Gaps and Tasks | Implemented thin slice |
| Control assignment with strict scoped visibility | `ControlAssignment` plus centralized authorization checks | Control owners land on **My tasks** and see only **My controls** and related evidence | Implemented and covered by authorization tests |
| Auditor review, verdict history and control locking | Engagement-scoped auditor access, human verdicts, lock/unlock and append-only history | Auditors land on **Review queue**; control detail is the review workspace | Implemented thin slice |

## Phase 1 support around the cut line

| Requirement | Alignment |
|---|---|
| Multi-tenancy and onboarding | Organisation, audit firm, engagement and allocation models exist. Identity is deliberately a development token; OIDC/MFA is not implemented. |
| Evidence quality score | Deterministic, explained and displayed. |
| Compliance/readiness view | The organisation Overview is the current basic CISO dashboard: framework readiness, verdict distribution, reuse and effort saved. Full G/R/C portal is Phase 2. |
| Task engine | Gap-derived tasks exist and are role-scoped. Assignment/due-date mutation, priority, reminders and notifications remain a bounded follow-up. |
| Auditor workspace | Review, verdict, history and locking exist. Engagement planning, milestones, findings lifecycle and generated reports remain later work. |
| Framework coverage | ISO 27001 and PCI DSS sample packs prove reuse. SOC 2 and DPDP packs are not yet authored. |

## Role journeys

| Role | Landing page | Intended job |
|---|---|---|
| Organisation admin | Overview | See readiness, upload evidence, inspect gaps, submit controls and administer the demo tenant. |
| Control owner | My tasks | Complete only assigned remediation work; unrelated controls remain inaccessible at the API. |
| Auditor | Review queue | Inspect deterministic evidence results, record the human verdict and lock/unlock with history. |

## Explicitly deferred

Risk register, full policy lifecycle, vendor/TPRM, full CISO G/R/C portal, notifications, report generation and integrations belong to Phase 2 or later in the concept note. They should not appear as empty navigation or browser-only mock data before their server-side domains and authorization rules exist.

## Next bounded slice

Add task owner, due date and priority mutations with audit events, then expose them in **My tasks**. This closes the largest remaining gap in the Phase 1 workflow without starting a separate ticketing system.
