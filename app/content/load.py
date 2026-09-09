"""Load and validate UCF content packs.

Content is data, not code: frameworks, requirements, UCO mappings, delta
conditions and the glossary all live in the YAML files next to this module.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, PrivateAttr

CONTENT_DIR = Path(__file__).parent

Operator = Literal[">=", "<=", ">", "<", "==", "!=", "contains_all", "one_of"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Uco(_Model):
    code: str
    title: str
    domain: str


class DeltaCondition(_Model):
    attribute: str
    operator: Operator
    value: Any


class Mapping(_Model):
    uco: str
    coverage: Literal["FULL", "PARTIAL", "SUPPORTING"]
    confidence: float
    source: Literal["EXPERT", "AI", "IMPORTED"]
    delta_conditions: tuple[DeltaCondition, ...] = ()


class EvidenceValidity(_Model):
    """How long evidence for this evidence-artefact-type stays good.

    Freshness is a property of *this artefact type within this requirement*, not
    of the requirement as a whole: a clause can involve two artefact types with
    two different freshness rules (a POLICY that states a cadence, and a record
    whose freshness is judged against that stated cadence — see
    org_defined_max_age_attribute below). Evaluated against the audit period
    when one is supplied, so a verdict means "current for this audit" rather
    than "current when the job happened to run".
    """
    # Attribute holding an explicit expiry date stated by the document itself.
    expiry_attribute: str | None = None
    # Or derive expiry: this attribute (a date) plus max_age_days.
    issued_attribute: str | None = None
    max_age_days: int | None = None
    # Or: the ceiling is not a framework-wide constant but this org's own stated
    # commitment (an "organization-defined parameter", NIST 800-53's term) —
    # resolved from OrgCommitment at evaluation time instead of a literal.
    # Mutually exclusive with max_age_days.
    org_defined_max_age_attribute: str | None = None
    # A requirement can insist the document state its expiry rather than infer it.
    required: bool = True


class EvidenceRequirement(_Model):
    artefact_type: str
    required_attributes: tuple[str, ...]
    evidence_validity: EvidenceValidity | None = None


class Requirement(_Model):
    clause: str
    title: str
    text: str
    evidence_requirements: tuple[EvidenceRequirement, ...]
    mappings: tuple[Mapping, ...]
    # Framework-authored remediation advice, appended to the generic per-gap-kind
    # wording in app/service.py::_remediation. Optional: only packs whose source
    # publishes actionable guidance (the AI RMF Playbook) have anything real to
    # put here, and an empty string is better than a restatement of the clause.
    guidance: str = ""


class FrameworkRef(_Model):
    code: str
    version: str


class Pack(_Model):
    framework: FrameworkRef
    requirements: tuple[Requirement, ...]


class Term(_Model):
    """One glossary entry. `source` names the document that settles the wording —
    a law outranks a standard outranks PLATFORM (our own) — so a disputed
    definition is traceable rather than merely asserted. `aliases` exist because
    in GRC people search for the acronym, not the term."""
    term: str
    definition: str
    source: str
    source_url: str = ""
    # Our own editorial gloss, kept OUT of `definition` so a quoted source's
    # words are never mixed with ours under that source's citation. If `source`
    # names a publication, `definition` is that publication's text; anything we
    # added about why it matters here belongs in `note`.
    note: str = ""
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    # True for the bulk-imported reference corpus, false for the hand-written
    # entries. Not cosmetic: the curated set is the vocabulary this product
    # actually uses, so it outranks the long tail in search and is what the
    # glossary shows before anyone types anything.
    imported: bool = False

    def names(self) -> tuple[str, ...]:
        return (self.term, *self.aliases)


# Reference data, not packs. Loaded from the same directory but under their own
# schemas, so the pack glob below must skip them.
_NON_PACK_FILES = {"uco.yaml", "glossary.yaml"}

# The imported layers, in precedence order after the hand-written glossary.yaml.
# JSON rather than YAML because they are machine written and machine read —
# nothing hand-edits them, so YAML's readability buys nothing and costs ~10x the
# parse time on 1.5MB. See scripts/import_*_glossary.py and ADR-015.
_IMPORTED_GLOSSARIES = (
    "glossary-nist.json",  # NIST CSRC — NIST's own words, public domain
    "glossary-ai.json",    # Trustworthy-AI compilation — quotes third parties, so it ranks last
)


class Content(_Model):
    ucos: tuple[Uco, ...]
    packs: tuple[Pack, ...]
    terms: tuple[Term, ...] = ()

    # Built once in model_post_init. Private, so they stay out of equality and
    # serialization — two Contents with the same terms are still equal.
    _by_name: dict[str, Term] = PrivateAttr(default_factory=dict)
    _searchable: list[tuple[Term, tuple[str, ...], str]] = PrivateAttr(default_factory=list)

    def model_post_init(self, _context: Any) -> None:
        """Fold the terms into a lookup once, rather than lowercasing several
        thousand names again on every request. The name index is what a tooltip
        hits, so that path must not be a scan."""
        by_name: dict[str, Term] = {}
        searchable: list[tuple[Term, tuple[str, ...], str]] = []
        for t in self.terms:
            names = tuple(n.lower() for n in t.names())
            for n in names:
                by_name.setdefault(n, t)
            searchable.append((t, names, t.definition.lower()))
        searchable.sort(key=lambda s: s[1][0])
        self._by_name = by_name
        self._searchable = searchable

    def framework(self, code: str) -> Pack:
        for pack in self.packs:
            if pack.framework.code == code:
                return pack
        raise KeyError(code)

    def requirement(self, framework: str, clause: str) -> Requirement | None:
        """One requirement by framework and clause, or None. Tolerant on purpose:
        callers hold a stored link whose pack may since have changed, and a
        missing clause must degrade (no title, no guidance) rather than raise
        inside the evaluation pipeline."""
        try:
            pack = self.framework(framework)
        except KeyError:
            return None
        return next((r for r in pack.requirements if r.clause == clause), None)

    def find_terms(self, query: str = "", tag: str = "", limit: int = 50) -> list[Term]:
        """Glossary search, ranked: exact name, then prefix, then substring, then
        a hit in the definition body. Alphabetical within each rank, so results
        are stable.

        Curated entries outrank imported ones at equal match quality, so the
        few dozen words this product actually uses are never buried under the
        several thousand reference entries that merely mention them.

        Still a linear scan, but over names lowercased once at load rather than
        per query.
        # ponytail: full scan over ~4k entries, a fraction of a millisecond.
        # Move to Postgres full-text only if the corpus grows an order of
        # magnitude, or if search needs stemming rather than substring matching.
        """
        wanted = tag.strip().lower()
        rows = self._searchable
        if wanted:
            rows = [r for r in rows if wanted in (x.lower() for x in r[0].tags)]

        q = query.strip().lower()
        if not q:
            # Nothing typed yet: show the curated vocabulary, not the corpus.
            return [r[0] for r in rows if not r[0].imported][:limit]

        ranked: list[tuple[int, bool, str, Term]] = []
        for term, names, definition in rows:
            if q in names:
                rank = 0
            elif any(n.startswith(q) for n in names):
                rank = 1
            elif any(q in n for n in names):
                rank = 2
            elif q in definition:
                rank = 3
            else:
                continue
            ranked.append((rank, term.imported, names[0], term))

        ranked.sort(key=lambda r: (r[0], r[1], r[2]))
        return [t for *_, t in ranked[:limit]]

    def term(self, name: str) -> Term:
        """Exact lookup by term or alias, case-insensitive. Raises KeyError."""
        try:
            return self._by_name[name.strip().lower()]
        except KeyError:
            raise KeyError(name) from None


def _read(path: Path) -> Any:
    """Content is UTF-8, always. Path.read_text() would otherwise decode with the
    platform default — cp1252 on Windows — which silently mangles every
    non-ASCII character (an em-dash arrives as 'â€"') instead of failing."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load(content_dir: Path = CONTENT_DIR) -> Content:
    """Cached: five modules call this at import time, and re-reading a dozen
    files (including a 1.5MB glossary) once per caller was pure waste. Content is
    frozen, so every caller sharing one instance is safe."""
    ucos = tuple(Uco(**u) for u in _read(content_dir / "uco.yaml")["ucos"])
    packs = tuple(
        Pack(**_read(path))
        for path in sorted(content_dir.glob("*.yaml"))
        if path.name not in _NON_PACK_FILES
    )
    _check_references(ucos, packs)

    glossary = content_dir / "glossary.yaml"
    curated = tuple(
        Term(**t) for t in (_read(glossary)["terms"] if glossary.exists() else [])
    )
    _check_terms(curated)

    imported = [
        tuple(
            Term(**t)
            for t in json.loads(path.read_text(encoding="utf-8"))["terms"]
        )
        for name in _IMPORTED_GLOSSARIES
        if (path := content_dir / name).exists()
    ]
    return Content(ucos=ucos, packs=packs, terms=_merge_terms(curated, *imported))


def _merge_terms(*layers: tuple[Term, ...]) -> tuple[Term, ...]:
    """Fold the glossary layers into one namespace, earlier layers winning.

    Layers are passed in precedence order — curated, then NIST CSRC, then the
    AI compilation. The hand-written file holds the platform vocabulary, the
    legal definitions and the deliberately paraphrased standards, so an imported
    entry never shadows one; between the two imports, the security corpus is
    NIST's own words while the AI one quotes third parties, so it goes last.

    Within each layer a term's own name beats being some other entry's alias, so
    canonical names are all claimed in a first pass before any alias is
    considered. "Additional Authenticated Data" is a real term with a real
    definition *and* the spelled-out form of another entry's acronym; resolving
    that in one pass silently drops ~357 defined terms depending on file order.

    An alias whose name is already claimed is dropped while its term is kept:
    the entry stays findable under its own name, and the acronym keeps resolving
    to whoever owns it instead of flipping to whichever loaded last.
    """
    taken: set[str] = set()
    merged: list[Term] = []
    for layer in layers:
        survivors = [t for t in layer if t.term.lower() not in taken]
        taken.update(t.term.lower() for t in survivors)
        for t in survivors:
            aliases = tuple(a for a in t.aliases if a.lower() not in taken)
            merged.append(t if aliases == t.aliases else t.model_copy(update={"aliases": aliases}))
            taken.update(a.lower() for a in aliases)
    return tuple(merged)


def _check_terms(terms: tuple[Term, ...]) -> None:
    """A name that resolves to two entries makes lookup silently pick one, so in
    the hand-written file it is a load-time error — aliases share the namespace
    with terms. Imported entries are deduplicated by _merge_terms instead, since
    a collision there is expected rather than a typo."""
    seen: dict[str, str] = {}
    for t in terms:
        for name in t.names():
            key = name.lower()
            if key in seen:
                raise ValueError(
                    f"glossary name '{name}' is claimed by both "
                    f"'{seen[key]}' and '{t.term}'"
                )
            seen[key] = t.term


def _check_references(ucos: tuple[Uco, ...], packs: tuple[Pack, ...]) -> None:
    known = {u.code for u in ucos}
    if len(known) != len(ucos):
        raise ValueError("duplicate UCO codes")
    for pack in packs:
        clauses = [r.clause for r in pack.requirements]
        if len(set(clauses)) != len(clauses):
            raise ValueError(f"duplicate clauses in {pack.framework.code}")
        for req in pack.requirements:
            for mapping in req.mappings:
                if mapping.uco not in known:
                    raise ValueError(
                        f"{pack.framework.code} {req.clause} maps to unknown "
                        f"UCO {mapping.uco}"
                    )


if __name__ == "__main__":
    content = load()
    print(f"{len(content.ucos)} UCOs, {len(content.packs)} frameworks, "
          f"{len(content.terms)} glossary terms")
    for pack in content.packs:
        print(f"  {pack.framework.code} {pack.framework.version}: "
              f"{len(pack.requirements)} requirements")
