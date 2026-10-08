"""Wires ingest -> evaluate -> persistence, and owns the evidence status lifecycle.

Gap/task history is never deleted: a gap that stops reproducing is marked
RESOLVED_BY_EVIDENCE, not removed. A locked EvidenceControlLink belongs only to
the evidence version the auditor reviewed — process_evidence never writes to one,
and no route clones a locked link onto a newer version.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app import audit_log, ciso_sync, provenance
from app import events, normalize
from app.ai import decision
from app.ai.prompts import NUTSHELL_PROMPT_VERSION
from app.ai.schemas import ExtractedField, ExtractionRun, Source
from app.content.load import Content
from app.documents import is_encrypted_pdf
from app.evaluate import evaluate, org_defined_attributes
from app.ingest import (
    PROMPT_VERSION, extract_attributes, extract_attributes_streaming, gateway_for, generate_nutshell,
    read_document,
)
from app.models import (
    AiRun, Engagement, Evidence, EvidenceAttribute, EvidenceControlLink, GapRow,
    OrgCommitment, OrgControl, Organization, TaskRow,
)
from app.quality import score_evidence
from app.storage import get_storage

logger = logging.getLogger("app.service")


def set_status(db: Session, evidence: Evidence, status: str, detail: str = "") -> None:
    evidence.status = status
    evidence.status_detail = detail
    db.commit()
    events.publish(evidence.id, "status", {"status": status, "detail": detail})


# The upload allowlist (frontend/src/pages/EvidenceList.tsx), enforced again in
# app/routers/evidence.py — a client-side-only check is not a check.
# CERTIFICATE and SCREENSHOT have no evidence_requirements mapped yet in
# app/content/*.yaml, so they upload and classify but evaluate against nothing
# until a framework pack maps them. The descriptions are what the model sees
# in classify_artefact (same text as the form's ARTEFACT_HELP).
ARTEFACT_TYPES = {
    "POLICY": "A written policy or procedure document — access control, passwords, data retention, and similar. Encryption and logging policies have their own types.",
    "ENCRYPTION_POLICY": "An encryption policy — protection of data at rest and in transit, and key management.",
    "LOGGING_POLICY": "A logging and monitoring policy — what is logged and how long audit logs are retained.",
    "SCAN_REPORT": "Output from a vulnerability or penetration test scan (e.g. an ASV report).",
    "REVIEW_RECORD": "A record that a periodic review happened — access reviews, log reviews.",
    "REPORT": "A narrative finding or audit report, distinct from an automated scan.",
    "CERTIFICATE": "A third-party attestation or certification (ISO, SOC 2, PCI AOC).",
    "SCREENSHOT": "A screen capture as supporting proof.",
    "AI_POLICY": "An AI governance policy, separate from a general security policy.",
    "AI_INVENTORY": "A system/model inventory for AI systems.",
    "PRIVACY_NOTICE": "A public-facing notice describing personal data, purposes, rights, withdrawal, complaints, and the privacy contact.",
}
# Topic-specific policies split out of POLICY so an access-control policy is not failed for
# saying nothing about encryption. They still state who approved them and when, which no
# requirement asks of them — extract those too, for the quality score only (no gaps).
TOPIC_POLICIES = {"ENCRYPTION_POLICY", "LOGGING_POLICY"}
DOCUMENT_CONTROL = ("approval_date", "approver_role", "effective_date", "systems_covered")
CLASSIFY_MAX_CHARS = 4000
CLASSIFY_ORDERS = 3

# Wrong-document guard: flag only when the model clearly thinks the file is some
# *other* type and gives the declared one next to nothing. Near-neighbours
# (POLICY vs AI_POLICY) split their probability and so stay unflagged.
#
# MISMATCH_TOP was 0.8 and let two of three scan reports filed as a policy through
# (qwen2.5vl:7b, measured 2026-10-06 over the demo documents): a vendor attestation
# reads partly like a CERTIFICATE, so the top answer lands at 0.67-0.87 even though the
# declared type gets ~0.0001. Every document's true type was the top answer (9 of 9), so
# the declared-type condition is what protects correct filings; the top share only needs to
# be a clear majority. 0.6 catches all three scans and still leaves a document that fits no
# type (an invoice: top 0.43) alone. Re-measure with evaluation/ if the model changes.
MISMATCH_TOP = 0.6
MISMATCH_DECLARED_MAX = 0.05


def classify_artefact(gateway, filename: str, text: str) -> dict[str, float]:
    """{artefact_type: probability} from the document's start, or {} when there
    is no text to judge or no model. Shared by the upload form's suggestion and
    the pipeline's wrong-document guard, so both ask the model the same thing."""
    if not text or not text.strip():
        return {}
    # 3 rotated orderings, averaged: the guard can send an upload to review on
    # this answer, so it must not hinge on which option happened to be listed first.
    return decision.choose(
        gateway, "Which kind of compliance evidence is this document?",
        f"Filename: {filename}\n\nDocument start:\n{text[:CLASSIFY_MAX_CHARS]}", ARTEFACT_TYPES,
        orders=CLASSIFY_ORDERS,
    )


def _type_mismatch(db: Session, gateway, evidence: Evidence, text: str) -> str:
    """'' when the declared type is plausible; otherwise the NEEDS_REVIEW detail.
    Logged as an AiRun either way it was asked, so a flag can be explained."""
    probabilities = classify_artefact(gateway, evidence.original_filename or evidence.filename, text)
    if not probabilities:
        return ""
    top = decision.top(probabilities)
    db.add(AiRun(
        org_id=evidence.org_id, evidence_id=evidence.id, operation="artefact_type_check",
        provider=getattr(gateway, "provider", ""), model=getattr(gateway, "model", ""),
        prompt_template_version="artefact_type:v1", validated_output=probabilities,
        confidence=probabilities[top], latency_ms=getattr(gateway, "last_latency_ms", 0),
    ))
    declared = evidence.artefact_type
    if (top != declared and probabilities[top] >= MISMATCH_TOP
            and probabilities.get(declared, 0.0) <= MISMATCH_DECLARED_MAX):
        return (f"uploaded as {declared}, but reads like a {top} "
                f"({round(probabilities[top] * 100)}%) — if so, upload it again as a new "
                f"version with the right type")
    return ""


SUPPORT_OPTIONS = {
    "YES": "the quoted passage states this value",
    "NO": "the passage does not state it, or states something different",
}
# Flag only a confident "no": measured 2026-09-24 (qwen2.5vl:7b) on 7 real
# extracted fields plus a deliberately wrong copy of each, every answer was
# right and >= 0.8 sure — but the wrong copies were blunt, real misreads are
# subtler, so a flag asks a human to look rather than discarding the value.
UNSUPPORTED_MIN = 0.8
# The question must say that a normalised value counts as stated. Without that, qwen2.5vl:7b
# answered NO (0.95-0.996) for true/"Overall Compliance Status: Pass" and false/"...: Fail",
# so every scan report with a pass/fail status went to review on a correct fact (found live,
# 2026-10-06). Measured on 16 value/quote pairs: false alarms 2 of 10 -> 0 of 10, wrong values
# caught 5 of 6 -> 5 of 6 (the miss is a subtle scope narrowing, out of reach either way).
SUPPORT_QUESTION = (
    "Does the quoted passage state this value for this attribute? The value may be a normalised form of "
    "the words: a date written as 2026-06-18 for '18 June 2026', true for 'Pass', 'Yes' or 'Compliant', "
    "false for 'Fail' or 'No', 90 for 'every 90 days'. The passage need not repeat the attribute's name: "
    "'Review completed: 20 March 2026' states a last review date of 2026-03-20. Answer NO only if the passage says something "
    "different, or says nothing about it."
)


def _restore_cadence_words(run) -> None:
    """Undo a model's own "quarterly" -> 90 on review-cadence attributes (see
    normalize.cadence_word_for). Only *_frequency_days names: log_retention_days and the like
    are periods, not cadences, and a number there means a number."""
    for name, field in run.fields.items():
        if "frequency" not in name or field.value is None:
            continue
        word = normalize.cadence_word_for(field.value, " ... ".join(s.quote for s in field.sources if s.quote))
        if word:
            logger.info("cadence_word_restored name=%s value=%r -> %r", name, field.value, word)
            run.fields[name] = field.model_copy(update={"value": word})


def _unsupported_values(db: Session, gateway, evidence: Evidence, run) -> list[str]:
    """Attributes whose extracted value its own cited quote does not state —
    a hallucination check on extraction, one yes/no per quoted field."""
    checked: dict[str, dict] = {}
    unsupported = []
    for name, field in run.fields.items():
        quote = " … ".join(s.quote for s in field.sources if s.quote)
        if field.value is None or not quote:
            continue  # nothing claimed, or nothing cited to check it against
        probabilities = decision.choose(
            gateway, SUPPORT_QUESTION,
            f"Attribute: {name}\nValue: {field.value!r}\nQuoted passage: {quote}", SUPPORT_OPTIONS,
        )
        if not probabilities:
            return []  # model gone mid-way: judge nothing rather than half
        checked[name] = probabilities
        if probabilities.get("NO", 0.0) >= UNSUPPORTED_MIN:
            unsupported.append(name)
    if checked:
        db.add(AiRun(
            org_id=evidence.org_id, evidence_id=evidence.id, operation="quote_support_check",
            provider=getattr(gateway, "provider", ""), model=getattr(gateway, "model", ""),
            prompt_template_version="quote_support:v3", requested_attributes=list(checked),
            validated_output=checked, latency_ms=getattr(gateway, "last_latency_ms", 0),
        ))
    return unsupported


def required_attribute_names(
    content: Content, frameworks: list[str], artefact_type: str
) -> list[str]:
    """Every attribute any known framework asks of this artefact type — not only
    the subscribed ones.

    Attributes are a property of the document, not of a framework (concept note
    §9.3): the same policy states its password minimum whether or not anyone is
    pursuing PCI yet. Extracting only what today's subscriptions need would make
    Day-1 readiness for a new framework under-report, because the facts it needs
    were never pulled out. One extraction call either way.
    """
    del frameworks  # deliberately ignored; see docstring
    names: list[str] = []
    if artefact_type in TOPIC_POLICIES:
        names.extend(DOCUMENT_CONTROL)  # no requirement asks for these, but quality scoring reads them
    for pack in content.packs:
        for req in pack.requirements:
            for er in req.evidence_requirements:
                if er.artefact_type == artefact_type:
                    names.extend(a for a in er.required_attributes if a not in names)
    return names


def _audit_as_of(db: Session, org_id: str) -> date:
    """The date freshness is judged against.

    An active engagement's period end, when one is set — evidence must be current
    *for the period under audit*, not merely current the day the job ran. Falls
    back to today when the org is self-assessing with no engagement.
    """
    engagement = (
        db.query(Engagement)
        .filter_by(org_id=org_id, status="ACTIVE")
        .order_by(Engagement.period_end.desc())
        .first()
    )
    if engagement is not None and engagement.period_end is not None:
        return engagement.period_end.date()
    return date.today()


def _required_scope(content: Content, frameworks: list[str], artefact_type: str) -> list[str]:
    """Scope terms the subscribed frameworks expect evidence to cover, taken from
    the content packs rather than hard-coded (PCI wants the CDE named; ISO does not)."""
    terms: list[str] = []
    for code in frameworks:
        for req in content.framework(code).requirements:
            if not any(e.artefact_type == artefact_type for e in req.evidence_requirements):
                continue
            for mapping in req.mappings:
                for cond in mapping.delta_conditions:
                    if cond.attribute in {"systems_covered", "entities_covered",
                                          "locations_covered"} and cond.operator == "contains_all":
                        terms.extend(t for t in cond.value if t not in terms)
    return terms


def _remediation(gap, guidance: str = "") -> str:
    """A gap must say what to actually do, not 'evidence insufficient'.

    `guidance` is the framework's own advice for this clause, when its source
    publishes any (the AI RMF Playbook's suggested actions — see
    app/content/nist-ai-rmf-1.0.yaml). Appended rather than substituted: the
    generic sentence names the concrete attribute that failed, which the
    framework's clause-level advice cannot.
    """
    if gap.kind == "STALE":
        base = (f"This evidence is no longer current ({gap.actual}; required {gap.required}). "
                f"Perform the activity again for the period under audit and upload the new "
                f"artefact as a version of this evidence.")
    elif gap.kind == "MISSING_ATTRIBUTE":
        base = (f"The evidence does not state '{gap.attribute}'. Update the document to "
                f"state it explicitly, obtain approval and upload a revised version.")
    else:
        base = (f"Current evidence states {gap.attribute}={gap.actual!r}; the requirement "
                f"expects {gap.required!r}. Update the control to meet it, obtain approval "
                f"and upload a revised version.")
    advice = " ".join((guidance or "").split())
    return f"{base}\n\nFramework guidance: {advice}" if advice else base


def _ensure_org_control(db: Session, org_id: str, framework: str, clause: str) -> OrgControl:
    control = db.query(OrgControl).filter_by(
        org_id=org_id, framework=framework, clause=clause
    ).one_or_none()
    if control is None:
        control = OrgControl(org_id=org_id, framework=framework, clause=clause)
        db.add(control)
        db.flush()
    return control


def _adopt_gap_from_earlier_version(db: Session, link: EvidenceControlLink, evidence: Evidence,
                                    kind: str, attribute: str) -> GapRow | None:
    """The still-OPEN gap this same requirement raised on an earlier version, moved onto `link`.

    Each evidence version has its own links, so a requirement that kept failing was
    raised again on every upload: the old gap stayed OPEN and a second gap and task
    appeared beside it, which made a partial fix *raise* the open counts. Carrying
    the row forward keeps one gap per requirement, with its task, owner, due date
    and priority. A locked link belongs to the version the auditor reviewed, so its
    gaps stay where they are.
    """
    ancestor_id = evidence.supersedes_id
    while ancestor_id:
        ancestor = db.get(Evidence, ancestor_id)
        if ancestor is None:
            return None
        row = (
            db.query(GapRow)
            .join(EvidenceControlLink, GapRow.link_id == EvidenceControlLink.id)
            .filter(EvidenceControlLink.evidence_id == ancestor.id,
                    EvidenceControlLink.framework == link.framework,
                    EvidenceControlLink.clause == link.clause,
                    EvidenceControlLink.locked_by_engagement_id.is_(None),
                    GapRow.kind == kind, GapRow.attribute == attribute,
                    GapRow.status == "OPEN")
            .first()
        )
        if row is not None:
            row.link_id = link.id
            return row
        ancestor_id = ancestor.supersedes_id
    return None


def _reconcile_gaps(db: Session, link: EvidenceControlLink, new_gaps, evidence,
                    actor_label: str = "", request_id: str = "",
                    guidance: str = "") -> None:
    """OPEN -> RESOLVED_BY_EVIDENCE when a gap stops reproducing. Never delete a row."""
    existing_open = {
        (g.kind, g.attribute): g
        for g in db.query(GapRow).filter_by(link_id=link.id, status="OPEN")
    }
    new_by_key = {(g.kind, g.attribute): g for g in new_gaps}

    for key, row in existing_open.items():
        if key not in new_by_key:
            row.status = "RESOLVED_BY_EVIDENCE"
            row.resolved_at = datetime.now(timezone.utc)
            row.resolved_by_evidence_id = getattr(evidence, "id", None)
            row.resolution_reason = "attribute now satisfies the requirement"
            for task in db.query(TaskRow).filter_by(gap_id=row.id, status="OPEN"):
                task.status = "DONE"
            ciso_sync.push_gap_resolution(db, actor_label, request_id, row, link.evidence.org_id)

    for key, gap in new_by_key.items():
        row = existing_open.get(key) or _adopt_gap_from_earlier_version(
            db, link, evidence, *key)
        actual = str(gap.actual) if gap.actual is not None else None
        required = str(gap.required) if gap.required is not None else None
        if row is not None:
            row.detail = gap.detail  # same occurrence, refreshed with the latest values
            row.actual_value = actual
            row.required_value = required
            row.required_action = _remediation(gap, guidance)
        else:
            row = GapRow(
                link_id=link.id, kind=gap.kind, attribute=gap.attribute, detail=gap.detail,
                actual_value=actual, required_value=required,
                required_action=_remediation(gap, guidance),
            )
            db.add(row)
            db.flush()
            control = _ensure_org_control(db, evidence.org_id, link.framework, link.clause)
            db.add(TaskRow(
                gap_id=row.id,
                org_id=evidence.org_id,
                org_control_id=control.id,
                title=f"{link.framework} {link.clause}: remediate {gap.attribute}",
                # No model-suggested priority: tried 2026-09-24 against
                # qwen2.5vl:7b and every gap (missing MFA down to a missing
                # version number) came back HIGH at 0.52-0.74 — no signal,
                # ~2.3s per gap. People set priority via PATCH /tasks/{id}.
            ))


def _store_attributes(db: Session, evidence: Evidence, run) -> None:
    """Normalized provenance rows, replacing this version's previous extraction."""
    db.query(EvidenceAttribute).filter_by(evidence_id=evidence.id).delete(synchronize_session=False)
    for name, field in run.fields.items():
        db.add(EvidenceAttribute(
            evidence_id=evidence.id, name=name, value_json={"v": field.value},
            confidence=field.confidence, extraction_method=field.extraction_method,
            sources=[s.model_dump() for s in field.sources],
        ))


def _upsert_org_commitments(db: Session, evidence: Evidence, run) -> None:
    """A POLICY's own stated values become this org's commitments for whatever
    organization-defined parameters a content pack references (see
    docs/adr/013-organization-defined-commitments.md). Every extracted attribute
    is stored unconditionally — ponytail: no lookup of "which attributes matter"
    here, only the ones a requirement actually reads via
    org_defined_max_age_attribute are ever consulted."""
    if evidence.artefact_type != "POLICY":
        return
    existing = {
        c.attribute: c
        for c in db.query(OrgCommitment).filter_by(org_id=evidence.org_id)
    }
    now = datetime.now(timezone.utc)
    for name, field in run.fields.items():
        if field.value is None:
            continue
        row = existing.get(name)
        if row is None:
            row = OrgCommitment(org_id=evidence.org_id, attribute=name)
            db.add(row)
        row.value_json = {"v": field.value}
        row.source_evidence_id = evidence.id
        row.updated_at = now


def _org_commitments(db: Session, org_id: str) -> dict:
    return {
        c.attribute: c.value
        for c in db.query(OrgCommitment).filter_by(org_id=org_id)
    }


def link_commitment_stale(
    db: Session, content: Content, org_id: str, link: EvidenceControlLink
) -> tuple[bool, str]:
    """Has this link's org-defined ceiling changed since it was last evaluated?

    Read-time only — this never rewrites a link. Per the answered design
    question (docs/adr/013), a changed commitment is surfaced as a flag for the
    org/owner to act on via the existing manual reprocess endpoint, not an
    automatic bulk re-evaluation.
    """
    attrs = org_defined_attributes(content, link.framework, link.clause)
    if not attrs:
        return False, ""
    changed = [
        c for c in db.query(OrgCommitment)
        .filter(OrgCommitment.org_id == org_id, OrgCommitment.attribute.in_(attrs))
        if c.updated_at > link.evaluated_at
    ]
    if not changed:
        return False, ""
    names = ", ".join(sorted(c.attribute for c in changed))
    return True, (f"the organisation's policy commitment for {names} changed after this "
                  f"control was last evaluated on {link.evaluated_at.date().isoformat()} "
                  f"— upload a new version of the evidence to re-check it against the "
                  f"current commitment")


def _resolve_gaps_from_earlier_versions(
    db: Session, evidence: Evidence, still_failing: set[tuple], evaluated: set[tuple],
    actor_label: str = "", request_id: str = "",
) -> None:
    """A newer version closes the older version's gaps.

    Gaps live on a link, and each evidence version gets its own links, so without
    this an OPEN gap raised by V1 would stay open forever even after V2 fixed it.
    Walks back the supersedes chain and resolves any gap this version no longer
    reproduces — the row is marked RESOLVED_BY_EVIDENCE, never deleted.
    """
    ancestor_id = evidence.supersedes_id
    while ancestor_id:
        ancestor = db.get(Evidence, ancestor_id)
        if ancestor is None:
            return
        for link in db.query(EvidenceControlLink).filter_by(evidence_id=ancestor.id):
            if (link.framework, link.clause) not in evaluated:
                continue  # not re-checked by this version; leave its gaps alone
            for gap in db.query(GapRow).filter_by(link_id=link.id, status="OPEN"):
                if (link.framework, link.clause, gap.kind, gap.attribute) in still_failing:
                    continue
                gap.status = "RESOLVED_BY_EVIDENCE"
                gap.resolved_at = datetime.now(timezone.utc)
                gap.resolved_by_evidence_id = evidence.id
                gap.resolution_reason = (
                    f"resolved by evidence version {evidence.version}"
                )
                for task in db.query(TaskRow).filter_by(gap_id=gap.id, status="OPEN"):
                    task.status = "DONE"
                ciso_sync.push_gap_resolution(db, actor_label, request_id, gap, evidence.org_id)
        ancestor_id = ancestor.supersedes_id


def process_evidence(db: Session, content: Content, evidence: Evidence, actor_label: str,
                     request_id: str = "") -> None:
    """Full pipeline for one evidence version, advancing status as it goes.

    The *whole* pipeline is guarded, not just extraction. This runs as a
    background task (app/routers/evidence.py), and an exception escaping it
    reaches nothing that would record it — main.py's handler covers requests,
    not background tasks — leaving the row in a non-terminal status forever
    while the frontend polls it indefinitely. Every failure must end at FAILED
    with a reason instead.
    """
    try:
        _run_pipeline(db, content, evidence, actor_label, request_id)
    except Exception as exc:  # noqa: BLE001 - any pipeline failure must be visible, not silent
        logger.exception("evidence_processing_failed evidence=%s", evidence.id)
        # A mid-transaction error leaves the session needing a rollback; without
        # this the FAILED write itself fails and the row stays stuck anyway.
        db.rollback()
        set_status(db, evidence, "FAILED", str(exc))
    finally:
        # Closes any watching stream whichever way the run ended — a browser
        # must never be left holding an open connection to a finished run.
        events.publish(evidence.id, "done", {"evidence_id": evidence.id})


def _run_pipeline(db: Session, content: Content, evidence: Evidence, actor_label: str,
                  request_id: str) -> None:
    org = db.get(Organization, evidence.org_id)
    storage = get_storage()

    set_status(db, evidence, "EXTRACTING")
    data = storage.get(evidence.storage_key)
    # Checked once, upfront: a password-protected file failing to extract
    # anything is a different problem than a scan needing OCR or the model
    # being down, and the status set below says so plainly instead of guessing.
    attr_names = required_attribute_names(content, org.frameworks, evidence.artefact_type)
    if evidence.mime_type == "application/vnd.grc.connector+json":
        payload = json.loads(data)
        source = str(payload["source"])
        supplied = payload["attributes"]
        text, method = data.decode("utf-8"), "connector"
        run = ExtractionRun(
            fields={
                name: ExtractedField(
                    value=supplied.get(name),
                    confidence=1.0 if name in supplied else None,
                    extraction_method="connector" if name in supplied else "none",
                    sources=[Source(quote=f"{source} API: {name}")] if name in supplied else [],
                )
                for name in attr_names
            },
            model="api", provider=source, prompt_template_version="connector:v1",
        )
    else:
        if is_encrypted_pdf(evidence.filename, data):
            evidence.is_encrypted = True
        # The uploader's model choice, if any (Evidence.ai_model/ai_vision_model)
        # — falls back to the server's env-configured default when unset.
        gateway = gateway_for(evidence.ai_model, evidence.ai_vision_model)
        text, method = read_document(evidence.filename, data, gateway=gateway)

        set_status(db, evidence, "ANALYZING")
        # Stream only while a browser is actually watching this upload: the
        # streamed values are a live preview, the persisted rows below are the
        # truth (app/events.py). Nobody watching -> the ordinary blocking call.
        if events.has_subscribers(evidence.id):
            run = extract_attributes_streaming(
                text, attr_names, method,
                on_attribute=lambda name, field: events.publish(
                    evidence.id, "attribute",
                    {"name": name, "value": field.value, "confidence": field.confidence,
                     "extraction_method": field.extraction_method,
                     "sources": [s.model_dump() for s in field.sources]},
                ),
                gateway=gateway,
            )
        else:
            run = extract_attributes(text, attr_names, method, gateway=gateway)
        _restore_cadence_words(run)

    set_status(db, evidence, "ANALYZING")

    # Asked before evaluating, acted on only at the end: a mistyped file still
    # gets evaluated as declared (that is what was asked for), it just can't
    # land as READY without a human looking at the type.
    type_mismatch, unsupported = "", []
    if method != "connector" and run.status != "UNAVAILABLE":
        type_mismatch = _type_mismatch(db, gateway, evidence, text)
    if method != "connector" and run.status == "OK":
        unsupported = _unsupported_values(db, gateway, evidence, run)

    confidences = [f.confidence for f in run.fields.values() if f.confidence is not None]
    db.add(AiRun(
        org_id=evidence.org_id, evidence_id=evidence.id, operation="attribute_extraction",
        provider=run.provider, model=run.model, prompt_template_version=run.prompt_template_version,
        requested_attributes=attr_names,
        validated_output={k: v.model_dump() for k, v in run.fields.items()},
        confidence=(sum(confidences) / len(confidences)) if confidences else None,
        latency_ms=run.latency_ms, status=run.status,
    ))

    attributes = {name: field.value for name, field in run.fields.items()}
    evidence.extracted_attributes = {name: field.model_dump() for name, field in run.fields.items()}
    _store_attributes(db, evidence, run)
    _upsert_org_commitments(db, evidence, run)

    quality = score_evidence(
        attributes, attr_names,
        sources={n: [s.model_dump() for s in f.sources] for n, f in run.fields.items()},
        extraction_methods={n: f.extraction_method for n, f in run.fields.items()},
        required_scope=_required_scope(content, org.frameworks, evidence.artefact_type),
        as_of=_audit_as_of(db, evidence.org_id),
        native_readable=bool(text and text.strip() and method != "none"),
    )
    evidence.quality_score = quality.score
    evidence.quality_detail = quality.to_dict()

    set_status(db, evidence, "EVALUATING")
    existing = {
        (l.framework, l.clause): l
        for l in db.query(EvidenceControlLink).filter_by(evidence_id=evidence.id)
    }

    still_failing: set[tuple] = set()
    evaluated: set[tuple] = set()

    as_of = _audit_as_of(db, evidence.org_id)
    org_commitments = _org_commitments(db, evidence.org_id)
    provenance_trail: list[dict] = []
    for link in evaluate(attributes, evidence.artefact_type, org.frameworks, content, as_of,
                         org_commitments):
        evaluated.add((link.framework, link.clause))
        still_failing.update(
            (link.framework, link.clause, g.kind, g.attribute) for g in link.gaps
        )
        row = existing.get((link.framework, link.clause))
        if row is not None and row.locked:
            continue  # defensive: this function must never overwrite a locked verdict

        _ensure_org_control(db, evidence.org_id, link.framework, link.clause)
        if row is None:
            row = EvidenceControlLink(
                evidence_id=evidence.id, framework=link.framework, clause=link.clause
            )
            db.add(row)
        row.ucos = list(link.ucos)
        row.verdict = link.verdict
        row.ai_model = run.model
        row.ai_prompt_version = PROMPT_VERSION
        row.ai_confidence = _link_confidence(link, run)
        row.rationale = f"{len(link.gaps)} gap(s)" if link.gaps else "all conditions met"
        row.evaluated_at = datetime.now(timezone.utc)
        provenance.stamp(db, content, row, link, evidence.artefact_type, attributes, as_of,
                         org_commitments)
        provenance_trail.append({"framework": link.framework, "clause": link.clause,
                                 "verdict": link.verdict,
                                 "evaluation_hash": row.evaluation_hash})
        # Same gateway the extraction call above already checked — skip the whole
        # narration step rather than repeat a doomed health check per link when
        # the model was already unavailable this run.
        requirement = content.requirement(link.framework, link.clause)
        if run.status != "UNAVAILABLE" and method != "connector":
            title = requirement.title if requirement else ""
            row.nutshell = generate_nutshell(
                link.framework, link.clause, title, link.verdict,
                [{"attribute": g.attribute, "actual": g.actual, "required": g.required,
                  "detail": g.detail} for g in link.gaps],
                evidence.extracted_attributes,
            )
            row.nutshell_model = run.model
            row.nutshell_prompt_version = NUTSHELL_PROMPT_VERSION
        db.flush()

        _reconcile_gaps(db, row, link.gaps, evidence, actor_label, request_id,
                        guidance=requirement.guidance if requirement else "")

        # Each framework's result as it lands, rather than all of them at the
        # end — the same rows the client will re-read from the API when the
        # run finishes, just visible sooner.
        events.publish(evidence.id, "link", {
            "id": row.id, "framework": link.framework, "clause": link.clause,
            "verdict": link.verdict, "locked": row.locked,
            "gaps": [
                {"kind": g.kind, "attribute": g.attribute, "detail": g.detail,
                 "actual_value": None if g.actual is None else str(g.actual),
                 "required_value": None if g.required is None else str(g.required)}
                for g in link.gaps
            ],
        })

    _resolve_gaps_from_earlier_versions(db, evidence, still_failing, evaluated,
                                        actor_label, request_id)

    audit_log.record(
        db, actor=actor_label, action="EVIDENCE_PROCESSED", entity_type="evidence",
        entity=evidence.id, org_id=evidence.org_id,
        detail={"attributes": list(attributes), "extraction_status": run.status,
                "quality_score": quality.score, "evaluations": provenance_trail},
        request_id=request_id,
    )
    # An unusable extraction is flagged for a human, never quietly accepted.
    # Encryption takes priority in the message even if the model also happened
    # to be down: a locked file would have extracted nothing regardless, and
    # "the model was unavailable" would be the wrong thing to tell the user to
    # wait out — the fix is a new, unlocked version, not a re-run.
    if evidence.is_encrypted:
        set_status(db, evidence, "NEEDS_REVIEW",
                  "password-protected — its text could not be read")
    elif run.status in {"INVALID_OUTPUT", "ERROR", "UNAVAILABLE"}:
        # All three mean the verdicts above were computed from no facts: the
        # model returned junk (INVALID_OUTPUT), errored mid-call (ERROR), or
        # was unreachable (UNAVAILABLE). NEEDS_REVIEW says so plainly, and
        # /reprocess can re-run once the model is back (see
        # app/routers/evidence.py, app/monitor.py).
        set_status(db, evidence, "NEEDS_REVIEW", f"extraction {run.status.lower().replace('_', ' ')}")
    elif type_mismatch:
        set_status(db, evidence, "NEEDS_REVIEW", type_mismatch)
    elif unsupported:
        set_status(db, evidence, "NEEDS_REVIEW",
                   f"extracted {', '.join(sorted(unsupported))} not stated by the quoted "
                   f"source — check before relying on the verdicts")
    else:
        set_status(db, evidence, "READY")


def _link_confidence(link, run) -> float | None:
    """Average confidence of the attributes this requirement actually consulted."""
    names = {g.attribute for g in link.gaps} | set(_attributes_of(link, run))
    values = [run.fields[n].confidence for n in names
              if n in run.fields and run.fields[n].confidence is not None]
    return (sum(values) / len(values)) if values else None


def _attributes_of(link, run) -> list[str]:
    # ponytail: Link doesn't carry the attribute set it consulted, so a clean link
    # falls back to every extracted attribute. Tighten when Link records them.
    return list(run.fields) if not link.gaps else []
