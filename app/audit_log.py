"""Append-only audit trail, hash-chained per tenant.

Every record links to the previous one in its chain by hash, so a silently edited, inserted
or deleted row breaks verification. Nothing here ever updates or deletes an existing row.

One chain per organisation, plus one `platform` chain for events with no organisation. That
is what row-level security makes possible: a tenant sees exactly its own events plus platform
events, so it can always see its own chain whole and nothing of anyone else's. The single
global chain this replaced was written from those partial views and could not verify on
Postgres (tests/test_rls_postgres.py, the audit-chain canary).

Hash version 2 commits to the chain, its position and the timestamp, as well as the content.
Rows written before per-tenant chains (hash version 1) are never rewritten: the first event of
each chain, CHAIN_GENESIS, records how many there were and a digest of their content, so they
cannot be changed afterwards without detection either.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent

PLATFORM = "platform"
HASH_VERSION = 2


def _digest(prev_hash: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{prev_hash}{body}".encode()).hexdigest()


def _payload(actor, action, entity_type, entity, org_id, detail, before, after, reason) -> dict:
    """The content fields every hash version commits to. One definition, used for both
    writing and verifying, so the two can never disagree."""
    return {
        "actor": actor, "action": action, "entity_type": entity_type, "entity": entity,
        "org_id": org_id, "detail": detail, "before": before, "after": after,
        "reason": reason,
    }


def _ts(at: datetime) -> str:
    return at.replace(tzinfo=None).isoformat(timespec="microseconds")


def _content(e: AuditEvent) -> dict:
    return _payload(e.actor, e.action, e.entity_type, e.entity, e.org_id, e.detail, e.before,
                    e.after, e.reason)


def _v2(e: AuditEvent) -> dict:
    return {**_content(e), "v": HASH_VERSION, "chain": e.chain, "chain_seq": e.chain_seq,
            "at": _ts(e.at)}


def chain_of(org_id: str | None) -> str:
    return org_id or PLATFORM


def _lock(db: Session, chain: str) -> None:
    """Serialize writers of one chain for the rest of the transaction. On SQLite, writes are
    already serialized, and the unique (chain, chain_seq) index turns any race into an error
    rather than a fork."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:c, 0))"), {"c": chain})


def _legacy(db: Session, chain: str, until: datetime | None = None) -> list[AuditEvent]:
    owner = AuditEvent.org_id.is_(None) if chain == PLATFORM else AuditEvent.org_id == chain
    query = select(AuditEvent).where(owner, AuditEvent.hash_version.is_(None))
    if until is not None:
        query = query.where(AuditEvent.at <= until)
    return list(db.execute(query.order_by(AuditEvent.seq, AuditEvent.id)).scalars())


def _legacy_digest(rows: list[AuditEvent]) -> str:
    """Content, id and time of every pre-chain row, in order: editing, adding or removing
    any of them changes this."""
    h = hashlib.sha256()
    for e in rows:
        h.update(json.dumps({**_content(e), "id": e.id, "at": _ts(e.at)}, sort_keys=True,
                            default=str).encode())
    return h.hexdigest()


def _now() -> datetime:
    # Stored naive UTC, exactly as hashed: the value read back must hash the same.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _head(db: Session, chain: str) -> AuditEvent | None:
    return db.execute(select(AuditEvent).where(AuditEvent.chain == chain)
                      .order_by(AuditEvent.chain_seq.desc()).limit(1)).scalar_one_or_none()


def _append(db: Session, chain: str, prev: AuditEvent | None, **fields) -> AuditEvent:
    # Column defaults only apply at INSERT, after the hash is taken: hash exactly what is stored.
    fields = {"detail": {}, "before": None, "after": None, "reason": "", "request_id": "", **fields}
    for text_field in ("actor", "action", "entity_type", "entity", "reason", "request_id"):
        fields[text_field] = fields.get(text_field) or ""
    fields["detail"] = fields["detail"] or {}
    event = AuditEvent(chain=chain, chain_seq=(prev.chain_seq + 1) if prev else 1,
                       hash_version=HASH_VERSION, at=_now(),
                       prev_hash=prev.entry_hash if prev else "", **fields)
    event.seq = event.chain_seq  # the legacy ordering column, kept meaningful within a chain
    event.entry_hash = _digest(event.prev_hash, _v2(event))
    db.add(event)
    db.flush()
    return event


def record(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity: str,
    org_id: str | None = None,
    detail: dict | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str = "",
    request_id: str = "",
) -> AuditEvent:
    db.flush()  # make events added earlier in this transaction visible to the chain
    chain = chain_of(org_id)
    _lock(db, chain)
    head = _head(db, chain)
    if head is None:
        at = _now()
        legacy = _legacy(db, chain, at)
        head = _append(db, chain, None, org_id=org_id, actor="system", action="CHAIN_GENESIS",
                       entity_type="audit_chain", entity=chain,
                       detail={"legacy_events": len(legacy), "legacy_digest": _legacy_digest(legacy),
                               "legacy_until": _ts(at)})
    return _append(db, chain, head, org_id=org_id, actor=actor, action=action,
                   entity_type=entity_type, entity=entity, detail=detail or {}, before=before,
                   after=after, reason=reason, request_id=request_id)


@dataclass
class ChainReport:
    chain: str
    ok: bool
    events: int = 0
    head_seq: int = 0
    head_hash: str = ""
    legacy_events: int = 0
    unchained_after_genesis: int = 0
    broken_at: int | None = None
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def verify(db: Session, chain: str) -> ChainReport:
    """Walk one chain from its genesis: every link, every hash, and the pre-chain rows the
    genesis sealed."""
    report = ChainReport(chain=chain, ok=True)
    events = list(db.execute(select(AuditEvent).where(AuditEvent.chain == chain)
                             .order_by(AuditEvent.chain_seq)).scalars())
    prev_hash = ""
    for expected, e in enumerate(events, start=1):
        if e.chain_seq != expected:
            report.problems.append(f"event {expected} is missing (found {e.chain_seq})")
        elif e.prev_hash != prev_hash or e.entry_hash != _digest(prev_hash, _v2(e)):
            report.problems.append(f"event {e.chain_seq} does not hash to its recorded value")
        if report.problems:
            report.ok, report.broken_at = False, expected
            break
        prev_hash = e.entry_hash
    report.events = len(events)
    if events:
        report.head_seq, report.head_hash = events[-1].chain_seq, events[-1].entry_hash
        genesis = events[0]
        if report.ok and genesis.action != "CHAIN_GENESIS":
            report.ok = False
            report.problems.append("the chain does not start with its genesis event")
        elif report.ok:
            until = datetime.fromisoformat(genesis.detail["legacy_until"])
            sealed = _legacy(db, chain, until)
            report.legacy_events = len(sealed)
            if (len(sealed) != genesis.detail["legacy_events"]
                    or _legacy_digest(sealed) != genesis.detail["legacy_digest"]):
                report.ok = False
                report.problems.append("events from before the chain no longer match its genesis seal")
            # Written by an instance still running the previous code during a deploy: reported,
            # not counted as tampering, and never more than the switchover window's worth.
            report.unchained_after_genesis = len(_legacy(db, chain)) - len(sealed)
    return report


def visible_chains(db: Session) -> list[str]:
    chains = db.execute(select(AuditEvent.chain).where(AuditEvent.chain.is_not(None)).distinct()).scalars()
    return sorted(chains)


def verify_chain(db: Session) -> bool:
    """True when every chain this session can see verifies. Catches tampering."""
    return all(verify(db, chain).ok for chain in visible_chains(db))
