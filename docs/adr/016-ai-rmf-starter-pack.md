# ADR-016: AI RMF as a content pack — a new UCO domain, and the honest limits of an outcome-based framework

## Context
Every framework packaged so far (ISO 27001, PCI DSS, SOC 2, NIST CSF, HIPAA, CIS, GDPR) shares
a shape: a clause states a requirement, evidence carries an attribute, and a condition decides
whether the attribute satisfies the clause. Numeric thresholds (`password_min_length >= 12`,
`max_age_days: 183`) do most of the work.

NIST AI 100-1 (AI RMF 1.0) does not have that shape. It is voluntary, outcome-based, and
contains no numeric threshold anywhere in its 72 subcategories. "Legal and regulatory
requirements involving AI are understood, managed, and documented" is a real governance
outcome with nothing to compare against. Its companion AI RMF Playbook supplies per-subcategory
"Suggested Actions" — advice, not criteria.

Packaging it therefore raises a question the other seven never did: what happens when a
framework's outcomes cannot honestly be reduced to attribute checks?

## Decision
**Package the GOVERN subcategories a document can actually evidence, and package no others.**

11 of the 19 GOVERN subcategories are in `app/content/nist-ai-rmf-1.0.yaml`. They were chosen
by one test: can a document state the thing, such that its absence is a real finding? A policy
either defines a decommissioning process or it does not (GOVERN 1.7); an inventory either has
owners or it does not (GOVERN 1.6). Those are packaged.

GOVERN 3.1 — "decision-making ... is informed by a diverse team" — is not, and neither are the
other seven. No document attribute settles them. Inventing `diverse_team_involved: true` would
not measure the outcome; it would manufacture a passing verdict for anyone willing to write the
sentence, which is worse than admitting the framework covers something we cannot test. MAP,
MEASURE and MANAGE are out of scope entirely for now.

**Almost every condition is "the policy states X".** That is not a weakness of the pack, it is
what AI RMF actually requires at the GOVERN layer, and it lands on the existing
`MISSING_ATTRIBUTE` gap, which names the attribute the document failed to state. The output is
"your AI policy never says who may override the model", not "insufficient evidence".

**A new UCO domain, `AI_GOVERNANCE`, with nine objectives.** This is the one pack that shares
no UCO with the others, and that is deliberate: the existing taxonomy covers IAM, vulnerability
management, data protection and logging, and an AI system inventory maps onto none of them.
Rather than bend an IAM objective to fit, the pack owns a new domain phrased
framework-neutrally, so ISO/IEC 42001 and the EU AI Act can map onto the same objectives
instead of adding a third parallel taxonomy. `test_ai_rmf_owns_a_new_uco_domain` records this
as an intended exception to `test_new_frameworks_reuse_existing_iam_and_vuln_ucos`.

The cost is real and worth stating: the reuse metric that is this product's headline number
(one upload satisfying many frameworks) does not apply across AI-RMF and the security packs
today. It will apply between AI frameworks once a second one exists.

**Two new artefact types, `AI_POLICY` and `AI_INVENTORY`.** An AI governance policy is
deliberately not a `POLICY`, so uploading the information security policy cannot accidentally
satisfy an AI clause. `AI_INVENTORY` exists because GOVERN 1.6 is evidenced by an inventory
with a freshness rule (`max_age_days: 365`), not by a policy asserting one exists.

**Playbook guidance becomes gap remediation.** `Requirement.guidance` is a new optional field,
appended by `app/service.py::_remediation` to the generic per-gap-kind sentence rather than
replacing it — the generic sentence names the concrete attribute that failed, which
clause-level advice cannot. Only packs whose source publishes actionable guidance carry it;
the other seven leave it empty and their remediation text is unchanged.

**Cadences reuse the ODP pattern, not invented numbers.** GOVERN 1.5 (periodic review) and
GOVERN 2.2 (training) have frequencies AI RMF explicitly leaves to the organisation. They use
`org_defined_max_age_attribute` from ADR-013, so the interval tested is the one the org's own
policy states. GOVERN 1.5 pairs an `AI_POLICY` stating the cadence with a `REVIEW_RECORD`
proving a review happened — the same two-artefact shape that ADR-013 introduced.

## Alternatives considered
- **Package all 72 subcategories.** Rejected: ~40 of them have no documentary evidence that
  would settle them, and a pack that fabricates attributes to reach full coverage produces
  confident nonsense. Coverage is not the goal; defensible verdicts are.
- **Force AI RMF onto the existing IAM/DATA UCOs.** Rejected: mapping "AI systems are
  inventoried" onto an access-control objective would corrupt the reuse metric with false
  overlap, which is worse than no overlap.
- **Free-text guidance per gap kind rather than per clause.** Rejected: the Playbook's value is
  that its advice is specific to the subcategory. A per-kind string would be another generic
  sentence.
- **A separate `ai_guidance` table.** Rejected: guidance is framework content and belongs in
  the pack with the clause it describes, like every other framework rule (ADR-004).
- **Wire the Playbook's "About" narrative in too.** Rejected for now: it is background reading,
  several paragraphs per subcategory, and a remediation task is not where someone reads an
  essay. The `source_url` in the pack header points at the Playbook for anyone who wants it.

## Consequences
- `app/content/uco.yaml` gains nine `AI_GOVERNANCE` objectives; UCO count goes 8 → 17.
- The evidence upload form gains `AI_POLICY` and `AI_INVENTORY`
  (`frontend/src/pages/EvidenceList.tsx`), and its hard-coded category-label chain became a
  lookup table rather than growing a fifth ternary.
- Extraction needs no code change — attributes are names passed to the model, so a pack can
  introduce new ones as pure content. Whether the model reliably extracts
  `human_override_capability` from a real AI policy is an open question that only a golden
  corpus will answer; `evaluation/` is where that belongs.
- The 8 unpackaged GOVERN subcategories and all of MAP/MEASURE/MANAGE remain available to add.
  The limiting factor is evidence design, not YAML.
