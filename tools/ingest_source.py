"""Source text in, DRAFT pack requirements out (ADR-029 section 6).

    python -m tools.ingest_source parse eu-ai-act
    python -m tools.ingest_source draft eu-ai-act --articles 4 5 26 27

`parse` is deterministic, with no model: the same source bytes always give byte-identical
sources/<framework>/provisions.jsonl. `draft` asks the configured model gateway
(app/ai/provider.py, ADR-005) for one requirement per provision and writes the drafts to
drafts/<framework>.yaml. It never writes to app/content/; only tools/review_drafts.py does,
after a person accepts the draft. The model drafts rules; it never decides a verdict (ADR-004).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.content.load import Requirement, load

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
DRAFTS = ROOT / "drafts"

# One entry per ingested source. Only free-to-reuse texts belong here: ISO, PCI DSS and
# AICPA are copyrighted and are never fetched (tests/test_source_ingestion.py enforces it).
FRAMEWORKS = {
    "eu-ai-act": {
        "file": "32024R1689.xhtml",
        "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
        "code": "EU-AI-ACT",
        "version": "2024/1689",
        "pack": "eu-ai-act-2024.yaml",
        "title": "EU AI Act — Regulation (EU) 2024/1689",
        "licence": "© European Union, https://eur-lex.europa.eu/ — reuse authorised with "
                   "acknowledgement (Commission Decision 2011/833/EU)",
        # EU law may be quoted, so a pack clause carries the provision's own words.
        "quote_allowed": True,
    },
    "gdpr": {
        "file": "32016R0679.xhtml",
        "url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
        # code and version match the existing hand-written app/content/gdpr.yaml
        "code": "GDPR",
        "version": "2016/679",
        "pack": "gdpr.yaml",
        "title": "GDPR — Regulation (EU) 2016/679",
        "licence": "© European Union, https://eur-lex.europa.eu/ — reuse authorised with "
                   "acknowledgement (Commission Decision 2011/833/EU)",
        "quote_allowed": True,
    },
}

_X = "{http://www.w3.org/1999/xhtml}"
_ARTICLE = re.compile(r"^art_(\d+)$")
_PARAGRAPH = re.compile(r"^(\d{3})\.(\d{3})$")
_POINT = re.compile(r"^\(([a-z]{1,3})\)$")


# ------------------------------------------------------------------ parse

def _text(el: ET.Element) -> str:
    """All text under `el`, with non-breaking spaces and layout whitespace collapsed."""
    return re.sub(r"\s+", " ", "".join(el.itertext()).replace("\xa0", " ")).strip()


def _provision(framework: str, pid: str, ref: str, text: str, url: str) -> dict:
    return {"id": f"{framework}:{pid}", "framework": framework, "ref": ref, "text": text,
            "url": url, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def parse_eurlex(path: Path, framework: str, url: str) -> list[dict]:
    """Official Journal XHTML (EUR-Lex / Cellar) into article / paragraph / point provisions.

    Uses the document's own structure, never text layout: an article is
    div.eli-subdivision#art_N, a paragraph is its child div#NNN.MMM, and a point is a
    two-cell table row whose first cell reads "(a)". A paragraph's text includes its
    points, and each point is also emitted on its own so a clause can cite one.
    Annexes and recitals are not parsed yet."""
    root = ET.parse(path).getroot()
    out: list[dict] = []
    for art in root.iter(f"{_X}div"):
        m = _ARTICLE.match(art.get("id", ""))
        if not m:
            continue
        n = int(m.group(1))
        anchor = f"{url}#art_{n}"
        paragraphs = [d for d in art.findall(f"{_X}div") if _PARAGRAPH.match(d.get("id", ""))]
        if not paragraphs:
            body = [p for p in art.findall(f"{_X}p") if p.get("class") == "oj-normal"]
            out.append(_provision(framework, f"art{n}", f"Art. {n}", " ".join(_text(p) for p in body), anchor))
            continue
        for para in paragraphs:
            p = int(_PARAGRAPH.match(para.get("id")).group(2))
            out.append(_provision(framework, f"art{n}.{p}", f"Art. {n}({p})", _text(para), anchor))
            # Top-level points only (a nested (i) inside (h) stays in (h)'s text), with the
            # subparagraph they sit in: Art. 43(1) has two separate (a)/(b) lists.
            points, sub = [], 0
            for child in para:
                if child.tag == f"{_X}p":
                    sub += 1
                for row in child.findall(f"{_X}tbody/{_X}tr") if child.tag == f"{_X}table" else ():
                    cells = row.findall(f"{_X}td")
                    point = _POINT.match(_text(cells[0])) if len(cells) == 2 else None
                    if point:
                        points.append((sub, point.group(1), _text(cells[1])))
            letters = [letter for _, letter, _ in points]
            repeated = len(letters) != len(set(letters))
            for sub, letter, text in points:
                if repeated:
                    pid, ref = f"art{n}.{p}.s{sub}.{letter}", f"Art. {n}({p}) subpara {sub}, point ({letter})"
                else:
                    pid, ref = f"art{n}.{p}.{letter}", f"Art. {n}({p})({letter})"
                out.append(_provision(framework, pid, ref, text, anchor))
    return out


def provisions_path(framework: str) -> Path:
    return SOURCES / framework / "provisions.jsonl"


def parse(framework: str, sources: Path = SOURCES) -> Path:
    cfg = FRAMEWORKS[framework]
    rows = parse_eurlex(sources / framework / cfg["file"], framework, cfg["url"])
    out = sources / framework / "provisions.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return out


def read_provisions(framework: str, sources: Path = SOURCES) -> list[dict]:
    path = sources / framework / "provisions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ------------------------------------------------------------------ draft

SYSTEM = """You draft ONE compliance requirement for a GRC content pack from ONE provision of a law.
You do not judge any organisation; you write the rule a document will later be checked against.

Admission test (ADR-016): a clause is "documentable" only if a document can state the thing so
that its absence is a real finding (a policy either names who oversees the AI system or it does
not). If no document can settle the outcome (it depends on what actually happened, on technical
measurement, or the provision only defines terms, sets out exceptions, or addresses authorities
rather than the organisation), answer "not documentable" and give the reason. Never invent an
attribute just to make an outcome testable.

Rules for a documentable draft:
- evidence_requirements: use the EXISTING artefact types listed. Only if none fits, name a new
  one in new_artefact_types.
- required_attributes: snake_case facts a document would state, e.g. human_oversight_assigned.
- mappings: onto EXISTING UCO codes only, each with coverage FULL, PARTIAL or SUPPORTING and a
  confidence between 0 and 1.
- delta_conditions: ONLY when the text states a checkable fact or a number. Example: "keep logs
  for a period of at least six months" -> {"attribute": "ai_log_retention_days", "operator":
  ">=", "value": 183}. Operators: >=, <=, >, <, ==, !=, contains_all, one_of. A boolean fact
  the document must state is {"attribute": x, "operator": "==", "value": true}.
- guidance: one or two sentences in your own words telling an owner what to put in the document.

Answer with JSON only:
{"verdict_basis": "documentable" | "not documentable",
 "reason": "<one sentence>",
 "new_artefact_types": [],
 "requirement": null | {"title": "...", "guidance": "...",
   "evidence_requirements": [{"artefact_type": "...", "required_attributes": ["..."]}],
   "mappings": [{"uco": "...", "coverage": "FULL", "confidence": 0.8,
                 "delta_conditions": [{"attribute": "...", "operator": "==", "value": true}]}]}}"""


def _context(content) -> str:
    ucos = "\n".join(f"{u.code} [{u.domain}] {u.title}" for u in content.ucos)
    types = sorted({e.artefact_type for p in content.packs for r in p.requirements
                    for e in r.evidence_requirements})
    return f"EXISTING UCOs:\n{ucos}\n\nEXISTING artefact types: {', '.join(types)}"


def prompt_sha256(content) -> str:
    return hashlib.sha256((SYSTEM + _context(content)).encode("utf-8")).hexdigest()


def _unfence(raw: str) -> str:
    s = raw.strip()
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", s) if s.startswith("```") else s


def check_draft(raw: str, provision: dict, cfg: dict, content) -> dict:
    """One model answer into one draft entry. Anything that fails the pack schema, names a UCO
    that doesn't exist, or uses an artefact type it didn't declare as new is marked
    schema_rejected here, so a reviewer never sees a draft that couldn't load."""
    entry = {"provision": provision["id"], "ref": provision["ref"], "sha256": provision["sha256"],
             "status": "pending"}
    try:
        answer = json.loads(_unfence(raw))
        basis = answer["verdict_basis"]
        if basis not in ("documentable", "not documentable"):
            raise ValueError(f"verdict_basis {basis!r}")
        entry.update(verdict_basis=basis, reason=str(answer.get("reason", "")),
                     new_artefact_types=list(answer.get("new_artefact_types") or []))
        if basis == "not documentable":
            return entry
        req = dict(answer["requirement"])
        # The provision decides clause and text, not the model: the clause is the citation, and
        # where the licence allows, the text is the law's own words rather than a paraphrase.
        req["clause"] = provision["ref"]
        req["text"] = provision["text"] if cfg["quote_allowed"] else req.get("text", "")
        for m in req.get("mappings", []):
            m["source"] = "AI"
        req = Requirement.model_validate(req).model_dump(mode="json")
        known_ucos = {u.code for u in content.ucos}
        bad = [m["uco"] for m in req["mappings"] if m["uco"] not in known_ucos]
        if bad:
            raise ValueError(f"unknown UCO {bad}")
        if not req["mappings"] or not req["evidence_requirements"]:
            raise ValueError("a requirement needs at least one mapping and one evidence requirement")
        known_types = {e.artefact_type for p in content.packs for r in p.requirements
                       for e in r.evidence_requirements}
        undeclared = {e["artefact_type"] for e in req["evidence_requirements"]} - known_types \
            - set(entry["new_artefact_types"])
        if undeclared:
            raise ValueError(f"artefact type(s) {sorted(undeclared)} neither existing nor declared new")
        # A condition on an attribute no document is asked to state can never pass. Every
        # existing pack keeps this invariant; a draft that breaks it is a broken rule.
        stated = {a for e in req["evidence_requirements"] for a in e["required_attributes"]}
        orphans = sorted({c["attribute"] for m in req["mappings"] for c in m["delta_conditions"]} - stated)
        if orphans:
            raise ValueError(f"condition on {orphans}, which no evidence requirement asks the document to state")
        entry["requirement"] = req
    except ValidationError as exc:
        why = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        entry.update(status="schema_rejected", error=why[:300], raw=raw[:2000])
    except (ValueError, KeyError, TypeError) as exc:
        entry.update(status="schema_rejected", error=str(exc).splitlines()[0][:300], raw=raw[:2000])
    return entry


def select(provisions: list[dict], articles: list[int]) -> list[dict]:
    """Paragraph-level provisions of the chosen articles (or the article itself when it has no
    paragraphs). Points are drafted as part of their paragraph, not one by one."""
    wanted = {f"art{a}" for a in articles}
    return [p for p in provisions if p["id"].split(":")[1].split(".")[0] in wanted
            and p["id"].count(".") <= 1]


def draft(framework: str, articles: list[int], gateway=None, content=None,
          sources: Path = SOURCES, drafts: Path = DRAFTS) -> Path:
    cfg = FRAMEWORKS[framework]
    content = content or load()
    if gateway is None:
        from app.ai.provider import make_gateway
        gateway = make_gateway()
        if not gateway.available():
            sys.exit(f"model gateway {gateway.model!r} is not available; check LLM_PROVIDER / LLM_MODEL")
    out = drafts / f"{framework}.yaml"
    doc = yaml.safe_load(out.read_text(encoding="utf-8")) if out.exists() else {}
    done = {d["provision"] for d in doc.get("drafts", []) if d["status"] != "schema_rejected"}
    kept = [d for d in doc.get("drafts", []) if d["provision"] in done]
    context = _context(content)
    for provision in select(read_provisions(framework, sources), articles):
        if provision["id"] in done:
            continue
        user = f"{context}\n\nPROVISION {provision['ref']} of {cfg['title']}:\n{provision['text']}"
        try:
            raw = gateway.complete_json(SYSTEM, user)
        except RuntimeError as exc:
            raw = f"<gateway error: {exc}>"
        entry = check_draft(raw, provision, cfg, content)
        kept.append(entry)
        print(f"{entry['ref']:<14} {entry['status']:<16} {entry.get('verdict_basis', '')}", flush=True)
    order = {p["id"]: i for i, p in enumerate(read_provisions(framework, sources))}
    kept.sort(key=lambda d: order.get(d["provision"], 1 << 30))
    drafts.mkdir(exist_ok=True)
    header = {"framework": framework, "model": getattr(gateway, "model", ""),
              "prompt_sha256": prompt_sha256(content), "drafts": kept}
    out.write_text(yaml.safe_dump(header, sort_keys=False, allow_unicode=True, width=100),
                   encoding="utf-8", newline="\n")
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m tools.ingest_source")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("parse").add_argument("framework", choices=FRAMEWORKS)
    d = sub.add_parser("draft")
    d.add_argument("framework", choices=FRAMEWORKS)
    d.add_argument("--articles", type=int, nargs="+", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "parse":
        out = parse(args.framework)
        print(f"{out} ({sum(1 for _ in out.open(encoding='utf-8'))} provisions)")
    else:
        print(draft(args.framework, args.articles))


if __name__ == "__main__":
    main()
