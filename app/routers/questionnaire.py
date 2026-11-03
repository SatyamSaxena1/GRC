"""Security questionnaire answers (ADR-040).

A customer sends questions ("Do you enforce MFA?"). Each is matched to the controls in this workspace by
words, and the answer's status (YES, PARTIAL, NO, NOT_EVIDENCED) is decided from those controls' verdicts
by fixed rules. A model, when one is online, only words the answer from the matched controls; a wording
that contradicts the status is discarded for the rules' own sentence. The model never decides a status,
and with no model the page still answers (ADR-004).

One question per request: the page fills answers in as they arrive, and a slow model cannot time out a
whole questionnaire.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor
from app.db import get_session
from app.routers import analytics as analytics_router

router = APIRouter(prefix="/questionnaire", tags=["questionnaire"])

STOP = set("""a an the and or of to in on for with by is are be do does did we you your our us it its this that
these those any all as at from how what when where which who whom why can could should would will shall have
has had not no if than then there their they them i my me about into over under per via also such other each
every both either neither using use used within without between through during before after again further
once only own same so too very just""".split())

# Words customers use that the packs word differently. Each maps to terms found in control titles and text.
SYNONYMS = {
    "mfa": ["multi-factor", "authentication"], "2fa": ["multi-factor", "authentication"],
    "multifactor": ["multi-factor", "authentication"], "login": ["authentication"], "sso": ["authentication"],
    "encrypt": ["encryption", "cryptography"], "encrypted": ["encryption", "cryptography"],
    "log": ["logging", "logs"], "audit": ["logging", "logs"], "monitor": ["logging", "monitoring"],
    "leaver": ["termination", "revoked"], "offboard": ["termination", "revoked"], "offboarding": ["termination", "revoked"],
    "terminated": ["termination", "revoked"], "joiner": ["access"], "deprovision": ["termination", "revoked"],
    "review": ["review", "approval"], "pull": ["change", "approval"], "merge": ["change", "approval"],
    "deploy": ["change"], "deployment": ["change"], "code": ["change"], "commit": ["change"],
    "password": ["password", "authentication"], "passwords": ["password", "authentication"],
    "incident": ["breach", "incident"], "breach": ["breach", "incident"],
    "patch": ["vulnerability"], "pentest": ["vulnerability"], "vulnerabilities": ["vulnerability"],
    "leave": ["terminated", "revoked"], "leaves": ["terminated", "revoked"], "leavers": ["terminated", "revoked"],
    "backup": ["backup"], "backups": ["backup"], "privileged": ["privileged", "administrative"],
    "admin": ["privileged", "administrative"], "retention": ["retained", "retention"],
}


# Words that appear in nearly every control: matching on them pulls in unrelated controls and lowers a
# status for the wrong reason ("access" alone once dragged an access-revocation answer to PARTIAL).
GENERIC = {"access", "system", "information", "security", "activity", "control", "organisation", "user",
           "service", "process", "requirement", "implemented", "ensure"}


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            word = word[: -len(suffix)]
            break
    return word[:-1] if len(word) > 4 and word.endswith("e") else word  # revoke / revoked meet at "revok"


def tokens(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9][a-z0-9\-]+", text.lower()) if w not in STOP and len(w) > 2}


def expand(question: str) -> set[str]:
    base = tokens(question)
    extra = {t for w in re.findall(r"[a-z0-9]+", question.lower()) for t in SYNONYMS.get(w, [])}
    return (base | {_stem(t) for t in extra}) - {_stem(g) for g in GENERIC}


def match(question: str, controls: list[dict], limit: int = 3) -> list[dict]:
    """The controls whose own wording best overlaps the question. At least two shared words, or one that
    is in the control's title: a single stray word in a long clause is not a match."""
    wanted, scored = expand(question), []
    for c in controls:
        title, body = tokens(c.get("title") or ""), tokens(f"{c.get('text') or ''} {c['clause']}")
        in_title, in_body = wanted & title, wanted & body
        score = len(in_title) * 2 + len(in_body - in_title)
        if len(in_title) >= 1 or len(in_title | in_body) >= 2:
            scored.append((score, c))
    scored.sort(key=lambda s: (-s[0], s[1]["framework"], s[1]["clause"]))
    if not scored:
        return []
    cutoff = scored[0][0] * 0.6  # a control far less relevant than the best one must not change the status
    return [c for score, c in scored if score >= cutoff][:limit]


def status_of(verdicts: list[str]) -> str:
    """From the matched controls' verdicts alone."""
    if not verdicts:
        return "NOT_EVIDENCED"
    if "FAIL" in verdicts:
        return "NO"
    if all(v == "PASS" for v in verdicts):
        return "YES"
    if any(v in ("PASS", "PARTIAL") for v in verdicts):
        return "PARTIAL"
    return "NOT_EVIDENCED"


LEAD = {"YES": "Yes.", "PARTIAL": "Partly.", "NO": "Not currently.", "NOT_EVIDENCED": "Not yet evidenced."}
CONTRADICTS = {"NO": ("yes",), "NOT_EVIDENCED": ("yes", "partly"), "PARTIAL": ("yes",), "YES": ("no,", "not ")}


def rules_wording(status: str, cites: list[dict]) -> str:
    if not cites:
        return f"{LEAD[status]} There is no evidence in the workspace that addresses this question yet."
    named = ", ".join(f"{c['framework']} {c['clause']}" for c in cites)
    reviewed = " An auditor has reviewed and locked at least one." if any(c["reviewed_by_auditor"] for c in cites) else ""
    return f"{LEAD[status]} Addressed by {named}.{reviewed}"


SYSTEM = """You help answer a customer's security questionnaire from facts about the organisation's controls.
Write at most two plain sentences. Begin with the status words you are given. Use only the controls listed;
do not add claims, tools, numbers or dates, and do not mention verdict codes. Reply as JSON: {"answer": "..."}."""


def model_wording(gateway, question: str, status: str, cites: list[dict]) -> str | None:
    facts = "\n".join(f"- {c['framework']} {c['clause']} ({c['title']}): {c['verdict']}"
                      f"{', reviewed by an auditor' if c['reviewed_by_auditor'] else ''}" for c in cites) or "- none"
    try:
        raw = gateway.complete_json(SYSTEM, f"Question: {question}\nStatus: {LEAD[status]}\nControls:\n{facts}")
        text = str(json.loads(raw).get("answer", "")).strip()
    except Exception:  # an unreachable or confused model must never fail the answer
        return None
    low = text.lower()
    if not text or len(text) > 600 or any(low.startswith(w) for w in CONTRADICTS[status]):
        return None
    return text


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@router.post("/answer")
def answer(body: QuestionIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    if not actor.org_id:
        raise HTTPException(400, "no organisation selected")
    from app.ingest import _gateway

    controls = analytics_router.control_details(actor, db)
    matched = match(body.question, controls)
    cites = [{"control_id": c["id"], "framework": c["framework"], "clause": c["clause"], "title": c["title"],
              "verdict": analytics_router.best_verdict(c["links"]), "reviewed_by_auditor": bool(c["locked"])}
             for c in matched]
    status = status_of([c["verdict"] for c in cites])

    # The extraction gateway, not the tool-calling one: this is a plain text-in, JSON-out job, and LM Studio
    # rejects the tool gateway's json_object mode (a 400 that the fallback hid until a live check).
    gateway, wording = _gateway(), None
    if cites and gateway.available():
        wording = model_wording(gateway, body.question, status, cites)
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="QUESTIONNAIRE_ANSWERED",
                     entity_type="questionnaire", entity=actor.org_id, org_id=actor.org_id,
                     detail={"status": status, "controls": len(cites), "wording": "model" if wording else "rules"})
    db.commit()
    return {"question": body.question, "status": status,
            "answer": wording or rules_wording(status, cites),
            "wording": "model" if wording else "rules", "controls": cites}
