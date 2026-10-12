"""Review Standards (ADR-027): publish, list, activate and try out an organisation's code-review
rules.

Who may do what:
- read: anyone on the organisation's side, and its auditors: the rules are audit evidence;
- publish and activate: ORG_ADMIN only, and each is an audited event in the tenant's chain;
- try a standard against a pasted diff: anyone who may write. Nothing is stored: the diff is
  the client's code (ADR-027).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor, deny_read_only
from app.content.load import load as load_content
from app.db import get_session
from app.models import ReviewStandard
from app.review import diff as diffs
from app.review import engine, standards

router = APIRouter(prefix="/review", tags=["review"])
CONTENT = load_content()
MAX_YAML_BYTES = 200_000
MAX_DIFF_BYTES = 1_000_000


def _payload(row: ReviewStandard) -> dict:
    return {"id": row.id, "name": row.name, "version": row.version, "body_hash": row.body_hash,
            "is_active": row.is_active, "created_by": row.created_by, "created_at": row.created_at.isoformat(),
            "source_yaml": row.source_yaml, "rules": [r["id"] for r in row.body.get("rules", [])]}


def _admin(actor: Actor, what: str) -> None:
    if not actor.can_write:
        raise deny_read_only(actor, what)
    if actor.role != "ORG_ADMIN":
        raise HTTPException(403, f"only an organisation admin can {what}")


def active_standard(db: Session, org_id: str) -> tuple[standards.Standard, str, int | None]:
    """(standard, body_hash, version) in force for an organisation: its active version, or the
    built-in default (version None) until it publishes one."""
    row = db.query(ReviewStandard).filter_by(org_id=org_id, is_active=True).one_or_none()
    if row is None:
        std = standards.default()
        return std, standards.body_hash(std), None
    return standards.Standard(**row.body), row.body_hash, row.version


@router.get("/standards")
def list_standards(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    rows = (db.query(ReviewStandard).filter_by(org_id=actor.org_id)
            .order_by(ReviewStandard.version.desc()).all())
    default = standards.default()
    return {"versions": [_payload(r) for r in rows],
            "default": {"name": default.name, "body_hash": standards.body_hash(default),
                        "source_yaml": standards.DEFAULT_YAML, "in_force": not any(r.is_active for r in rows)}}


class StandardIn(BaseModel):
    yaml: str = Field(min_length=1, max_length=MAX_YAML_BYTES)
    # Optimistic concurrency: the active version the editor started from (0: none was active).
    # Two admins editing at once cannot silently overwrite each other's change.
    expected_active_version: int | None = Field(default=None, ge=0)


class ActivateIn(BaseModel):
    expected_active_version: int | None = Field(default=None, ge=0)


def _check_expected(db: Session, org_id: str, expected: int | None) -> ReviewStandard | None:
    current = db.query(ReviewStandard).filter_by(org_id=org_id, is_active=True).one_or_none()
    if expected is not None and expected != (current.version if current else 0):
        raise HTTPException(409, f"the active standard changed to version {current.version if current else 0} "
                                 f"while you were editing version {expected}; reload and reapply your change")
    return current


def _parse_or_422(text: str) -> standards.Standard:
    try:
        return standards.parse(text, CONTENT)
    except standards.StandardError as exc:
        raise HTTPException(422, {"problems": exc.problems}) from exc


@router.post("/standards", status_code=201)
def publish_standard(body: StandardIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor, "publish a review standard")
    std = _parse_or_422(body.yaml)
    previous = _check_expected(db, actor.org_id, body.expected_active_version)
    version = (db.query(func.max(ReviewStandard.version)).filter_by(org_id=actor.org_id).scalar() or 0) + 1
    if previous is not None:
        previous.is_active = False
        db.flush()  # the one-active index must see the old version retired first
    row = ReviewStandard(org_id=actor.org_id, name=std.name, version=version, body=standards.body(std),
                         source_yaml=body.yaml, body_hash=standards.body_hash(std), is_active=True,
                         created_by=actor.label())
    db.add(row)
    db.flush()
    audit_log.record(db, actor=actor.label(), action="REVIEW_STANDARD_PUBLISHED", entity_type="review_standard",
                     entity=row.id, org_id=actor.org_id, request_id=actor.request_id,
                     detail={"name": row.name, "version": version, "body_hash": row.body_hash,
                             "rules": [r.id for r in std.rules],
                             "previous_version": previous.version if previous else None})
    db.commit()
    return _payload(row)


@router.post("/standards/{standard_id}/activate")
def activate_standard(standard_id: str, body: ActivateIn | None = None, actor: Actor = Depends(current_actor),
                      db: Session = Depends(get_session)):
    _admin(actor, "activate a review standard")
    row = db.get(ReviewStandard, standard_id)
    if row is None or row.org_id != actor.org_id:
        raise HTTPException(404)
    previous = _check_expected(db, actor.org_id, body.expected_active_version if body else None)
    if previous is not None and previous.id != row.id:
        previous.is_active = False
        db.flush()  # retire the old version before the one-active index sees the new one
    row.is_active = True
    audit_log.record(db, actor=actor.label(), action="REVIEW_STANDARD_ACTIVATED", entity_type="review_standard",
                     entity=row.id, org_id=actor.org_id, request_id=actor.request_id,
                     detail={"version": row.version, "body_hash": row.body_hash,
                             "previous_version": previous.version if previous else None})
    db.commit()
    return _payload(row)


@router.get("/packs")
def list_packs(actor: Actor = Depends(current_actor)):
    """Built-in policy packs to start a standard from. Platform content, the same for everyone."""
    return standards.packs()


class TryIn(BaseModel):
    diff: str = Field(min_length=1, max_length=MAX_DIFF_BYTES)
    yaml: str | None = Field(default=None, max_length=MAX_YAML_BYTES)


@router.post("/standards/test")
def try_standard(body: TryIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Run a standard (the posted YAML, else the one in force) over a pasted diff. Stores
    nothing and records nothing: the diff is code, and this is only an authoring aid."""
    if not actor.can_write:
        raise deny_read_only(actor, "try a review standard")
    if body.yaml is not None:
        std = _parse_or_422(body.yaml)
        digest = standards.body_hash(std)
    else:
        std, digest, _ = active_standard(db, actor.org_id)
    files = diffs.parse(body.diff)
    return {"standard": {"name": std.name, "body_hash": digest}, "files": len(files),
            **engine.review(std, files).as_dict()}
