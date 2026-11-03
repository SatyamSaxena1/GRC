"""Policy templates whose numbers come from the rules (ADR-038).

A template is a starting document. The figures it states (minimum password length, how often access is
reviewed, which access needs multi-factor authentication) are not typed here: each is the strictest value
any loaded framework requires, read from the packs, so a policy written from it meets every framework's
threshold and the template follows the packs when they change. Like the glossary this is reference data:
no tenant rows, no RLS. Approval and effective dates are left blank for the organisation to fill in.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app.auth import Actor, current_actor
from app.content.load import load as load_content

router = APIRouter(prefix="/templates", tags=["templates"])
CONTENT = load_content()


def conditions(attribute: str) -> list:
    """Every delta condition on this attribute, across all framework packs."""
    return [c for p in CONTENT.packs for r in p.requirements for m in r.mappings
            for c in m.delta_conditions if c.attribute == attribute]


def strictest(attribute: str) -> Any:
    """The one value that satisfies every framework's condition on this attribute."""
    conds = conditions(attribute)
    assert conds, f"no framework states a condition on {attribute}"
    ops = {c.operator for c in conds}
    if ops == {">="}:
        return max(c.value for c in conds)
    if ops == {"<="}:
        return min(c.value for c in conds)
    if ops == {"contains_all"}:
        return sorted({v for c in conds for v in c.value})
    if ops == {"=="} and len({str(c.value) for c in conds}) == 1:
        return conds[0].value
    raise ValueError(f"cannot combine conditions on {attribute}: {sorted(ops)}")


HEAD = """# {title}

| | |
|---|---|
| Organisation | [your organisation] |
| Approved by (role) | [for example, Chief Information Security Officer] |
| Approval date | [date] |
| Effective date | [date] |
| Next review | [date] |

"""


def _access_control() -> tuple[str, dict]:
    days, systems = strictest("access_review_frequency_days"), strictest("systems_covered")
    stated = {"access_review_frequency_days": days, "systems_covered": systems}
    body = HEAD.format(title="Access Control Policy") + f"""## Purpose
Access to information and systems is limited to people who need it to do their work, and is removed when
they no longer do.

## Scope
This policy covers the following systems: {", ".join(systems)}.

## Principles
- Access is granted on least privilege and need to know, and approved by the system owner.
- Every account belongs to one named person. Shared accounts are not permitted.
- Privileged access is granted separately from everyday access and is logged.

## Access reviews
Access rights are reviewed at least every {days} days. The reviewer records the date of the review, who
was reviewed, and every right that was removed. Reviews are retained as evidence.

## Joiners, movers and leavers
- Access is granted only after approval and removed when a person changes role.
- When employment ends, all access is revoked on the last working day.
- Human resources informs IT of every leaver on or before their last working day.

## Exceptions
Any exception is approved in writing by the policy owner, time-limited, and recorded.
"""
    return body, stated


def _password_and_mfa() -> tuple[str, dict]:
    length, mfa = strictest("password_min_length"), strictest("mfa_required_for")
    stated = {"password_min_length": length, "mfa_required_for": mfa}
    body = HEAD.format(title="Password and Authentication Policy") + f"""## Purpose
Credentials are strong enough that they cannot be found by guessing, and sensitive access needs a second
factor.

## Passwords
- Passwords are at least {length} characters long.
- Passwords are never shared, written down where others can read them, or reused across systems.
- Compromised or suspected passwords are changed immediately.

## Multi-factor authentication
Multi-factor authentication is required for: {" and ".join(mfa)}.
It is enabled on every account that can reach these, without exception for senior staff.

## Exceptions
Any exception is approved in writing by the policy owner, time-limited, and recorded.
"""
    return body, stated


def _encryption() -> tuple[str, dict]:
    stated = {"encryption_at_rest": strictest("encryption_at_rest"),
              "encryption_in_transit": strictest("encryption_in_transit")}
    assert stated == {"encryption_at_rest": True, "encryption_in_transit": True}
    body = HEAD.format(title="Encryption Policy") + """## Purpose
Sensitive data stays unreadable to anyone who is not entitled to it, whether it is stored or moving.

## Encryption at rest
Encryption at rest is required for databases, file storage, backups and laptops that hold sensitive data.

## Encryption in transit
Encryption in transit is required for all connections that carry sensitive data, inside and outside the
network.

## Keys
Keys are generated with approved algorithms, stored apart from the data they protect, rotated on a defined
schedule, and removed when no longer needed.

## Exceptions
Any exception is approved in writing by the policy owner, time-limited, and recorded.
"""
    return body, stated


TEMPLATES = {
    "access-control": ("Access Control Policy", "POLICY", _access_control),
    "password-and-mfa": ("Password and Authentication Policy", "POLICY", _password_and_mfa),
    "encryption": ("Encryption Policy", "ENCRYPTION_POLICY", _encryption),
}


def render(template_id: str) -> tuple[str, dict]:
    if template_id not in TEMPLATES:
        raise HTTPException(404, "unknown template")
    return TEMPLATES[template_id][2]()


@router.get("")
def list_templates(actor: Actor = Depends(current_actor)) -> list[dict]:
    return [{"id": tid, "title": title, "evidence_type": art, "states": render(tid)[1]}
            for tid, (title, art, _) in TEMPLATES.items()]


@router.get("/{template_id}", response_class=PlainTextResponse)
def get_template(template_id: str, actor: Actor = Depends(current_actor)) -> str:
    return render(template_id)[0]
