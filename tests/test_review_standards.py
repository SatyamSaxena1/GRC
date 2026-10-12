"""Review Standards (ADR-027): strict, line-numbered validation; immutable hashed versions;
admin-only publishing that lands in the audit chain; a try-it endpoint that stores nothing."""

from __future__ import annotations

import pytest

from app import audit_log
from app.content.load import load as load_content
from app.models import AuditEvent, ReviewStandard
from app.review import standards

GOOD = """\
name: Acme engineering
rules:
  - id: no-secrets
    title: No credentials in code
    kind: secret_scan
    severity: critical
    action: block
    clauses: ["SOC-2 CC8.1"]
"""
DIFF = """\
diff --git a/app/x.py b/app/x.py
--- a/app/x.py
+++ b/app/x.py
@@ -1 +1,2 @@
 import os
+KEY = "AKIAABCDEFGHIJKLMNOP"
"""


def test_problems_are_reported_with_their_line():
    bad = GOOD + """  - id: no-secrets
    title: Again
    kind: forbid_added
    patern: x
"""
    with pytest.raises(standards.StandardError) as caught:
        standards.parse(bad)
    lines = {p["line"] for p in caught.value.problems}
    assert 12 in lines  # the misspelt key, on its own line
    assert any("patern" in p["message"] for p in caught.value.problems)


@pytest.mark.parametrize("text, message", [
    ("rules: []", "name"),
    ("name: x\nrules:\n  - {id: a, title: A, kind: forbid_added, pattern: '('}", "does not compile"),
    ("name: x\nrules:\n  - {id: a, title: A, kind: forbid_added, pattern: '" + "a" * 600 + "'}", "longer than"),
    ("name: x\nrules:\n  - {id: a, title: A, kind: forbid_dependency}", "needs `packages`"),
    ("name: x\nrules:\n  - {id: a, title: A, kind: secret_scan, detectors: [nope]}", "unknown detector"),
    ("name: x\nrules:\n  - {id: a, title: A, kind: secret_scan}\n  - {id: a, title: B, kind: secret_scan}", "used twice"),
    ("name: x\nrules:\n  - {id: A b, title: A, kind: secret_scan}", "pattern"),
    ("name: [unclosed", "not valid YAML"),
])
def test_invalid_standards_are_rejected(text, message):
    with pytest.raises(standards.StandardError, match=message):
        standards.parse(text)


def test_clauses_must_exist_in_a_pack():
    with pytest.raises(standards.StandardError, match="unknown clause 'SOC-2 CC99.9'"):
        standards.parse(GOOD.replace("CC8.1", "CC99.9"), load_content())
    standards.parse(GOOD, load_content())


def test_the_hash_is_of_the_rules_not_the_formatting():
    reformatted = GOOD.replace('clauses: ["SOC-2 CC8.1"]', "clauses:\n      - SOC-2 CC8.1  # change control")
    assert standards.body_hash(standards.parse(GOOD)) == standards.body_hash(standards.parse(reformatted))
    assert standards.body_hash(standards.parse(GOOD)) != standards.body_hash(
        standards.parse(GOOD.replace("critical", "high")))


def _h(org_id):
    return {"authorization": f"org:{org_id}"}


def test_publishing_makes_an_immutable_active_version_in_the_audit_chain(client, bootstrap, db):
    org_id, _ = bootstrap(client)
    listed = client.get("/review/standards", headers=_h(org_id)).json()
    assert listed["versions"] == [] and listed["default"]["in_force"]

    first = client.post("/review/standards", headers=_h(org_id), json={"yaml": GOOD})
    assert first.status_code == 201, first.text
    second = client.post("/review/standards", headers=_h(org_id), json={"yaml": GOOD.replace("critical", "high")})
    versions = client.get("/review/standards", headers=_h(org_id)).json()["versions"]
    assert [(v["version"], v["is_active"]) for v in versions] == [(2, True), (1, False)]
    assert first.json()["body_hash"] == standards.body_hash(standards.parse(GOOD))

    back = client.post(f"/review/standards/{first.json()['id']}/activate", headers=_h(org_id))
    assert back.status_code == 200
    rows = db.query(ReviewStandard).filter_by(org_id=org_id).order_by(ReviewStandard.version).all()
    assert [r.is_active for r in rows] == [True, False] and rows[0].source_yaml == GOOD
    actions = [e.action for e in db.query(AuditEvent).filter_by(org_id=org_id).order_by(AuditEvent.chain_seq)
               if e.action.startswith("REVIEW_STANDARD")]
    assert actions == ["REVIEW_STANDARD_PUBLISHED", "REVIEW_STANDARD_PUBLISHED", "REVIEW_STANDARD_ACTIVATED"]
    assert audit_log.verify(db, audit_log.chain_of(org_id)).ok
    assert second.status_code == 201


def test_an_invalid_standard_is_a_422_with_line_numbers(client, bootstrap):
    org_id, _ = bootstrap(client)
    response = client.post("/review/standards", headers=_h(org_id), json={"yaml": GOOD.replace("CC8.1", "CC99.9")})
    assert response.status_code == 422
    assert response.json()["detail"]["problems"][0]["line"] == 8


def test_only_an_admin_publishes_and_auditors_can_read(client, bootstrap):
    org_id, engagement_id = bootstrap(client)
    client.post("/review/standards", headers=_h(org_id), json={"yaml": GOOD})
    for role in ("COMPLIANCE_VIEWER", "CONTROL_OWNER"):
        user = client.post("/admin/users", json={"email": f"{role}@acme.test", "org_id": org_id, "role": role},
                           headers=_h(org_id))
        assert user.status_code in (200, 201), user.text
        headers = {"authorization": f"user:{user.json()['id']}"}
        assert client.post("/review/standards", headers=headers, json={"yaml": GOOD}).status_code == 403
        assert client.get("/review/standards", headers=headers).status_code == 200
    auditor = {"authorization": f"auditor:{engagement_id}"}
    assert len(client.get("/review/standards", headers=auditor).json()["versions"]) == 1
    assert client.post("/review/standards", headers=auditor, json={"yaml": GOOD}).status_code == 403


def test_trying_a_standard_stores_and_records_nothing(client, bootstrap, db):
    org_id, _ = bootstrap(client)
    before = db.query(AuditEvent).filter_by(org_id=org_id).count()
    default = client.post("/review/standards/test", headers=_h(org_id), json={"diff": DIFF}).json()
    assert default["standard"]["name"] == "GRC default" and not default["blocking"]  # the default never blocks
    edited = client.post("/review/standards/test", headers=_h(org_id), json={"diff": DIFF, "yaml": GOOD}).json()
    assert edited["blocking"] and edited["findings"][0]["rule_id"] == "no-secrets"
    assert db.query(AuditEvent).filter_by(org_id=org_id).count() == before
    assert db.query(ReviewStandard).filter_by(org_id=org_id).count() == 0


def test_another_organisation_sees_none_of_it(client, bootstrap):
    org_id, _ = bootstrap(client)
    published = client.post("/review/standards", headers=_h(org_id), json={"yaml": GOOD}).json()
    other, _ = bootstrap(client)
    assert client.get("/review/standards", headers=_h(other)).json()["versions"] == []
    assert client.post(f"/review/standards/{published['id']}/activate", headers=_h(other)).status_code == 404


def test_concurrent_edits_conflict_instead_of_overwriting(client, bootstrap):
    org_id, _ = bootstrap(client)
    first = client.post("/review/standards", headers=_h(org_id), json={"yaml": GOOD, "expected_active_version": 0})
    assert first.status_code == 201
    # Two admins both started from version 1; the second to publish is told, not overwritten.
    a = client.post("/review/standards", headers=_h(org_id),
                    json={"yaml": GOOD.replace("critical", "high"), "expected_active_version": 1})
    b = client.post("/review/standards", headers=_h(org_id),
                    json={"yaml": GOOD.replace("critical", "low"), "expected_active_version": 1})
    assert a.status_code == 201 and b.status_code == 409 and "version 2" in b.json()["detail"]
    stale = client.post(f"/review/standards/{first.json()['id']}/activate", headers=_h(org_id),
                        json={"expected_active_version": 1})
    assert stale.status_code == 409


def test_the_database_allows_one_active_version_per_organisation(client, bootstrap, db):
    from sqlalchemy.exc import IntegrityError
    org_id, _ = bootstrap(client)
    body = standards.body(standards.parse(GOOD))
    db.add_all([ReviewStandard(org_id=org_id, name="a", version=v, body=body, body_hash="h", is_active=True)
                for v in (1, 2)])
    with pytest.raises(IntegrityError):
        db.commit()


def test_built_in_packs_are_valid_starting_points(client, bootstrap):
    org_id, _ = bootstrap(client)
    packs = client.get("/review/packs", headers=_h(org_id)).json()
    assert {p["id"] for p in packs} >= {"secure-development", "dependency-controls", "testing", "change-management"}
    for pack in packs:
        standards.parse(pack["yaml"], load_content())  # every clause exists in a loaded pack
    published = client.post("/review/standards", headers=_h(org_id), json={"yaml": packs[0]["yaml"]})
    assert published.status_code == 201 and published.json()["body_hash"] == packs[0]["body_hash"]
