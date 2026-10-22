"""Human review gate for drafted pack requirements (ADR-029 section 6).

    python -m tools.review_drafts eu-ai-act

Shows each pending draft in drafts/<framework>.yaml next to its source provision. The
reviewer accepts, edits or rejects it. Only an accepted draft reaches app/content/<pack>.yaml,
with its mappings re-marked source: EXPERT (a person has now vouched for them) and a
source_ref naming the exact provision and its sha256. A "not documentable" draft is either
confirmed, which records the omission in the pack header so it is never silently dropped, or
overridden by writing the requirement by hand in the editor.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path

import yaml

from app.content.load import CONTENT_DIR, Requirement
from tools.ingest_source import DRAFTS, FRAMEWORKS, SOURCES, read_provisions

LEFT_OUT = "# Left out (reviewed as not documentable, ADR-016 admission test):"


def _dump(obj) -> str:
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=100)


def _new_pack(framework: str) -> str:
    cfg = FRAMEWORKS[framework]
    return (f"# {cfg['title']}\n#\n# Source: {cfg['url']}\n# Licence: {cfg['licence']}\n"
            f"# Clauses are drafted from sources/{framework}/provisions.jsonl and accepted one by one\n"
            f"# through tools/review_drafts.py; each carries a source_ref to its exact provision.\n#\n"
            f"{LEFT_OUT}\n\n"
            f"framework:\n  code: {cfg['code']}\n  version: \"{cfg['version']}\"\n\nrequirements:\n")


def finalise(entry: dict, requirement: dict) -> dict:
    """The accepted form of a draft: mappings vouched for by a person, linked to its source."""
    req = dict(requirement)
    req["mappings"] = [{**m, "source": "EXPERT"} for m in req["mappings"]]
    req["source_ref"] = {"provision": entry["provision"], "sha256": entry["sha256"]}
    Requirement.model_validate(req)  # raises on anything that would not load
    return req


def append_requirement(pack: Path, framework: str, req: dict) -> None:
    """Appended as text, not re-dumped, so the pack's hand-written comments survive."""
    text = pack.read_text(encoding="utf-8") if pack.exists() else _new_pack(framework)
    existing = yaml.safe_load(text) or {}
    if any(r["clause"] == req["clause"] for r in existing.get("requirements") or []):
        raise ValueError(f"{req['clause']} is already in {pack.name}")
    block = textwrap.indent(_dump([req]), "  ")
    pack.write_text(text.rstrip("\n") + "\n\n" + block, encoding="utf-8", newline="\n")


def sync_omissions(pack: Path, doc: dict) -> None:
    """Write every confirmed omission into the pack header. A pack with no requirements yet
    doesn't exist (the loader would load an empty framework), so omissions confirmed before
    the first accept wait in the drafts file and land here with it."""
    if not pack.exists():
        return
    text = pack.read_text(encoding="utf-8")
    for entry in doc["drafts"]:
        line = f"#   {entry['ref']}: {entry.get('reason', '').strip()}"
        if entry["status"] == "omitted" and line not in text:
            text = text.replace(LEFT_OUT, f"{LEFT_OUT}\n{line}", 1)
    pack.write_text(text, encoding="utf-8", newline="\n")


def _edit(req: dict) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(_dump(req))
        path = f.name
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
    subprocess.run([editor, path], check=False)
    edited = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    os.unlink(path)
    return edited


def _show(entry: dict, provision: dict) -> None:
    print("\n" + "=" * 100)
    print(f"{entry['ref']}  [{entry.get('verdict_basis')}]  {provision['url']}")
    print("-" * 40 + " source")
    print(textwrap.fill(provision["text"], 100))
    print("-" * 40 + " draft")
    if entry.get("verdict_basis") == "not documentable":
        print(f"NOT DOCUMENTABLE: {entry.get('reason')}")
    else:
        print(_dump(entry["requirement"]))
        if entry.get("new_artefact_types"):
            print(f"!! proposes new artefact type(s): {entry['new_artefact_types']}")


def review(framework: str, ask=input, drafts: Path = DRAFTS, content_dir: Path = CONTENT_DIR,
           sources: Path = SOURCES, edit=_edit) -> dict:
    path = drafts / f"{framework}.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    pack = content_dir / FRAMEWORKS[framework]["pack"]
    provisions = {p["id"]: p for p in read_provisions(framework, sources)}
    counts: dict[str, int] = {}
    for entry in doc["drafts"]:
        if entry["status"] != "pending":
            continue
        provision = provisions.get(entry["provision"])
        if provision is None or provision["sha256"] != entry["sha256"]:
            print(f"\n{entry['ref']}: source text changed since drafting; re-draft it. Skipped.")
            continue
        _show(entry, provision)
        documentable = entry.get("verdict_basis") == "documentable"
        options = "[a]ccept [e]dit [r]eject [s]kip [q]uit" if documentable \
            else "[c]onfirm omission [e]dit (write it anyway) [s]kip [q]uit"
        while True:
            choice = ask(f"{options} > ").strip().lower()[:1]
            try:
                if choice == "q":
                    path.write_text(_dump(doc), encoding="utf-8", newline="\n")
                    return counts
                if choice == "s":
                    break
                if choice == "r" and documentable:
                    entry["status"] = "rejected"
                elif choice == "c" and not documentable:
                    entry["status"] = "omitted"
                elif choice == "a" and documentable:
                    append_requirement(pack, framework, finalise(entry, entry["requirement"]))
                    entry["status"] = "accepted"
                elif choice == "e":
                    seed = entry.get("requirement") or {"clause": entry["ref"], "title": "", "text": provision["text"],
                                                        "evidence_requirements": [], "mappings": []}
                    req = edit(seed)
                    req["clause"] = entry["ref"]
                    append_requirement(pack, framework, finalise(entry, req))
                    entry.update(status="accepted", requirement=req, edited=True)
                else:
                    continue
            except (ValueError, KeyError, TypeError) as exc:
                print(f"not accepted: {str(exc).splitlines()[0]}")
                continue
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
            sync_omissions(pack, doc)
            path.write_text(_dump(doc), encoding="utf-8", newline="\n")
            break
    path.write_text(_dump(doc), encoding="utf-8", newline="\n")
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m tools.review_drafts")
    ap.add_argument("framework", choices=FRAMEWORKS)
    print(review(ap.parse_args(argv).framework))


if __name__ == "__main__":
    main()
