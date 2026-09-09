"""Import NIST's "The Language of Trustworthy AI" glossary into
app/content/glossary-ai.json.

    python -m scripts.import_ai_glossary "<path to the Glossary.csv>"

Unlike scripts/import_nist_glossary.py there is no stable bulk URL to pull, so
this takes the CSV exported from NIST's AI Resource Center
(https://airc.nist.gov/glossary/) as a local path. Run it when NIST publishes a
newer edition; the output is committed and nothing fetches at runtime.

PROVENANCE, which differs from the CSRC import in a way that matters: NIST wrote
the CSRC glossary, so that text is US Government work and public domain. This
file is a *compilation of quotations* — of its 447 terms only ~107 carry a
definition from a public-domain source, while the rest quote ISO/IEC TS 5723,
IEEE vocabularies, textbooks and individual papers. Every entry therefore keeps
its citation, and `source` names the publisher whose words these are, not NIST.

What is deliberately dropped, and why:

* Definitions after the first. A term carries up to five, one per publication;
  the first is the primary and a tooltip cannot show five.
* The "Related terms and synonyms" column. It is *related terms*, not synonyms —
  "active learning agent" lists "passive learning agent", its opposite, and
  "biometric data" lists "personal data". Treating those as aliases would put
  the wrong definition under a word the user clicked. Acronyms are taken from
  the term text instead ("human-computer interaction (HCI)"), which is safe.
"""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "content" / "glossary-ai.json"

# "human-computer interaction (HCI)" -> term + alias. Conservative on purpose:
# the parenthetical must look like an acronym, so "ISO/IEC_TS_5723:2022(en)" and
# other trailing qualifiers are left alone.
_ACRONYM = re.compile(r"^(.+?)\s*\(([A-Z][A-Za-z0-9/\-]{1,11})\)$")


def clean(text: str) -> str:
    """Entities are unescaped for the same reason as the CSRC import — a raw
    `&nbsp;` rendered in a tooltip is a bug. No tag stripping here: the angle
    brackets in this corpus are ISO/IEEE domain qualifiers ("<of an item> ability
    to perform as and when required"), not markup, and removing them would
    truncate the quote."""
    return " ".join(html.unescape(text or "").split()).strip()


def convert(rows: list[dict]) -> list[dict]:
    # Which acronyms are ambiguous must be known before any is kept.
    claims: Counter[str] = Counter()
    for row in rows:
        if m := _ACRONYM.match(clean(row.get("Terms", ""))):
            claims[m.group(2).lower()] += 1

    terms: list[dict] = []
    for row in rows:
        term = clean(row.get("Terms", ""))
        if not term:
            continue

        definition = citation = ""
        for i in range(1, 6):
            if definition := clean(row.get(f"Definition {i}", "")):
                citation = clean(row.get(f"Citation {i}", ""))
                break
        if not definition:
            continue

        aliases: list[str] = []
        if (m := _ACRONYM.match(term)) and claims[m.group(2).lower()] == 1:
            term, acronym = clean(m.group(1)), m.group(2)
            aliases.append(acronym)

        terms.append({
            "term": term,
            "definition": definition,
            # Citations are keys like "IEEE_Guide_IPA" or "Russell_and_Norvig".
            "source": citation.replace("_", " ") or "NIST Trustworthy AI glossary",
            "source_url": "",  # the CSV carries citation keys, not links
            "aliases": aliases,
            "tags": ["ai"],
            "imported": True,
        })

    terms.sort(key=lambda t: t["term"].lower())
    return terms


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: python -m scripts.import_ai_glossary \"<Glossary.csv>\"\n"
            "Export it from https://airc.nist.gov/glossary/"
        )
    src = Path(sys.argv[1])
    if not src.exists():
        raise SystemExit(f"not found: {src}")

    rows = list(csv.DictReader(src.read_text(encoding="utf-8-sig").splitlines()))
    terms = convert(rows)
    OUT.write_text(
        json.dumps(
            {
                "_comment": (
                    "GENERATED — do not hand-edit. Rebuild with "
                    "`python -m scripts.import_ai_glossary <Glossary.csv>`. Hand-written "
                    "entries belong in glossary.yaml, which wins on any name collision."
                ),
                "_source": (
                    "Compiled in 'The Language of Trustworthy AI: An In-Depth Glossary of "
                    "Terms', NIST AI Resource Center (https://airc.nist.gov/glossary/). "
                    "Definitions are quoted from the publication named in each entry's "
                    "`source`, not authored by NIST."
                ),
                "terms": terms,
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"{len(terms)} terms written to {OUT.name} ({len(rows) - len(terms)} rows dropped)")
    print(f"  with an acronym alias: {sum(1 for t in terms if t['aliases'])}")


if __name__ == "__main__":
    main()
