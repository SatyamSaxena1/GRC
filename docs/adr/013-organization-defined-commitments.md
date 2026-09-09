# ADR-013: A policy's own stated cadence becomes the org's evidence requirement

## Context
`access_review_frequency_days` was already extracted from POLICY evidence across all 7
frameworks, but checked only against a hard-coded ceiling in content-pack YAML (`<= 365`, `<=
183` for PCI). A policy merely *stating* a plausible cadence passed the requirement, with no
evidence a review had ever actually happened — the exact gap named on the call this feature
came from: *"are you really following that policy or not? अगर policy में जो लिखा है follow नहीं
कर रहे, it is non-compliance."*

This is a named pattern, not a bespoke idea: NIST SP 800-53 and OSCAL call it an
**organization-defined parameter (ODP)** — the control text has a blank ("reviewed at
[Assignment: organization-defined frequency]"); the org's own policy fills it in; the auditor
then tests the org against *its own* stated number, not a universal constant.

## Decision
`access_review_frequency_days`, stated in an org's own POLICY evidence, becomes the ceiling a
*second*, separate REVIEW_RECORD artefact (proof a review actually happened) is measured
against — reusing `app/evaluate.py`'s existing freshness machinery
(`EvidenceValidity`/`_freshness_gaps`/`STALE`), which previously only accepted a literal
`max_age_days`.

**Schema move, not a new concept:** `evidence_validity` moves from `Requirement` to
`EvidenceRequirement` (`app/content/load.py`) because a clause can now involve two artefact
types with two different freshness rules — a POLICY that states the cadence, and a
REVIEW_RECORD whose freshness is judged against it. A clause with two entries of the *same*
artefact type (nist-csf-2.0's `PR.AA-01`) keeps the existing "union required attributes across
all matching entries" behavior; `evidence_validity` is read from whichever entry declares it
(first match — see `app/evaluate.py::_validity_for`).

**Storage:** a new `OrgCommitment(org_id, attribute, value, source_evidence_id, updated_at)`
table — content packs are static and shared across every org (ADR-004: "content packs, not
code, hold framework rules"), so an org-specific override needs its own row, not a YAML edit.
Upserted unconditionally for every extracted POLICY attribute (ponytail: no filtering logic to
decide "which attributes matter" — cheap to store all, only the ones a requirement actually
references via `org_defined_max_age_attribute` are ever read).

**Missing commitment is its own gap**, `NO_ORG_COMMITMENT`, not a silent pass and not a
confusing generic `MISSING_ATTRIBUTE` — "the organisation's policy does not yet state a
required X" tells the org exactly what to fix, distinct from "the evidence document is
incomplete."

**Not every access-review clause got this treatment.** PCI DSS 7.2.4 states its own explicit
number — "at least once every six months" — so it keeps a literal `max_age_days: 183`; making
it org-defined there would let a looser org policy silently override PCI's actual mandate. The
REVIEW_RECORD requirement (proof a review happened) still applies to PCI — the "policy alone
was never proof of practice" gap is universal — only the *ceiling* stays framework-defined
where the framework itself supplies one. The other six frameworks' access-review clauses only
ever said "recurring" or "regularly," which is exactly where an ODP belongs; two of their
authors' own comments already called the previous hard-coded numbers "our own baseline."

**Staleness, not auto-rewrite, when a commitment changes.** `EvidenceControlLink.evaluated_at`
(set on every (re)evaluation) is compared at *read time* against `OrgCommitment.updated_at` for
whatever org-defined attribute a link's requirement depends on
(`app/service.py::link_commitment_stale`). A stale link keeps its last verdict — visible to
every role, not just the auditor, since it's the auditee who needs to act — and is surfaced as
`commitment_stale`/`stale_reason` in `GET /controls/{id}` and `GET /evidence/{id}/evaluations`.
Resolution is the *existing* `POST /evidence/{id}/versions` upload — `/reprocess` is recovery-only
(refused once evidence reaches READY, by design: it must not become a quiet way to recompute a
verdict the auditor already acted on), so re-checking against a changed commitment goes through
the same "upload a new version" path any other correction already does. No new mutation surface
either way. This was an explicit product decision, not a default: the alternative (auto-reprocess
every affected link synchronously when a policy changes) risks a single upload silently rewriting
verdicts nobody asked to change right now; a third option (no staleness signal at all) leaves a
stale PASS sitting unflagged indefinitely, which is exactly the failure mode this feature exists
to close.

## Alternatives considered
- **A new `DeltaCondition` variant** whose `value` resolves from another evidence artefact at
  evaluation time, rather than extending `EvidenceValidity`. Rejected: the concrete need
  (access-review cadence) is a freshness/expiry question, and `EvidenceValidity` already models
  exactly that; a second general-purpose mechanism for the same underlying need would be two
  ways to do one thing.
- **Auto-reprocess on commitment change.** Rejected — see Decision above and the answered
  design question this ADR resolves.
- **A manual override UI** (an admin typing a commitment number directly, bypassing policy
  extraction). Rejected for now: the call is explicit that this should come from AI reading the
  policy; a manual form is a fallback for extraction failure, which today surfaces as
  `NO_ORG_COMMITMENT` — an honest, actionable gap rather than a silent one. Revisit only if that
  gap proves too blunt in practice.

## Consequences
- `evidence_validity`'s move required a mechanical edit to the 7 frameworks that had it
  (re-indenting under `evidence_requirements`) — behavior-preserving everywhere it wasn't also
  gaining the new REVIEW_RECORD requirement.
- A new artefact type, `REVIEW_RECORD`, joins `POLICY`/`SCAN_REPORT` — the upload form's
  artefact-type list needs it (`frontend/src/pages/EvidenceList.tsx`).
- The same mechanism extends to other organization-defined parameters (patch/remediation SLA
  was the call's other literal example) by writing more YAML — `org_defined_max_age_attribute`
  plus an `OrgCommitment` row is the whole pattern; no more plumbing needed.
