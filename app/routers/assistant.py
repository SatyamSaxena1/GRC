"""Ask the workspace: a chat assistant over the caller's own GRC data.

The model gets read-only tools, and each one calls the same route function the UI
calls, with the caller's own Actor. So an answer can only use what that person could
already open on screen (tenant, role and control-assignment scoping all apply), and
nothing here can upload, edit, close a gap or move a verdict. Verdicts come from the
rules engine; the assistant reads and explains them, it never decides one (ADR-004).

Every question is written to the audit chain (ASSISTANT_ASKED) with the tools it used:
an AI answer about compliance is itself evidence of how the system was used.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor
from app.db import get_session

logger = logging.getLogger("app.assistant")
router = APIRouter(prefix="/assistant", tags=["assistant"])

MAX_TOOL_CHARS = 6000  # per tool result: keeps a small local model's context usable
MAX_HISTORY = 6

SYSTEM_PROMPT = """You are the assistant inside a GRC (governance, risk and compliance) workspace.
You answer questions about THIS organisation's evidence, verdicts, gaps, tasks and frameworks,
using the tools. Rules you must follow:
- Get facts from the tools. Never invent evidence, verdicts, clause text or numbers.
- Verdicts (PASS, PARTIAL, FAIL) were decided by fixed rules, not by you. Report them exactly as
  the tools return them. Never say something passes, fails or is compliant unless a tool says so,
  and never suggest a verdict should be different.
- Quote the source sentence when you rely on an extracted fact, and name the clause (for example
  "ISO-27001 A.5.15") and the evidence file you mean.
- You cannot change anything. If asked to upload, edit, approve, close or delete, explain where in
  the app the person can do it themselves.
- If the tools don't hold the answer, say so plainly.
- Answer in plain, short sentences. No markdown tables; short bullet lists are fine."""


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []}}}


TOOLS = [
    _fn("list_evidence", "List the organisation's current evidence files: id, file name, type, status, version.",
        {"artefact_type": {"type": "string", "description": "optional filter, e.g. POLICY, AI_POLICY"}}),
    _fn("get_evidence", "One evidence file: its verdict per framework clause with gaps, and every fact "
        "extracted from it with the quoted source sentence.",
        {"evidence_id": {"type": "string"}}, ["evidence_id"]),
    _fn("list_gaps", "Gaps (unmet requirements) with framework, clause, what is missing and the evidence.",
        {"status": {"type": "string", "description": "OPEN (default), RESOLVED, or ALL"}}),
    _fn("list_tasks", "Remediation tasks with owner, priority, due date and status.",
        {"status": {"type": "string", "description": "optional, e.g. OPEN"}}),
    _fn("get_clause_text", "The official title and text of one framework clause.",
        {"framework": {"type": "string", "description": "e.g. ISO-27001, NIST-AI-RMF"},
         "clause": {"type": "string", "description": "e.g. A.5.15, GOVERN 1.2"}}, ["framework", "clause"]),
    _fn("search_glossary", "Look up GRC terms and acronyms in the glossary.",
        {"query": {"type": "string"}}, ["query"]),
]


def _trim(value) -> dict:
    text = json.dumps(value, default=str)
    if len(text) <= MAX_TOOL_CHARS:
        return {"result": value}
    return {"result_truncated": text[:MAX_TOOL_CHARS], "note": "truncated; ask about one item at a time"}


def run_tool(name: str, args: dict, actor: Actor, db: Session) -> dict:
    """Each tool is an existing read-only route function, called as the asking user."""
    from app.routers import controls, evidence, glossary

    try:
        if name == "list_evidence":
            rows = evidence.list_evidence(artefact_type=args.get("artefact_type") or None,
                                          lifecycle_status="CURRENT", actor=actor, db=db)
            keep = ("id", "original_filename", "artefact_type", "status", "version")
            return _trim([{k: r.get(k) for k in keep} for r in rows])
        if name == "get_evidence":
            eid = str(args.get("evidence_id", ""))
            links = evidence.evidence_evaluations(eid, actor=actor, db=db)
            facts = evidence.evidence_attributes(eid, actor=actor, db=db)
            return _trim({
                "verdicts": [{"framework": l["framework"], "clause": l["clause"], "verdict": l["verdict"],
                              "locked_by_auditor": l.get("locked"),
                              "gaps": [g.get("message") or g.get("attribute") for g in l.get("gaps", [])]}
                             for l in links],
                "facts": [{"name": f["name"], "value": f["value"],
                           "quote": (f.get("sources") or [{}])[0].get("quote")} for f in facts],
            })
        if name == "list_gaps":
            status = (args.get("status") or "OPEN").upper()
            rows = controls.list_gaps(status=None if status == "ALL" else status, actor=actor, db=db)
            keep = ("framework", "clause", "attribute", "kind", "detail", "required_action", "actual_value",
                    "required_value", "status", "evidence_id")
            return _trim([{k: r.get(k) for k in keep if k in r} for r in rows])
        if name == "list_tasks":
            rows = controls.list_tasks(status=args.get("status") or None, priority=None, owner_user_id=None,
                                       q=None, actor=actor, db=db)
            keep = ("title", "status", "priority", "due_at", "owner_email", "framework", "clause", "required_action")
            return _trim([{k: r.get(k) for k in keep if k in r} for r in rows])
        if name == "get_clause_text":
            title, text = controls._requirement_text(str(args.get("framework", "")), str(args.get("clause", "")))
            return {"title": title, "text": text} if (title or text) else {"error": "no such clause"}
        if name == "search_glossary":
            rows = glossary.list_terms(q=str(args.get("query", "")), tag="", limit=5, actor=actor)
            return _trim([{k: r.get(k) for k in ("term", "definition", "source")} for r in rows])
    except HTTPException as exc:
        return {"error": str(exc.detail or exc.status_code)}
    return {"error": f"unknown tool {name}"}


class Turn(BaseModel):
    role: str
    content: str = Field(max_length=4000)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    page: str = Field(default="", max_length=200)          # route the person is on, e.g. /evidence/<id>
    history: list[Turn] = Field(default_factory=list)


def _prompt(body: AskIn) -> str:
    lines = []
    for t in body.history[-MAX_HISTORY:]:
        who = "Person" if t.role == "user" else "Assistant"
        lines.append(f"{who}: {t.content}")
    context = f"The person is looking at the page {body.page}.\n" if body.page else ""
    earlier = ("Earlier in this conversation:\n" + "\n".join(lines) + "\n\n") if lines else ""
    return f"{context}{earlier}Question: {body.question}"


@router.get("/status")
def assistant_status(actor: Actor = Depends(current_actor)):
    from app.ingest import _tool_gateway

    gateway = _tool_gateway()
    return {"available": gateway.available(), "model": gateway.model}


@router.post("/ask")
def ask(body: AskIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Answer one question with read-only tools. A model call, hence POST (same as draft-remediation)."""
    from app.ingest import _tool_gateway

    if not actor.org_id:
        raise HTTPException(400, "no organisation selected")
    gateway = _tool_gateway()
    if not gateway.available():
        raise HTTPException(503, "the assistant's model is offline")

    used: list[str] = []

    def executor(name: str, args: dict) -> dict:
        used.append(name)
        return run_tool(name, args, actor, db)

    answer = gateway.complete_with_tools(SYSTEM_PROMPT, _prompt(body), TOOLS, executor, max_rounds=5)
    answer = (answer or "").strip() or "I couldn't produce an answer this time. Please try rephrasing."
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="ASSISTANT_ASKED",
                     entity_type="assistant", entity=gateway.model, org_id=actor.org_id,
                     detail={"question": body.question, "page": body.page, "tools": used,
                             "model": gateway.model, "answer_chars": len(answer)})
    db.commit()
    return {"answer": answer, "tools": used, "model": gateway.model}
