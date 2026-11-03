"""Advisory pre-review of drafted pack requirements (ADR-035).

    python -m tools.review_drafts eu-ai-act --assist

Beside each draft the reviewer sees three things, in this order of trust:

1. Mechanical checks (no model): is the source text unchanged since drafting, is the quoted text
   exactly the law's, is a number in a condition written anywhere in the provision, does the draft
   invent an artefact type, is the clause already in the pack.
2. Related provisions, fetched BY ID (no embeddings, no similarity search): the provisions the
   text cites ("Article 6(1)"), and the paragraphs on either side. A lookup cannot retrieve the
   wrong passage; it can only miss one, and the reviewer is told what was fetched.
3. A sceptical critique from the model, told to argue against the draft using only the text it is
   given. It is advice, shown labelled as such. Nothing here changes a draft's status, text or
   mappings, and no code path accepts a draft because of what the critique says (ADR-004: a model
   never decides; ADR-026: a model's review is evidence, not approval).

The critique is stored on the draft entry (`assist`) so it is not recomputed or lost between
sessions. A different model from the drafter gives a more independent critique, because a model
agrees with its own drafts: set REVIEW_ASSIST_MODEL.
"""

from __future__ import annotations

import hashlib
import json
import re
import textwrap

import yaml

CRITIC = """You are a sceptical reviewer of ONE drafted compliance requirement. You are shown the
provision of the law it was drafted from, a few related provisions fetched by id, and the draft.
You do NOT approve or reject anything and you do not judge any organisation; a person decides.
Your job is to argue against the draft: find where it says more or less than the law does.

Use ONLY the text you are given. If the given text does not settle a point, say "cannot tell"
rather than guessing or recalling the law from memory. Cite provisions by their ref (for example
"Art. 26(6)").

The RELATED PROVISIONS are context only. Each provision is drafted on its own, so NEVER fault the
draft for not covering what a related provision says. Use them only to see whether they limit,
extend or make an exception to THE PROVISION being drafted. Every concern must be about what THE
PROVISION itself says. If the draft is faithful, say "yes" and leave the lists empty.

Look for: a "must" the text does not contain; an exception, scope limit or cross-reference that the
draft ignores; a condition or number the text does not state; an attribute no document could state;
a requirement drafted as documentable when whether it is met depends on what actually happened.

Answer with JSON only:
{"faithful": "yes" | "partly" | "no" | "cannot tell",
 "concerns": ["<one sentence each, citing the provision>"],
 "missing_context": ["<a provision or fact that would change the answer>"],
 "suggested_changes": ["<a concrete change to the draft>"]}
Keep each list to at most five short items; use [] when there is nothing to say."""

FAITHFUL = ("yes", "partly", "no", "cannot tell")
MAX_RELATED, MAX_CHARS = 4, 700
_CITES = re.compile(r"Article (\d+)(?:\((\d+)\))?")


# ------------------------------------------------------------------ retrieval by id

def _article_para(pid: str) -> tuple[str, str, int | None]:
    framework, rest = pid.split(":", 1)
    article, _, para = rest.partition(".")
    return framework, article, int(para) if para.isdigit() else None


def related(provisions: dict[str, dict], provision: dict, limit: int = MAX_RELATED) -> list[dict]:
    """The provisions the reviewer should read beside this one, by id: everything it cites, then
    the paragraphs on either side. `provisions` is keyed by provision id."""
    framework, article, para = _article_para(provision["id"])
    found: list[dict] = []
    seen = {provision["id"]}

    def add(pid: str, why: str) -> None:
        row = provisions.get(pid)
        if row is not None and pid not in seen and len(found) < limit:
            seen.add(pid)
            found.append({"ref": row["ref"], "why": why, "text": row["text"][:MAX_CHARS]})

    for m in _CITES.finditer(provision["text"]):
        n, p = m.group(1), m.group(2)
        add(f"{framework}:art{n}.{p}" if p else f"{framework}:art{n}", "cited by the provision")
        if p:
            add(f"{framework}:art{n}", "the article it cites")
    if para is not None:
        add(f"{framework}:{article}.{para - 1}", "the paragraph before")
        add(f"{framework}:{article}.{para + 1}", "the paragraph after")
    return found


# ------------------------------------------------------------------ mechanical checks

def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def mechanical_checks(entry: dict, provision: dict, cfg: dict, pack_clauses: set[str]) -> list[dict]:
    """No model. Each item is {"level": "ok" | "warn", "what": str}."""
    out: list[dict] = []

    def say(ok: bool, good: str, bad: str) -> None:
        out.append({"level": "ok" if ok else "warn", "what": good if ok else bad})

    say(provision["sha256"] == entry.get("sha256"), "source text unchanged since drafting",
        "the source text changed since this was drafted; re-draft it")
    if entry.get("verdict_basis") == "not documentable":
        say(bool(str(entry.get("reason", "")).strip()), "an omission reason is given",
            "marked not documentable with no reason")
        return out
    req = entry.get("requirement") or {}
    if cfg.get("quote_allowed"):
        say(req.get("text") == provision["text"], "quotes the law word for word",
            "the requirement text is not the law's own words")
    if entry.get("new_artefact_types"):
        out.append({"level": "warn", "what": f"proposes new artefact type(s) {entry['new_artefact_types']}: "
                                              "check they are really needed"})
    in_text = _numbers(provision["text"])
    for m in req.get("mappings", []):
        for c in m.get("delta_conditions", []):
            v = c.get("value")
            if isinstance(v, (int, float)) and not isinstance(v, bool) and str(v) not in in_text:
                out.append({"level": "warn", "what": f"{c['attribute']} {c['operator']} {v}: the number {v} is not "
                                                     "written in the provision (derived from words, or invented?)"})
    say(provision["ref"] not in pack_clauses, "clause not yet in the pack",
        f"{provision['ref']} is already in the pack")
    return out


# ------------------------------------------------------------------ the critique

def prompt_sha256() -> str:
    return hashlib.sha256(CRITIC.encode("utf-8")).hexdigest()


def _unfence(raw: str) -> str:
    s = raw.strip()
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", s) if s.startswith("```") else s


_FILLER = {"", "none", "n/a", "cannot tell", "nothing", "no concerns", "no further concerns"}


def _flat(value) -> list:
    """Models sometimes nest a list inside the list, or send a bare string."""
    if isinstance(value, (list, tuple)):
        return [y for x in value for y in _flat(x)]
    return [value]


def _items(value) -> list[str]:
    """At most five real items: nested lists flattened, filler such as "cannot tell" dropped."""
    out = [str(x).strip()[:400] for x in _flat(value) if x is not None]
    return [x for x in out if x.lower().rstrip(".") not in _FILLER][:5]


def parse_critique(raw: str) -> dict:
    """The model's answer as the reviewer will see it. Anything unusable is an error entry, never
    a guess: a critique that cannot be read is shown as unavailable."""
    try:
        data = json.loads(_unfence(raw))
        faithful = str(data.get("faithful", "")).strip().lower()
        return {"faithful": faithful if faithful in FAITHFUL else "cannot tell",
                "concerns": _items(data.get("concerns")), "missing_context": _items(data.get("missing_context")),
                "suggested_changes": _items(data.get("suggested_changes"))}
    except (ValueError, AttributeError, TypeError):
        return {"error": "the model's answer could not be read as a critique"}


def _draft_text(entry: dict) -> str:
    if entry.get("verdict_basis") == "not documentable":
        return f"NOT DOCUMENTABLE. Reason given: {entry.get('reason', '')}"
    return yaml.safe_dump(entry.get("requirement"), sort_keys=False, allow_unicode=True, width=100)


NEIGHBOUR_TAG = "(about a neighbouring provision, not this one) "


def tag_neighbour_concerns(parsed: dict, ref: str, rel: list[dict]) -> dict:
    """A small model often faults a draft for what the provision NEXT to it says, despite being told
    not to. Whatever the model says, a concern that cites a related provision and never the one being
    reviewed is tagged, so the reviewer sees at a glance that it is not about this provision."""
    if "error" in parsed:
        return parsed
    others = [r["ref"] for r in rel if r["ref"] != ref]

    def tag(text: str) -> str:
        return NEIGHBOUR_TAG + text if ref not in text and any(o in text for o in others) else text

    return {**parsed, **{k: [tag(t) for t in parsed[k]] for k in ("concerns", "missing_context", "suggested_changes")}}


def critique(gateway, entry: dict, provision: dict, rel: list[dict], title: str) -> dict:
    user = (f"PROVISION {provision['ref']} of {title}:\n{provision['text']}\n\n"
            + ("RELATED PROVISIONS (fetched by id):\n"
               + "\n".join(f"- {r['ref']} ({r['why']}): {r['text']}" for r in rel) + "\n\n" if rel else "")
            + f"DRAFT:\n{_draft_text(entry)}")
    try:
        return tag_neighbour_concerns(parse_critique(gateway.complete_json(CRITIC, user)), provision["ref"], rel)
    except Exception as exc:  # noqa: BLE001 - advice is optional; the review goes on without it
        return {"error": f"the model could not be reached: {type(exc).__name__}"}


def assist(entry: dict, provision: dict, provisions: dict[str, dict], cfg: dict, pack_clauses: set[str],
           gateway=None, force: bool = False) -> dict:
    """Everything the reviewer is shown beside one draft. Cached on the entry, keyed by the source
    hash and the critic prompt, so re-running a session does not re-ask the model."""
    model = getattr(gateway, "model", "") if gateway is not None else ""
    cached = entry.get("assist")
    if (not force and cached and cached.get("sha256") == provision["sha256"]
            and cached.get("prompt_sha256") == prompt_sha256() and cached.get("model", "") == model
            and (gateway is None or cached.get("critique") is not None)):
        cached["checks"] = mechanical_checks(entry, provision, cfg, pack_clauses)  # cheap: always current
        return cached
    rel = related(provisions, provision)
    result = {"sha256": provision["sha256"], "prompt_sha256": prompt_sha256(), "model": model,
              "checks": mechanical_checks(entry, provision, cfg, pack_clauses),
              "related": [r["ref"] for r in rel], "critique": None}
    if gateway is not None:
        result["critique"] = critique(gateway, entry, provision, rel, cfg["title"])
    return result


def render(result: dict, drafter: str = "") -> str:
    """The reviewer's view. Labelled advisory, with the model named, so it is never mistaken for
    part of the draft."""
    lines = ["-" * 40 + " assist (advisory: nothing here accepts or changes the draft)"]
    for c in result["checks"]:
        lines.append(f"  {'ok  ' if c['level'] == 'ok' else 'CHECK'} {c['what']}")
    if result.get("related"):
        lines.append(f"  related provisions read: {', '.join(result['related'])}")
    crit = result.get("critique")
    if crit is None:
        lines.append("  model critique: not requested")
    elif "error" in crit:
        lines.append(f"  model critique: unavailable ({crit['error']})")
    else:
        model = result.get("model") or "the model"
        same = f"  (same model as the drafter; less independent)" if drafter and drafter == result.get("model") else ""
        lines.append(f"  model critique by {model}: faithful to the text? {crit['faithful']}{same}")
        for label, key in (("concern", "concerns"), ("missing context", "missing_context"), ("suggested change", "suggested_changes")):
            for item in crit[key]:
                lines.append(textwrap.fill(f"{label}: {item}", 100, initial_indent="   - ", subsequent_indent="     "))
    return "\n".join(lines)
