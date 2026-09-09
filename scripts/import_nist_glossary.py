"""Import NIST's CSRC glossary into app/content/glossary-nist.json.

Run occasionally, commit the output, done — this is not a runtime dependency and
nothing in the app ever reaches for the network. NIST publishes the whole
glossary as a bulk download refreshed daily, so there is no scraping involved:

    https://csrc.nist.gov/csrc/media/glossary/glossary-export.zip
    https://csrc.nist.gov/csrc/media/glossary/glossary-export.meta   (size + sha256)

NIST publications are US Government work and therefore public domain, so the
definitions are reproduced verbatim with their source citation intact.

    python -m scripts.import_nist_glossary

What is deliberately dropped, and why:

* Entries with no definition (5k of the 9k records). They are acronym pointers —
  ".csv -> Comma-Separated Value" — with nothing to show in a tooltip.
* Every definition after the first. NIST carries up to 39 for a single term
  ("authenticate"), one per publication that defines it. The first is the
  primary; a glossary entry that dumps all 39 is unreadable.
* Aliases claimed by more than one term. "CI" abbreviates several unrelated
  terms, and resolving it to whichever happened to import first would put the
  wrong definition under the word a user clicked. Search still finds them all.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import re
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

EXPORT_URL = "https://csrc.nist.gov/csrc/media/glossary/glossary-export.zip"
META_URL = "https://csrc.nist.gov/csrc/media/glossary/glossary-export.meta"
OUT = Path(__file__).resolve().parent.parent / "app" / "content" / "glossary-nist.json"

_TAG = re.compile(r"<[^>]+>")

# csrc.nist.gov sits behind Cloudflare, which 403s urllib's default UA. Identify
# the tool honestly rather than impersonating a browser.
_UA = "grc-slice-glossary-import/1.0 (+https://csrc.nist.gov/glossary bulk export)"


def _get(url: str) -> bytes:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": _UA}), timeout=60
    ).read()


def clean(text: str) -> str:
    """NIST term and definition text carries markup (`<em>A</em>`), HTML entities
    (`&nbsp;`, `&amp;`) and stray whitespace.

    Order matters: strip tags first so an escaped `&lt;em&gt;` cannot become a
    real one, then unescape, then collapse — `&nbsp;` unescapes to \\xa0, which
    str.split() treats as whitespace and folds away.
    """
    return " ".join(html.unescape(_TAG.sub("", text or "")).split()).strip()


def fetch() -> tuple[list[dict], str]:
    """Download the export and check it against NIST's published sha256, which
    covers the *unzipped* JSON (their `size` field is the JSON's length)."""
    meta = _get(META_URL).decode("utf-8-sig")
    expected = next(
        (line.split(":", 1)[1].strip().lower()
         for line in meta.splitlines() if line.lower().startswith("sha256")),
        "",
    )
    data = zipfile.ZipFile(io.BytesIO(_get(EXPORT_URL))).read("glossary-export.json")

    actual = hashlib.sha256(data).hexdigest().lower()
    if expected and actual != expected:
        raise SystemExit(
            f"checksum mismatch: NIST published {expected}, downloaded {actual}. "
            "The export is refreshed daily — retry before assuming corruption."
        )
    raw = json.loads(data.decode("utf-8-sig"))
    return raw["parentTerms"], raw["comment"]


def convert(records: list[dict]) -> list[dict]:
    # Which aliases are ambiguous has to be known before any are kept, so count
    # every claim first and only then build the entries.
    claims: Counter[str] = Counter()
    for rec in records:
        if not rec.get("definitions"):
            continue
        for syn in rec.get("abbrSyn") or []:
            if name := clean(syn.get("text", "")):
                claims[name.lower()] += 1

    terms: list[dict] = []
    for rec in records:
        definitions = rec.get("definitions")  # null, not absent, for ~5k records
        term = clean(rec.get("term", ""))
        if not definitions or not term:
            continue

        primary = definitions[0]
        definition = clean(primary.get("text", ""))
        if not definition:
            continue

        sources = primary.get("sources") or []
        source = clean(sources[0].get("text", "")) if sources else "NIST CSRC Glossary"
        source_url = (sources[0].get("link") or "") if sources else rec.get("link", "")

        aliases = [
            name for syn in (rec.get("abbrSyn") or [])
            if (name := clean(syn.get("text", "")))
            and claims[name.lower()] == 1
            and name.lower() != term.lower()
        ]

        terms.append({
            "term": term,
            "definition": definition,
            "source": source,
            "source_url": source_url or rec.get("link", ""),
            "aliases": aliases,
            "tags": ["nist"],
            "imported": True,
        })

    terms.sort(key=lambda t: t["term"].lower())
    return terms


def main() -> None:
    records, comment = fetch()
    terms = convert(records)
    OUT.write_text(
        json.dumps(
            {
                "_comment": (
                    "GENERATED — do not hand-edit. Rebuild with "
                    "`python -m scripts.import_nist_glossary`. Hand-written entries "
                    "belong in glossary.yaml, which wins on any name collision."
                ),
                "_source": comment,
                "_url": EXPORT_URL,
                "terms": terms,
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    dropped = len(records) - len(terms)
    print(f"{len(terms)} terms written to {OUT.name} ({dropped} records dropped: no definition)")
    print(f"  with aliases: {sum(1 for t in terms if t['aliases'])}")


if __name__ == "__main__":
    main()
