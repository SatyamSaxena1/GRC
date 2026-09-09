"""The glossary is reference data — no tenant rows, so what is worth testing is
the search ranking, the alias namespace, and that every entry is attributable."""

from __future__ import annotations

import re

import pytest

from app.content.load import Term, _check_terms, _merge_terms
from app.content.load import load as load_content

CONTENT = load_content()

CURATED = [t for t in CONTENT.terms if not t.imported]
IMPORTED = [t for t in CONTENT.terms if t.imported]
NIST = [t for t in IMPORTED if "nist" in t.tags]
AI = [t for t in IMPORTED if "ai" in t.tags]


def test_every_term_is_attributed():
    """An unsourced definition is an assertion, not a reference. PLATFORM is a
    valid source (we wrote it); an empty one is not."""
    assert CONTENT.terms
    for t in CONTENT.terms:
        assert t.source.strip(), f"{t.term} has no source"
        assert t.definition.strip(), f"{t.term} has no definition"


def test_a_cited_definition_is_not_mixed_with_our_commentary():
    """A definition under a publication's citation must be that publication's
    words. Our own gloss goes in `note`.

    This started as a real defect: 'Audit log' cited NIST SP 800-53 and then
    appended a sentence of ours about tamper-evidence, so a reader could not tell
    where NIST stopped. The heuristic here is deliberately blunt — a first-person
    editorial voice inside a cited definition is the tell.
    """
    tells = ("in this product", "in practice:", "compliance value", "this platform")
    offenders = [
        t.term for t in CURATED
        if t.source != "PLATFORM"
        and any(tell in t.definition.lower() for tell in tells)
    ]
    assert not offenders, offenders


def test_unverified_paraphrases_are_labelled_as_adapted():
    """Entries we wrote from knowledge of a source, rather than quoting it, say
    'Adapted from' — so nothing reads as a quotation that was never checked
    against the document it names."""
    adapted = [t for t in CURATED if t.source.startswith("Adapted from")]
    assert adapted, "the 'Adapted from' convention has been lost"
    assert all(t.source_url for t in adapted), "an adapted entry still needs its source link"


def test_content_is_decoded_as_utf8():
    """Regression: Path.read_text() defaults to the platform encoding, so on
    Windows every em-dash in the content packs arrived as 'â€"' — mangled, not
    an error. Applies to all content, not just the glossary."""
    text = " ".join(t.definition for t in CONTENT.terms)
    text += " ".join(r.text for p in CONTENT.packs for r in p.requirements)
    assert "â€" not in text
    assert "—" in text, "no em-dash in the corpus — this test would pass vacuously"


def test_search_ranks_exact_name_above_a_body_mention():
    """'risk' appears in the body of several entries; the entry actually named
    Risk must come first or the tooltip shows the wrong thing."""
    assert CONTENT.find_terms("risk")[0].term == "Risk"


def test_search_finds_acronyms():
    assert CONTENT.term("MFA").term == "Multi-factor authentication"
    assert CONTENT.term("phi").term == "Protected Health Information"  # case-insensitive
    assert CONTENT.find_terms("SoA")[0].term == "Statement of Applicability"


def test_unknown_term_raises():
    with pytest.raises(KeyError):
        CONTENT.term("not a real term")


def test_empty_query_lists_curated_only_alphabetically():
    """With ~3.9k imported entries against ~70 curated ones, listing everything
    would bury the vocabulary this product actually uses."""
    rows = CONTENT.find_terms("", limit=500)
    assert rows and not any(t.imported for t in rows)
    names = [t.term for t in rows]
    assert names == sorted(names, key=str.lower)


# ------------------------------------------------------- the two glossary layers


def test_all_three_layers_are_present():
    assert len(CURATED) > 50, "hand-written glossary missing"
    assert len(NIST) > 3000, "CSRC import missing — run scripts/import_nist_glossary.py"
    assert len(AI) > 300, "AI import missing — run scripts/import_ai_glossary.py"


def test_layer_precedence_curated_then_nist_then_ai():
    """Three layers claim overlapping words. Curated is ours and wins outright;
    between the imports, CSRC is NIST's own text while the AI file quotes third
    parties, so CSRC ranks higher."""
    assert not CONTENT.term("Encryption").imported          # curated beats both
    assert "nist" in CONTENT.term("accountability").tags     # CSRC beats the AI file
    assert "ai" in CONTENT.term("model card").tags           # AI file owns what it alone defines


def test_ai_layer_keeps_the_citation_of_whoever_wrote_it():
    """These definitions are quoted from ISO, IEEE, textbooks and papers — NIST
    only compiled them, so `source` must name the actual publisher."""
    assert all(t.source.strip() for t in AI)
    assert not any(t.source.startswith("PLATFORM") for t in AI)


def test_ai_related_terms_are_not_treated_as_aliases():
    """'active learning agent' lists 'passive learning agent' in the CSV's
    "Related terms and synonyms" column — its *opposite*, not a synonym.
    Importing that column as aliases would resolve one to the other's
    definition. Both are real entries; they must stay distinct."""
    active = CONTENT.term("active learning agent")
    passive = CONTENT.term("passive learning agent")
    assert active.aliases == ()
    assert active.term != passive.term
    assert active.definition != passive.definition


def test_curated_wins_a_name_collision_with_the_import():
    """NIST also defines 'encryption' and 'attestation'. The hand-written entry
    is the one deliberately written for this product, so it must survive."""
    for name in ("Encryption", "Attestation", "MFA", "Availability"):
        assert not CONTENT.term(name).imported, f"{name} was shadowed by the import"
    assert CONTENT.term("Attestation").source == "PLATFORM"


def test_a_term_outranks_being_another_entrys_alias():
    """Regression: merging in one pass dropped ~357 defined NIST terms whose name
    happened to be the spelled-out form of some other entry's acronym."""
    t = CONTENT.term("Additional Authenticated Data")
    assert t.definition and t.imported


def test_merge_drops_the_colliding_alias_not_the_term():
    curated = (Term(term="Multi-factor authentication", definition="ours", source="PLATFORM",
                    aliases=("MFA",)),)
    imported = (Term(term="Mandatory Access Control", definition="theirs", source="NIST",
                     aliases=("MFA", "MAC"), imported=True),)
    merged = _merge_terms(curated, imported)

    assert len(merged) == 2, "the imported term itself should survive"
    kept = merged[1]
    assert kept.aliases == ("MAC",), "only the claimed alias should be dropped"
    assert {t.term: t.definition for t in merged}["Multi-factor authentication"] == "ours"


def test_search_prefers_curated_at_equal_match_quality():
    hits = CONTENT.find_terms("access")
    assert hits[0].term == "Access review" and not hits[0].imported


def test_imported_corpus_is_attributed_to_a_real_document():
    """The point of importing rather than writing them: every entry carries the
    NIST publication it came from."""
    sample = [t for t in IMPORTED if t.source_url][:200]
    assert len(sample) > 100
    assert all(t.source_url.startswith("http") for t in sample)


def test_imports_decode_html_entities():
    """Regression: 32 CSRC entries reached the UI reading
    'on&nbsp;\\([0,n-1]\\)'. Stripping tags is not enough — entities have to be
    unescaped too, in both imports."""
    entity = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,10}|#\d{1,5}|#x[0-9a-fA-F]{1,5});")
    offenders = [
        t.term for t in IMPORTED
        if entity.search(t.term) or entity.search(t.definition)
    ]
    assert not offenders, offenders[:5]


def test_csrc_import_strips_html():
    """CSRC term text carries real HTML (`<em>A</em>`); the importer strips it.

    Scoped to the CSRC layer and to tag-shaped matches. A bare '<' is legitimate
    maths there ("where x<2m"), and the AI layer keeps angle brackets on purpose
    — ISO and IEEE write domain qualifiers that way ("<of an item> ability to
    perform as and when required"), so stripping them would damage the quote.
    """
    tag = re.compile(r"</?(em|i|b|strong|span|p|br|sub|sup)\b[^>]*>", re.I)
    offenders = [t.term for t in NIST if tag.search(t.term) or tag.search(t.definition)]
    assert not offenders, offenders[:5]


def test_duplicate_name_across_alias_and_term_is_rejected():
    """Aliases share the namespace with terms, so a collision would make lookup
    silently pick one. It must fail at load time instead."""
    with pytest.raises(ValueError, match="MFA"):
        _check_terms((
            Term(term="Multi-factor authentication", definition="d", source="s", aliases=("MFA",)),
            Term(term="MFA", definition="d", source="s"),
        ))


def test_endpoint_search_and_lookup(client, bootstrap):
    org_id, _ = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}

    hits = client.get("/glossary", params={"q": "least"}, headers=headers).json()
    assert hits[0]["term"] == "Least privilege"
    assert hits[0]["source"].startswith("NIST")
    assert "\n" not in hits[0]["definition"]  # YAML folding collapsed to one line

    one = client.get("/glossary/UCO", headers=headers).json()
    assert one["term"] == "Unified Control Objective"

    assert client.get("/glossary/nonsense", headers=headers).status_code == 404


def test_endpoint_requires_auth(client):
    assert client.get("/glossary").status_code == 422  # missing authorization header


def test_tag_filter(client, bootstrap):
    org_id, _ = bootstrap(client)
    rows = client.get("/glossary", params={"tag": "gdpr", "limit": 100},
                      headers={"authorization": f"org:{org_id}"}).json()
    assert rows and all("gdpr" in r["tags"] for r in rows)
