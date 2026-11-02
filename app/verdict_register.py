"""The verdict register (ADR-029): an immutable history of every verdict on a control.

A locked verdict can be reopened and replaced, but the original row is never altered, hidden or
deleted. A reopening or replacement is a new VerdictRecord pointing at the one it supersedes, with
a mandatory reason. Each record is anchored in the hash-chained audit log: the audit event carries
the record's hash, and the record stores the event's chain position and hash, so the register can
be verified against the chain offline (scripts/verify_audit_export.py --register).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit_log
from app.models import EvidenceControlLink, VerdictRecord

REASON_CODES = {
    "NEW_EVIDENCE": "New evidence changes the picture",
    "RULES_CHANGED": "The rules the original verdict was judged against have changed",
    "ERROR_IN_ORIGINAL": "The original verdict was wrong",
    "SCOPE_CHANGE": "The scope of the audit or the control changed",
    "OTHER": "Another reason, stated in full below",
}
# Normal flow (a first opinion, a lock) is not a supersession and needs no reason code.
RECORDED = "RECORDED"

MIN_REASONING_CHARS = 15
MIN_REASONING_WORDS = 3
_BOILERPLATE = {"n/a", "na", "none", "nil", "test", "testing", "see above", "as discussed", "per request",
                "per policy", "reopen", "reopening", "ok", "okay", "reviewed", "because", "asdf"}

HASHED_FIELDS = ("id", "org_id", "link_id", "seq", "supersedes_id", "kind", "verdict", "engine_verdict",
                 "rule_hash", "evaluation_hash", "engine_version", "decided_by", "decided_by_user_id",
                 "engagement_id", "decided_at", "reason_code", "reasoning", "origin")


def check_reasoning(text: str) -> str:
    """The reason for reopening or replacing a verdict: specific, or refused."""
    text = (text or "").strip()
    words = re.findall(r"\w+", text)
    if (len(text) < MIN_REASONING_CHARS or len(words) < MIN_REASONING_WORDS
            or text.lower().rstrip(".!") in _BOILERPLATE or len(set(text.lower().replace(" ", ""))) < 5):
        raise ValueError(f"reasoning must say what changed, in at least {MIN_REASONING_WORDS} words "
                         f"and {MIN_REASONING_CHARS} characters; boilerplate is refused")
    return text


def _ts(at: datetime) -> str:
    return at.replace(tzinfo=None).isoformat(timespec="microseconds")


def record_hash(fields: dict) -> str:
    """Covers every field but the audit anchors (which cannot exist before the hash does).
    Mirrored, not imported, by the migration and by scripts/verify_audit_export.py."""
    body = {k: (_ts(fields[k]) if k == "decided_at" else fields[k]) for k in HASHED_FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def history(db: Session, link_id: str) -> list[VerdictRecord]:
    return list(db.execute(select(VerdictRecord).where(VerdictRecord.link_id == link_id)
                           .order_by(VerdictRecord.seq)).scalars())


def head(db: Session, link_id: str) -> VerdictRecord | None:
    return db.execute(select(VerdictRecord).where(VerdictRecord.link_id == link_id)
                      .order_by(VerdictRecord.seq.desc()).limit(1)).scalar_one_or_none()


def append(db: Session, actor, link: EvidenceControlLink, *, kind: str, verdict: str | None,
           reason_code: str, reasoning: str = "", org_id: str) -> VerdictRecord:
    """Add one step to the control's history and record it in the audit chain. The only writer."""
    prior = head(db, link.id)
    fields = {
        "id": str(uuid.uuid4()), "org_id": org_id, "link_id": link.id,
        "seq": prior.seq + 1 if prior else 1, "supersedes_id": prior.id if prior else None,
        "kind": kind, "verdict": verdict, "engine_verdict": link.engine_verdict,
        "rule_hash": link.rule_hash, "evaluation_hash": link.evaluation_hash,
        "engine_version": link.engine_version, "decided_by": actor.label(),
        "decided_by_user_id": actor.user_id, "engagement_id": actor.engagement_id,
        "decided_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "reason_code": reason_code, "reasoning": reasoning, "origin": "LIVE",
    }
    digest = record_hash(fields)
    event = audit_log.record(
        db, actor=actor.label(), request_id=actor.request_id, action="VERDICT_REGISTERED",
        entity_type="evidence_control_link", entity=link.id, org_id=org_id, reason=reasoning,
        detail={"record_id": fields["id"], "record_hash": digest, "seq": fields["seq"], "kind": kind,
                "reason_code": reason_code, "supersedes_id": fields["supersedes_id"],
                "rule_hash": link.rule_hash},
        before=_state(prior), after={"kind": kind, "verdict": verdict})
    record = VerdictRecord(**fields, record_hash=digest, audit_chain_seq=event.chain_seq,
                           audit_entry_hash=event.entry_hash)
    db.add(record)
    db.flush()
    return record


def _state(record: VerdictRecord | None) -> dict | None:
    return {"kind": record.kind, "verdict": record.verdict} if record else None


def _entry(r: VerdictRecord, previous: VerdictRecord | None) -> dict:
    changed = bool(previous and previous.rule_hash and r.rule_hash and previous.rule_hash != r.rule_hash)
    return {
        "id": r.id, "seq": r.seq, "supersedes_id": r.supersedes_id, "kind": r.kind, "verdict": r.verdict,
        "engine_verdict": r.engine_verdict, "rule_hash": r.rule_hash, "evaluation_hash": r.evaluation_hash,
        "engine_version": r.engine_version, "decided_by": r.decided_by,
        "decided_by_user_id": r.decided_by_user_id, "engagement_id": r.engagement_id,
        "decided_at": _ts(r.decided_at), "reason_code": r.reason_code, "reasoning": r.reasoning,
        "origin": r.origin, "record_hash": r.record_hash, "audit_chain_seq": r.audit_chain_seq,
        "audit_entry_hash": r.audit_entry_hash,
        # Visible, not hidden: the verdicts on either side of this step were judged by different rules.
        "rules_changed_since_previous": changed,
    }


def register(db: Session, link: EvidenceControlLink) -> dict:
    """The human-readable view: every step, oldest first, and what is in force now."""
    rows = history(db, link.id)
    entries = [_entry(r, rows[i - 1] if i else None) for i, r in enumerate(rows)]
    decisions = [r for r in rows if r.kind == "DECISION"]
    return {
        "link_id": link.id, "framework": link.framework, "clause": link.clause,
        "current": ({"verdict": rows[-1].verdict, "locked": link.locked, "record_id": rows[-1].id,
                     "state": "REOPENED" if rows[-1].kind == "REOPENED" else "DECIDED"}
                    if rows else None),
        "original_verdict": decisions[0].verdict if decisions else None,
        "entries": entries,
        "not_covered": ("Steps before this register existed are marked origin=MIGRATED and keep only "
                        "what the link row still held; their original reasoning is in the audit log."),
    }


def export(db: Session, org_id: str) -> dict:
    """Every record of one organisation, for offline verification against the audit export."""
    rows = list(db.execute(select(VerdictRecord).where(VerdictRecord.org_id == org_id)
                           .order_by(VerdictRecord.link_id, VerdictRecord.seq)).scalars())
    by_id = {r.id: r for r in rows}
    return {"format": "grc-verdict-register/1", "org_id": org_id,
            "records": [_entry(r, by_id.get(r.supersedes_id)) | {"org_id": r.org_id, "link_id": r.link_id}
                        for r in rows]}
