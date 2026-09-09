"""Organization-defined commitments (see docs/adr/013). The regression this file
exists to prevent: a policy merely stating a review cadence used to pass a
generic ceiling with no proof a review ever happened. A REVIEW_RECORD is now
required and measured against the org's OWN stated cadence, not a constant.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import db as db_module
from app.content.load import load
from app.evaluate import evaluate
from app.models import Evidence, EvidenceControlLink, OrgCommitment

CONTENT = load()
TODAY = date(2026, 8, 31)


def review_link(attributes, org_commitments, as_of=TODAY, clause="A.5.18"):
    links = {l.clause: l for l in evaluate(
        attributes, "REVIEW_RECORD", ["ISO-27001"], CONTENT, as_of=as_of,
        org_commitments=org_commitments,
    )}
    return links[clause]


# --------------------------------------------------------------------- pure evaluator


def test_no_commitment_is_its_own_gap_not_a_silent_pass():
    link = review_link({"last_access_review_date": "2026-08-01"}, org_commitments={})
    assert link.verdict != "PASS"
    assert any(g.kind == "NO_ORG_COMMITMENT" for g in link.gaps)
    assert any(g.attribute == "access_review_frequency_days" for g in link.gaps)


def test_review_older_than_the_orgs_own_commitment_fails():
    """This is the exact regression: 75 days old would have PASSED the old
    generic 365-day ceiling, but the org itself committed to 60 days."""
    stale_date = (TODAY - timedelta(days=75)).isoformat()
    link = review_link(
        {"last_access_review_date": stale_date},
        org_commitments={"access_review_frequency_days": 60},
    )
    assert link.verdict == "FAIL"
    stale = [g for g in link.gaps if g.kind == "STALE"]
    assert len(stale) == 1
    assert "60 days" in stale[0].required


def test_review_within_the_orgs_own_commitment_passes():
    fresh_date = (TODAY - timedelta(days=10)).isoformat()
    link = review_link(
        {"last_access_review_date": fresh_date},
        org_commitments={"access_review_frequency_days": 60},
    )
    assert link.verdict == "PASS"
    assert not link.gaps


def test_commitment_stated_as_a_cadence_word_is_understood():
    """A policy is as likely to say 'quarterly' as '90 days'."""
    fresh_date = (TODAY - timedelta(days=10)).isoformat()
    link = review_link(
        {"last_access_review_date": fresh_date},
        org_commitments={"access_review_frequency_days": "quarterly"},
    )
    assert link.verdict == "PASS"


def test_unusable_commitment_value_is_its_own_gap():
    link = review_link(
        {"last_access_review_date": "2026-08-01"},
        org_commitments={"access_review_frequency_days": "whenever we feel like it"},
    )
    assert any(g.kind == "NO_ORG_COMMITMENT" for g in link.gaps)


def test_pci_access_review_stays_framework_defined_not_org_defined():
    """PCI itself states 'at least once every six months' — unlike the other six
    frameworks, this is not deferred to the org, so no commitment is needed and
    a looser org commitment (or none at all) cannot loosen PCI's own ceiling."""
    old_date = (TODAY - timedelta(days=200)).isoformat()
    link = {l.clause: l for l in evaluate(
        {"last_access_review_date": old_date}, "REVIEW_RECORD", ["PCI-DSS"], CONTENT,
        as_of=TODAY, org_commitments={},  # no commitment at all
    )}["7.2.4"]
    assert not any(g.kind == "NO_ORG_COMMITMENT" for g in link.gaps)
    assert any(g.kind == "STALE" for g in link.gaps)  # 200 days > PCI's 183-day ceiling

    within_pci_window = (TODAY - timedelta(days=100)).isoformat()
    fresh = {l.clause: l for l in evaluate(
        {"last_access_review_date": within_pci_window}, "REVIEW_RECORD", ["PCI-DSS"],
        CONTENT, as_of=TODAY, org_commitments={"access_review_frequency_days": 20},
    )}["7.2.4"]
    # An org commitment of 20 days must not tighten PCI's window either — it's simply ignored.
    assert fresh.verdict == "PASS"


# --------------------------------------------------------------------- pipeline (upsert)


def controls_for(org_id):
    with Session(db_module.engine) as s:
        from app.models import OrgControl
        return {(c.framework, c.clause): c.id
                for c in s.query(OrgControl).filter_by(org_id=org_id)}


def test_policy_upload_creates_and_updates_org_commitment(client, bootstrap, upload, monkeypatch):
    from app import service
    from app.ai.schemas import ExtractedField, ExtractionRun

    def fake_extract(text, names, method="native_text", gateway=None):
        values = {"access_review_frequency_days": 60}
        return ExtractionRun(
            fields={n: ExtractedField(value=values.get(n), confidence=1.0) for n in names},
            model="stub", provider="stub", status="OK",
        )

    monkeypatch.setattr(service, "extract_attributes", fake_extract)
    org_id, _ = bootstrap(client)
    upload(client, org_id, content=b"policy document one")

    with Session(db_module.engine) as s:
        row = s.query(OrgCommitment).filter_by(
            org_id=org_id, attribute="access_review_frequency_days").one()
        assert row.value == 60
        first_updated_at = row.updated_at

    # A second POLICY upload with a different value updates the same row (one
    # per org+attribute), not a duplicate.
    def fake_extract_v2(text, names, method="native_text", gateway=None):
        values = {"access_review_frequency_days": 30}
        return ExtractionRun(
            fields={n: ExtractedField(value=values.get(n), confidence=1.0) for n in names},
            model="stub", provider="stub", status="OK",
        )

    monkeypatch.setattr(service, "extract_attributes", fake_extract_v2)
    upload(client, org_id, content=b"policy document two, tightened", name="policy2.txt")

    with Session(db_module.engine) as s:
        rows = s.query(OrgCommitment).filter_by(
            org_id=org_id, attribute="access_review_frequency_days").all()
        assert len(rows) == 1
        assert rows[0].value == 30
        assert rows[0].updated_at >= first_updated_at


def test_staleness_flag_appears_without_rewriting_the_old_verdict(
    client, bootstrap, upload, monkeypatch
):
    from app import service
    from app.ai.schemas import ExtractedField, ExtractionRun

    def policy_extract(days):
        def fake(text, names, method="native_text", gateway=None):
            values = {"access_review_frequency_days": days}
            return ExtractionRun(
                fields={n: ExtractedField(value=values.get(n), confidence=1.0) for n in names},
                model="stub", provider="stub", status="OK",
            )
        return fake

    def review_extract(days_ago):
        def fake(text, names, method="native_text", gateway=None):
            when = (date.today() - timedelta(days=days_ago)).isoformat()
            values = {"last_access_review_date": when}
            return ExtractionRun(
                fields={n: ExtractedField(value=values.get(n), confidence=1.0) for n in names},
                model="stub", provider="stub", status="OK",
            )
        return fake

    org_id, engagement_id = bootstrap(client)

    # Policy commits to 90 days; a review from 10 days ago passes.
    monkeypatch.setattr(service, "extract_attributes", policy_extract(90))
    upload(client, org_id, content=b"access review policy, 90 day cadence")
    monkeypatch.setattr(service, "extract_attributes", review_extract(10))
    review_evidence_id = upload(client, org_id, content=b"access review record, recent",
                                artefact_type="REVIEW_RECORD").json()["evidence_id"]

    control_id = controls_for(org_id)[("ISO-27001", "A.5.18")]
    before = client.get(f"/controls/{control_id}",
                        headers={"authorization": f"org:{org_id}"}).json()
    review_link = next(l for l in before["links"] if l["evidence_id"] == review_evidence_id)
    assert review_link["verdict"] == "PASS"
    assert review_link["commitment_stale"] is False

    # Org tightens its own commitment to 5 days — the existing evaluation was
    # against 90 and must not be silently rewritten.
    monkeypatch.setattr(service, "extract_attributes", policy_extract(5))
    upload(client, org_id, content=b"access review policy, tightened to 5 days",
          name="policy-tightened.txt")

    after = client.get(f"/controls/{control_id}",
                       headers={"authorization": f"org:{org_id}"}).json()
    same_link = next(l for l in after["links"] if l["evidence_id"] == review_evidence_id)
    assert same_link["verdict"] == "PASS", "the old verdict must not be rewritten in place"
    assert same_link["commitment_stale"] is True
    assert "access_review_frequency_days" in same_link["stale_reason"]

    # Uploading a new version re-evaluates against the current (5-day) commitment.
    monkeypatch.setattr(service, "extract_attributes", review_extract(10))
    new_version = client.post(
        f"/evidence/{review_evidence_id}/versions",
        headers={"authorization": f"org:{org_id}"},
        files={"file": ("review2.txt", b"access review record", "text/plain")},
    ).json()
    new_eval = client.get(f"/evidence/{new_version['evidence_id']}/evaluations",
                          headers={"authorization": f"org:{org_id}"}).json()
    new_link = next(l for l in new_eval if l["clause"] == "A.5.18")
    assert new_link["verdict"] == "FAIL"  # 10 days ago fails a 5-day commitment
    assert new_link["commitment_stale"] is False  # freshly evaluated against the current one
