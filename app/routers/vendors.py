"""The vendor register (ADR-042): who the organisation depends on, how risky each is by fixed rules, and when
each is next due for review. An organisation admin writes; a compliance viewer reads. Every change is in the
audit chain with before and after state."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log, vendors
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import User, Vendor

router = APIRouter(prefix="/vendors", tags=["vendors"])

DataAccess = Literal["NONE", "INTERNAL", "PERSONAL", "SENSITIVE"]
Criticality = Literal["LOW", "MEDIUM", "HIGH"]
MIN_REVIEW_WORDS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _reader(actor: Actor) -> Actor:
    if actor.role not in ("ORG_ADMIN", "COMPLIANCE_VIEWER") or actor.engagement_id or not actor.org_id:
        raise HTTPException(403, "the vendor register is for an organisation admin or compliance viewer")
    return actor


def _writer(actor: Actor) -> Actor:
    if actor.role != "ORG_ADMIN" or actor.engagement_id:
        raise HTTPException(403, "only an organisation admin may change the vendor register")
    return actor


def _out(v: Vendor, owner_email: str | None) -> dict:
    risk = vendors.tier(v.data_access, v.criticality, v.has_attestation)
    return {
        "id": v.id, "name": v.name, "service": v.service, "data_access": v.data_access,
        "criticality": v.criticality, "has_attestation": v.has_attestation, "owner_user_id": v.owner_user_id,
        "owner_email": owner_email, "status": v.status, "notes": v.notes,
        "last_reviewed_at": v.last_reviewed_at.isoformat() if v.last_reviewed_at else None,
        "tier": risk, "points": vendors.points(v.data_access, v.criticality, v.has_attestation),
        "review_every_days": vendors.REVIEW_EVERY_DAYS[risk],
        "review": vendors.review(v.status, risk, v.last_reviewed_at),
    }


def _state(v: Vendor) -> dict:
    return {"name": v.name, "service": v.service, "data_access": v.data_access, "criticality": v.criticality,
            "has_attestation": v.has_attestation, "owner_user_id": v.owner_user_id, "status": v.status}


def _owner_email(db: Session, user_id: str | None) -> str | None:
    user = db.get(User, user_id) if user_id else None
    return user.email if user else None


def _check_owner(db: Session, actor: Actor, user_id: str | None) -> None:
    if user_id is not None:
        owner = db.get(User, user_id)  # RLS: another organisation's user is simply not there
        if owner is None or owner.org_id != actor.org_id:
            raise HTTPException(422, "owner must be a user of this organisation")


class VendorIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    service: str = Field(default="", max_length=300)
    data_access: DataAccess = "NONE"
    criticality: Criticality = "LOW"
    has_attestation: bool = False
    owner_user_id: str | None = None
    notes: str = Field(default="", max_length=2000)


class VendorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    service: str | None = Field(default=None, max_length=300)
    data_access: DataAccess | None = None
    criticality: Criticality | None = None
    has_attestation: bool | None = None
    owner_user_id: str | None = None
    status: Literal["ACTIVE", "OFFBOARDED"] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ReviewIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


@router.get("")
def list_vendors(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _reader(actor)
    rows = db.query(Vendor).filter_by(org_id=actor.org_id).order_by(Vendor.name).all()
    emails = {u.id: u.email for u in db.query(User).filter_by(org_id=actor.org_id)}
    return [_out(v, emails.get(v.owner_user_id)) for v in rows]


@router.post("")
def add_vendor(body: VendorIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _writer(actor)
    _check_owner(db, actor, body.owner_user_id)
    v = Vendor(org_id=actor.org_id, created_by=actor.label(), created_at=_now(), **body.model_dump())
    db.add(v)
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="VENDOR_ADDED",
                     entity_type="vendor", entity=v.id, org_id=actor.org_id, after=_state(v))
    db.commit()
    return _out(v, _owner_email(db, v.owner_user_id))


def _load(db: Session, actor: Actor, vendor_id: str) -> Vendor:
    v = db.get(Vendor, vendor_id)
    if v is None or v.org_id != actor.org_id:
        raise HTTPException(404)
    return v


@router.patch("/{vendor_id}")
def update_vendor(vendor_id: str, body: VendorPatch, actor: Actor = Depends(current_actor),
                  db: Session = Depends(get_session)):
    _writer(actor)
    v = _load(db, actor, vendor_id)
    changes = body.model_dump(exclude_unset=True)
    if "owner_user_id" in changes:
        _check_owner(db, actor, changes["owner_user_id"])
    before = _state(v)
    for key, value in changes.items():
        if key == "notes":
            v.notes = value or ""
        else:
            setattr(v, key, value)
    if _state(v) != before:
        action = "VENDOR_OFFBOARDED" if before["status"] != "OFFBOARDED" and v.status == "OFFBOARDED" else "VENDOR_UPDATED"
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action=action,
                         entity_type="vendor", entity=v.id, org_id=actor.org_id, before=before, after=_state(v))
    db.commit()
    return _out(v, _owner_email(db, v.owner_user_id))


@router.post("/{vendor_id}/review")
def record_review(vendor_id: str, body: ReviewIn, actor: Actor = Depends(current_actor),
                  db: Session = Depends(get_session)):
    """Record that the vendor was reviewed now. The note says what was checked; it must say something."""
    _writer(actor)
    v = _load(db, actor, vendor_id)
    if v.status == "OFFBOARDED":
        raise HTTPException(409, "an offboarded vendor needs no review")
    note = body.note.strip()
    if len(re.findall(r"\w+", note)) < MIN_REVIEW_WORDS:
        raise HTTPException(422, f"say what was reviewed, in at least {MIN_REVIEW_WORDS} words")
    previous = v.last_reviewed_at
    v.last_reviewed_at = _now()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="VENDOR_REVIEWED",
                     entity_type="vendor", entity=v.id, org_id=actor.org_id, reason=note,
                     before={"last_reviewed_at": previous.isoformat() if previous else None},
                     after={"last_reviewed_at": v.last_reviewed_at.isoformat()},
                     detail={"name": v.name, "tier": vendors.tier(v.data_access, v.criticality, v.has_attestation)})
    db.commit()
    return _out(v, _owner_email(db, v.owner_user_id))
