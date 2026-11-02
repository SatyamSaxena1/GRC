"""Turn the actor labels the audit trail stores into something a person can read.

Audit events keep `Actor.label()` strings (`user:<id>`, `auditor:<engagement>/user:<id>`, `org:<id>`,
`firm:<id>`) plus the literals the operator and the cron jobs write. The strings are the record and
stay as they are; this only adds a display name beside them. Unknown shapes come back unchanged, so a
label this module does not recognise is shown raw rather than guessed at.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.db import identity_lookup
from app.models import AuditFirm, Engagement, Organization, User

_LITERALS = {"admin": "Operator", "system": "System"}


def _split(label: str) -> tuple[str, str | None, str | None]:
    """(kind, engagement_or_subject_id, user_id) for the shapes Actor.label() produces."""
    if label.startswith("auditor:"):
        engagement, _, rest = label.removeprefix("auditor:").partition("/user:")
        return "auditor", engagement, rest or None
    for kind in ("user", "org", "firm"):
        if label.startswith(kind + ":"):
            return kind, label.split(":", 1)[1], None
    return "other", None, None


def resolve_actors(db: Session, labels: Iterable[str]) -> dict[str, str]:
    """label -> display name, one batched lookup per table. Users are read across tenants on
    purpose: a firm's auditor is not in the auditee's tenant, but their name belongs on the trail."""
    labels = {l for l in labels if l}
    parsed = {l: _split(l) for l in labels}
    user_ids = {u for l, (k, a, u) in parsed.items() if k == "auditor" and u} | \
               {a for l, (k, a, u) in parsed.items() if k == "user" and a}
    engagement_ids = {a for l, (k, a, _) in parsed.items() if k == "auditor" and a}
    org_ids = {a for l, (k, a, _) in parsed.items() if k == "org" and a}
    firm_ids = {a for l, (k, a, _) in parsed.items() if k == "firm" and a}

    with identity_lookup(db):
        emails = {u.id: u.email for u in db.query(User).filter(User.id.in_(user_ids))} if user_ids else {}
    engagements = ({e.id: e.audit_firm_id for e in db.query(Engagement).filter(Engagement.id.in_(engagement_ids))}
                   if engagement_ids else {})
    firm_ids |= set(engagements.values())
    firms = {f.id: f.name for f in db.query(AuditFirm).filter(AuditFirm.id.in_(firm_ids))} if firm_ids else {}
    orgs = {o.id: o.name for o in db.query(Organization).filter(Organization.id.in_(org_ids))} if org_ids else {}

    out: dict[str, str] = {}
    for label, (kind, subject, user_id) in parsed.items():
        if label in _LITERALS:
            out[label] = _LITERALS[label]
        elif label.startswith(("system:", "monitor:")):
            out[label] = "Scheduled monitor"
        elif kind == "user":
            out[label] = emails.get(subject, label)
        elif kind == "auditor":
            firm = firms.get(engagements.get(subject, ""), "")
            who = emails.get(user_id) if user_id else None
            out[label] = f"{who} (auditor{', ' + firm if firm else ''})" if who else f"Auditor{' · ' + firm if firm else ''}"
        elif kind == "org":
            out[label] = f"{orgs[subject]} (organisation)" if subject in orgs else label
        elif kind == "firm":
            out[label] = f"{firms[subject]} (firm)" if subject in firms else label
        else:
            out[label] = label
    return out
