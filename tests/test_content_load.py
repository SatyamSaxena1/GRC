import pytest

from app.content import load as content_load
from app.content.load import load


def test_load_is_deterministic_and_references_resolve():
    assert load() == load()  # frozen models; loading twice is identical
    content = load()
    known = {u.code for u in content.ucos}
    assert known
    for pack in content.packs:
        assert pack.requirements
        for req in pack.requirements:
            assert req.mappings and req.evidence_requirements
            assert all(m.uco in known for m in req.mappings)


def test_unknown_uco_reference_is_rejected(tmp_path):
    (tmp_path / "uco.yaml").write_text(
        "ucos:\n  - {code: UCO-X, title: t, domain: d}\n"
    )
    (tmp_path / "bad.yaml").write_text("""
framework: {code: F, version: "1"}
requirements:
  - clause: "1"
    title: t
    text: t
    evidence_requirements: [{artefact_type: POLICY, required_attributes: [a]}]
    mappings: [{uco: UCO-NOPE, coverage: FULL, confidence: 1.0, source: EXPERT}]
""")
    with pytest.raises(ValueError, match="UCO-NOPE"):
        load(tmp_path)


def test_both_frameworks_are_present():
    content = load()
    assert content.framework("ISO-27001").framework.version == "2022"
    assert content.framework("PCI-DSS").framework.version == "4.0.1"
    assert content_load.CONTENT_DIR.is_dir()
