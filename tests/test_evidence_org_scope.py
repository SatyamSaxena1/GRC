"""A firm-side user with no client open has audit_firm_id but no org_id — there
is no tenant for an upload to belong to. This used to be let through, creating
an orphaned Evidence(org_id="") that crashed the background pipeline the
instant it dereferenced org.frameworks (org_id="" matches no Organization),
and returned quality:{} instead of null on GET, which crashed the frontend's
`evidence.quality && evidence.quality.dimensions.map(...)` guard — a real
report, not a hypothetical.
"""

from __future__ import annotations


def test_upload_without_an_organisation_selected_is_rejected(client):
    firm = client.post("/admin/audit-firms", json={"name": "Gemba"}).json()
    admin = client.post("/admin/users", json={
        "email": "admin@gemba.test", "audit_firm_id": firm["id"], "role": "FIRM_ADMIN",
    }).json()

    resp = client.post("/evidence", headers={"authorization": f"user:{admin['id']}"},
                       params={"artefact_type": "POLICY"},
                       files={"file": ("policy.txt", b"a policy", "text/plain")})

    assert resp.status_code == 400
    assert "no organisation selected" in resp.json()["detail"]


def test_quality_is_null_not_an_empty_object_before_scoring_runs(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    body = client.get(f"/evidence/{evidence_id}", headers={"authorization": f"org:{org_id}"}).json()
    # Extraction is unavailable in tests, so quality scoring may not have run
    # yet or may have run against nothing — either way this must never be {},
    # which the frontend's `quality && quality.dimensions.map(...)` guard
    # would treat as truthy-but-shapeless and crash on.
    assert body["quality"] is None or "dimensions" in body["quality"]
