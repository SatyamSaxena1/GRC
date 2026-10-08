"""Auditor-held audit checkpoints (ADR-023; the external anchor idea from the earlier Trishul
attempt, held by the auditor instead of an object-lock bucket).

A checkpoint is a small signed statement: "this organisation's audit chain had N events and
its head hashed to H". The auditor downloads it and keeps it. Later, the same chain must still
contain that exact event at that position, and must still verify from its genesis to its
current head: so nothing at or before the checkpoint can have been edited, inserted or deleted,
without the platform's signature on the checkpoint being forged too.

Signing is Ed25519 with the key in AUDIT_CHECKPOINT_SIGNING_KEY (base64 of the 32-byte raw
private key). Retired public keys stay verifiable via AUDIT_CHECKPOINT_RETIRED_KEYS (comma-
separated base64 raw public keys). No key configured means no checkpoints: an unsigned one
would prove nothing about who issued it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy.orm import Session

from app import audit_log
from app.models import AuditEvent

FORMAT = "grc-audit-checkpoint/1"


class NotConfigured(RuntimeError):
    pass


def canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _raw_public(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def key_id(public: Ed25519PublicKey) -> str:
    return hashlib.sha256(_raw_public(public)).hexdigest()[:16]


def _signing_key() -> Ed25519PrivateKey:
    raw = os.environ.get("AUDIT_CHECKPOINT_SIGNING_KEY", "").strip()
    if not raw:
        raise NotConfigured("checkpoint signing is not configured (AUDIT_CHECKPOINT_SIGNING_KEY)")
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))


def public_keys() -> dict[str, Ed25519PublicKey]:
    """Every key a checkpoint may have been signed with, current first."""
    keys: dict[str, Ed25519PublicKey] = {}
    try:
        current = _signing_key().public_key()
        keys[key_id(current)] = current
    except NotConfigured:
        pass
    for raw in filter(None, (k.strip() for k in os.environ.get("AUDIT_CHECKPOINT_RETIRED_KEYS", "").split(","))):
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw))
        keys.setdefault(key_id(public), public)
    return keys


def published_keys() -> list[dict]:
    return [{"kid": kid, "alg": "Ed25519", "public_key": base64.b64encode(_raw_public(k)).decode()}
            for kid, k in public_keys().items()]


def _previous(db: Session, chain: str) -> dict | None:
    last = (db.query(AuditEvent).filter_by(chain=chain, action="AUDIT_CHECKPOINT_ISSUED")
            .order_by(AuditEvent.chain_seq.desc()).first())
    return {"chain_seq": last.detail["chain_seq"], "head_hash": last.detail["head_hash"]} if last else None


def issue(db: Session, org_id: str, actor_label: str, request_id: str = "",
          issuer: str | None = None) -> dict:
    """Sign the current head of this organisation's chain. Refuses to certify a broken chain."""
    key = _signing_key()
    chain = audit_log.chain_of(org_id)
    report = audit_log.verify(db, chain)
    if not report.ok:
        raise ValueError("the audit chain does not verify: " + "; ".join(report.problems))
    if report.events == 0:
        raise ValueError("this organisation has no audit events yet")
    genesis = db.query(AuditEvent).filter_by(chain=chain, chain_seq=1).one()
    body = {
        "format": FORMAT,
        "issuer": issuer or os.environ.get("PUBLIC_BASE_URL", "grc"),
        "org_id": org_id,
        "chain": chain,
        "chain_seq": report.head_seq,
        "head_hash": report.head_hash,
        "event_count": report.events,
        "genesis_hash": genesis.entry_hash,
        "previous": _previous(db, chain),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    public = key.public_key()
    signed = {**body, "signature": {"alg": "Ed25519", "kid": key_id(public),
                                    "value": base64.b64encode(key.sign(canonical(body))).decode()}}
    audit_log.record(db, actor=actor_label, action="AUDIT_CHECKPOINT_ISSUED", entity_type="audit_chain",
                     entity=chain, org_id=org_id, request_id=request_id,
                     detail={"chain_seq": body["chain_seq"], "head_hash": body["head_hash"],
                             "kid": key_id(public)})
    return signed


def verify_signature(checkpoint: dict) -> list[str]:
    signature = checkpoint.get("signature") or {}
    body = {k: v for k, v in checkpoint.items() if k != "signature"}
    if checkpoint.get("format") != FORMAT:
        return [f"not a {FORMAT} checkpoint"]
    key = public_keys().get(signature.get("kid", ""))
    if key is None or signature.get("alg") != "Ed25519":
        return ["signed with a key this platform does not know"]
    try:
        key.verify(base64.b64decode(signature.get("value", "")), canonical(body))
    except (InvalidSignature, ValueError):
        return ["the signature does not match the checkpoint: it was altered or not issued here"]
    return []


def verify(db: Session, org_id: str, checkpoint: dict) -> dict:
    """Is everything this checkpoint certifies still in the chain, unchanged?"""
    problems = verify_signature(checkpoint)
    chain = audit_log.chain_of(org_id)
    report = audit_log.verify(db, chain)
    if not problems:
        if checkpoint.get("org_id") != org_id:
            problems.append("this checkpoint belongs to another organisation")
        else:
            seq = checkpoint.get("chain_seq")
            event = db.query(AuditEvent).filter_by(chain=chain, chain_seq=seq).one_or_none()
            if event is None:
                problems.append(f"event {seq} the checkpoint certifies is no longer in the chain")
            elif event.entry_hash != checkpoint.get("head_hash"):
                problems.append(f"event {seq} has changed since the checkpoint")
            genesis = db.query(AuditEvent).filter_by(chain=chain, chain_seq=1).one_or_none()
            if genesis is None or genesis.entry_hash != checkpoint.get("genesis_hash"):
                problems.append("the chain was restarted since the checkpoint")
        if not report.ok:
            problems += report.problems
    return {"verified": not problems, "problems": problems,
            "checkpoint_seq": checkpoint.get("chain_seq"), "current_head_seq": report.head_seq,
            "events_since": max(0, report.head_seq - (checkpoint.get("chain_seq") or 0))}


def export_events(db: Session, org_id: str) -> list[dict]:
    """Everything an offline verifier needs: the chain, and the pre-chain rows its genesis sealed."""
    chain = audit_log.chain_of(org_id)
    owner = (AuditEvent.org_id.is_(None) if chain == audit_log.PLATFORM else AuditEvent.org_id == org_id)
    rows = (db.query(AuditEvent).filter((AuditEvent.chain == chain) | (owner & AuditEvent.hash_version.is_(None)))
            .order_by(AuditEvent.chain_seq.is_(None).desc(), AuditEvent.seq, AuditEvent.chain_seq, AuditEvent.id))
    return [{"id": e.id, "seq": e.seq, "chain": e.chain, "chain_seq": e.chain_seq,
             "hash_version": e.hash_version, "org_id": e.org_id, "actor": e.actor, "action": e.action,
             "entity_type": e.entity_type, "entity": e.entity, "detail": e.detail, "before": e.before,
             "after": e.after, "reason": e.reason, "at": audit_log._ts(e.at), "prev_hash": e.prev_hash,
             "entry_hash": e.entry_hash} for e in rows]
