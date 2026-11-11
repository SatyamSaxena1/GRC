# ADR-060: Every ISO 27001 and SOC 2 control is listed; one with no rule yet is attested by a named person

**Status:** Accepted
**Date:** 2026-11-11
**Deciders:** Platform owner

## Context
Competitor research (Vanta, Drata, Secureframe, Sprinto, Scrut and others, November 2026) found that the first thing
a buyer checks is whether the product covers their framework. We listed 12 of the 93 ISO 27001:2022 Annex A controls and
11 of the 33 SOC 2 Security criteria, because a clause entered the packs only once a deterministic rule could judge it
from evidence (ADR-004). Many controls (screening, physical entry, board oversight) have no document attribute a rule
can check. Every rival handles these the same way: a person states the control is in place and attaches proof, and the
auditor judges it.

## Decision
- **Every Annex A control and every CC1 to CC9 criterion is in the packs** (SOC 2 CC7.5 arrives with draft PR 109). A
  clause has a rule (evidence requirements and mappings) or neither. One with neither is `attestation_only`: no evidence
  is ever matched against it, so the engine cannot pass or fail it.
- **A rule-less clause is met by an attestation:** an organisation admin, or that control's owner, writes how it is in
  place (at least 20 characters), a date no more than a year away, and optionally a piece of evidence already uploaded.
  Auditors cannot attest; they judge. A clause that has a rule cannot be attested (409): its evidence decides it.
- **Attested is never PASS.** Readiness shows it as ATTESTED and counts it separately (`attested`), adding it to the
  readiness percentage but not to `satisfied`, the rules' count, which the public trust page still uses.
- **Nothing is deleted.** A newer statement supersedes; withdrawing sets `revoked_at`; a statement past its date stops
  counting. Each attestation and withdrawal is an audit event on the control. The table is under row level security.
- The new clause wording is our own, drafted by AI and marked for review in the YAML. A clause moves from attested to a
  rule when one can be written; the attestation history stays.

## Consequences
- Readiness percentages for ISO 27001 and SOC 2 drop for every organisation on deploy, because there are more clauses.
  That is the honest number; the page explains which clauses need a statement.
- Rule hashes of existing clauses are unchanged (new fields are not added to existing requirements), so no verdict is
  flagged as "rules changed since".
- Not done: a picker for attaching evidence in the form (the API accepts `evidence_id`), reminders before a statement
  lapses, and attestation on the control detail page.
