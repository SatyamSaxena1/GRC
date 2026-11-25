# ADR-069: An "AI-assessed" lane: the model may propose a verdict where no fixed rule exists, and a person confirms it

**Status:** Accepted (owner decision, 25 Nov 2026)
**Amends:** ADR-004 (rules decide) and ADR-018 (what the model may do). Both stay in force except where this ADR says otherwise.

## Context
ADR-004 let the model read documents and kept the verdict in fixed rules, and ADR-018 listed four roles the model may play and
none of them decides. That is right for structured facts (merges, MFA, password length). It leaves a gap that the established
compliance tools fill with AI: many requirements are about whether a *document* does its job, and no number can be compared.
In our own DPDP pack, "retention and erasure are governed", "a clear privacy notice", and "rights and grievance routes are
published" have no fixed rule at all (`mappings: []`), so today they can only read "no evidence" or be attested by a person. The
owner asked to move toward what competitors do (Vanta, Drata and Secureframe advertise AI that evaluates documents and
evidence) while keeping an audit trail an auditor can accept.

## Decision
Add a fifth role beside ADR-018's four: **assessor, for requirements with no fixed rule only.**

- **Where it applies.** Only a requirement whose content pack gives evidence requirements but no delta conditions. A requirement
  with a fixed rule is decided by that rule, always. The model may never override, soften or replace a rule.
- **What it produces.** A stored *assessment*: a proposed outcome (`MET`, `PARTIAL`, `NOT_MET`), a short reason per point it
  checked, and for each point a **verbatim quote and page** from the document. Plus the model and prompt version, the SHA-256 of
  the document it read, and the time. An assessment is a record, never recomputed: running it again makes a *new* record and never
  changes a confirmed one.
- **It is never "passed".** It shows as **AI-ASSESSED** (a new verdict, like ATTESTED), is counted in readiness as its own
  bucket, and is never counted as "met by the rules". The word PASS stays reserved for fixed rules.
- **A person confirms it.** Until a named person confirms (or overrides) the assessment, it reads "AI-assessed, awaiting
  confirmation" and counts as progress, not as met. Confirming records who and when, like an attestation. The auditor sees the
  proposal, the quotes, and the confirmation, and still locks the verdict (ADR-004).
- **Guards that carry over.** A quote that is not a verbatim substring of the document is not accepted (the existing
  quote-support check): the assessment drops to `NEEDS_REVIEW`. The document is untrusted input (`app/ai/untrusted.py`): an
  instruction inside it can only ever make the outcome *less* favourable or send it to a person, never more.
- **Reproducibility, honestly.** A model run is not reproducible, so the product does not pretend it is. What is reproducible is
  the *record*: the same stored assessment always displays the same, and re-evaluating the pack never silently changes it.
- **Not allowed (unchanged).** The model never decides a verdict where a rule exists, never clears a human review, never
  auto-confirms, and never sets a task priority.

## Alternatives considered
- **AI decides when confident, no person.** Rejected: our own benchmark found the model wrong about one time in eight when it
  sounded sure (ADR-059), and an auditor cannot re-check a score.
- **AI decides every verdict.** Rejected: it discards the property ADR-004 was written for (a verdict that is the same every time).
- **Stay as is.** Rejected by the owner: the gap with competing tools is real for document-type requirements.

## Consequences
- The model's role grows from witness, doubter, suggester and narrator to include assessor, so ADR-018's table gains a row and
  its sentence "never a decider" becomes "never a decider where a rule exists".
- Readiness pages gain a bucket (like "attested"): "AI-assessed, awaiting confirmation" and "AI-assessed, confirmed".
- The first requirements to use it are the DPDP ones with no rule: privacy notice, rights and grievance routes, retention and
  erasure. Others follow only when a pack author marks them as assessable.
- It is more convincing to buyers and a little weaker to an auditor than a fixed rule. Labels keep the two apart.
- **Open before it ships:** the schema for stored assessments, the prompt and a calibration set for the DPDP documents, the new
  verdict in the readiness and gap views, and tests that a forged quote, a prompt-injected document and a re-run cannot change a
  confirmed result.
