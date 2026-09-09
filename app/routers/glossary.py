"""GRC glossary — what the words on screen mean.

Reference data, not tenant data: every organisation sees the same entries, so
there is no org_id, no RLS and no table. It is served straight from the content
pack loaded at import time, exactly like the UCO and framework definitions.

Authentication is still required, for the same reason as every other route —
this is product surface, not a public marketing page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import Actor, current_actor
from app.content.load import Term
from app.content.load import load as load_content

router = APIRouter(prefix="/glossary", tags=["glossary"])
CONTENT = load_content()

MAX_LIMIT = 200


def _out(term: Term) -> dict:
    return {
        "term": term.term,
        "definition": " ".join(term.definition.split()),
        "note": " ".join(term.note.split()),
        "source": term.source,
        "source_url": term.source_url,
        "aliases": list(term.aliases),
        "tags": list(term.tags),
        "imported": term.imported,
    }


@router.get("")
def list_terms(q: str = "", tag: str = "", limit: int = 50,
               actor: Actor = Depends(current_actor)) -> list[dict]:
    """Search the glossary, or — with no query — list the curated vocabulary.

    The imported NIST corpus is reachable by searching, not by scrolling: it is
    ~3.9k reference entries against ~70 curated ones, so listing everything
    would bury the words this product actually uses.
    """
    return [
        _out(t)
        for t in CONTENT.find_terms(q, tag=tag, limit=max(1, min(limit, MAX_LIMIT)))
    ]


@router.get("/{name}")
def get_term(name: str, actor: Actor = Depends(current_actor)) -> dict:
    """Exact lookup by term or alias — what a tooltip asks for. Falls back to
    404 rather than a near match, so the caller never renders someone else's
    definition under the word the user actually clicked."""
    try:
        return _out(CONTENT.term(name))
    except KeyError:
        raise HTTPException(404, f"unknown term '{name}'") from None
