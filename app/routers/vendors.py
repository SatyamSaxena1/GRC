"""The vendor register (ADR-042): who the organisation depends on, how risky each is by fixed rules, and when
each is next due for review. An organisation admin writes; a compliance viewer reads. Every change is in the
audit chain with before and after state."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log, vendors
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import User, Vendor, VendorReport
from app.storage import get_storage
from app.upload_security import UploadRejected, get_scanner, validate_upload

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


def _attestation(v: Vendor, reports: list[VendorReport]) -> dict:
    """Where the vendor's attestation comes from: a current report (the rule in app/vendors.py), the manual
    tick, or nothing. A report wins because it can be opened and checked."""
    current = [r for r in reports if vendors.attests(r.report_type, r.valid_until)]
    if current:
        return {"on_file": True, "source": "report", "valid_until": max(r.valid_until for r in current).isoformat()}
    return {"on_file": v.has_attestation, "source": "manual" if v.has_attestation else "none", "valid_until": None}


def _report_out(r: VendorReport) -> dict:
    return {"id": r.id, "report_type": r.report_type, "valid_until": r.valid_until.isoformat(), "filename": r.filename,
            "size_bytes": r.size_bytes, "sha256": r.sha256, "uploaded_by": r.uploaded_by,
            "uploaded_at": r.uploaded_at.isoformat(), "counts": vendors.attests(r.report_type, r.valid_until)}


def _out(v: Vendor, owner_email: str | None, reports: list[VendorReport] | None = None) -> dict:
    reports = reports or []
    attestation = _attestation(v, reports)
    risk = vendors.tier(v.data_access, v.criticality, attestation["on_file"])
    return {
        "id": v.id, "name": v.name, "service": v.service, "data_access": v.data_access,
        "criticality": v.criticality, "has_attestation": v.has_attestation, "owner_user_id": v.owner_user_id,
        "owner_email": owner_email, "status": v.status, "notes": v.notes,
        "last_reviewed_at": v.last_reviewed_at.isoformat() if v.last_reviewed_at else None,
        "attestation": attestation, "reports": [_report_out(r) for r in reports],
        "tier": risk, "points": vendors.points(v.data_access, v.criticality, attestation["on_file"]),
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
    by_vendor: dict[str, list[VendorReport]] = {}
    for r in db.query(VendorReport).filter_by(org_id=actor.org_id).order_by(VendorReport.uploaded_at.desc()):
        by_vendor.setdefault(r.vendor_id, []).append(r)
    return [_out(v, emails.get(v.owner_user_id), by_vendor.get(v.id)) for v in rows]


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
    return _out(v, _owner_email(db, v.owner_user_id), _reports(db, v))


def _reports(db: Session, v: Vendor) -> list[VendorReport]:
    return db.query(VendorReport).filter_by(org_id=v.org_id, vendor_id=v.id).order_by(VendorReport.uploaded_at.desc()).all()


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
    return _out(v, _owner_email(db, v.owner_user_id), _reports(db, v))


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
                     detail={"name": v.name, "tier": vendors.tier(
                         v.data_access, v.criticality, _attestation(v, _reports(db, v))["on_file"])})
    db.commit()
    return _out(v, _owner_email(db, v.owner_user_id), _reports(db, v))

@router.post("/{vendor_id}/reports")
def attach_report(vendor_id: str, file: UploadFile, report_type: str = Form(...), valid_until: str = Form(...),
                  actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Attach a SOC 2 / ISO 27001 report (or another document) to a vendor. The uploader states the date the
    report stays valid until; the rule in app/vendors.py decides whether it counts. Stored like evidence:
    validated at the trust boundary, immutable, never deleted."""
    _writer(actor)
    v = _load(db, actor, vendor_id)
    if report_type not in vendors.REPORT_TYPES:
        raise HTTPException(422, f"report_type must be one of {', '.join(vendors.REPORT_TYPES)}")
    try:
        until = date.fromisoformat(valid_until)
    except ValueError:
        raise HTTPException(422, "valid_until must be a date like 2027-03-31") from None
    try:
        upload = validate_upload(file.file, file.filename or "")
        get_scanner().scan(upload.data)
    except UploadRejected as exc:
        raise HTTPException(400, str(exc)) from exc
    if db.query(VendorReport).filter_by(org_id=actor.org_id, vendor_id=v.id, sha256=upload.sha256).first():
        raise HTTPException(409, "this exact file is already attached to the vendor")

    report = VendorReport(org_id=actor.org_id, vendor_id=v.id, report_type=report_type, valid_until=until,
                          filename=upload.filename, mime_type=upload.mime_type, size_bytes=upload.size_bytes,
                          sha256=upload.sha256, storage_key="", uploaded_by=actor.label(), uploaded_at=_now())
    db.add(report)
    db.flush()
    report.storage_key = f"tenant/{actor.org_id}/vendor/{v.id}/{report.id}/{upload.filename}"
    get_storage().put(report.storage_key, upload.data)
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="VENDOR_REPORT_ATTACHED",
                     entity_type="vendor", entity=v.id, org_id=actor.org_id,
                     detail={"name": v.name, "report_type": report_type, "valid_until": until.isoformat(),
                             "sha256": upload.sha256, "size_bytes": upload.size_bytes, "counts": vendors.attests(report_type, until)})
    db.commit()
    return _out(v, _owner_email(db, v.owner_user_id), _reports(db, v))


@router.get("/{vendor_id}/reports/{report_id}/file")
def download_report(vendor_id: str, report_id: str, actor: Actor = Depends(current_actor),
                    db: Session = Depends(get_session)):
    """Always a download, never rendered in the page: a vendor's document is untrusted content."""
    _reader(actor)
    report = db.get(VendorReport, report_id)
    if report is None or report.org_id != actor.org_id or report.vendor_id != vendor_id:
        raise HTTPException(404)
    name = report.filename.replace('"', "")
    return Response(content=get_storage().get(report.storage_key), media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store"})
