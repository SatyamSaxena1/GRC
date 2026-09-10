from __future__ import annotations

import pytest

from app.content.load import load
from app.routers import connectors


class Response:
    def __init__(self, attributes):
        self.content = b"{}"
        self._attributes = attributes

    def raise_for_status(self):
        return None

    def json(self):
        return {"attributes": self._attributes}


SOURCES = {
    "aws": {
        "encryption_at_rest": True,
        "privileged_access_mfa": True,
        "access_logging_enabled": True,
        "backup_enabled": True,
    },
    "m365": {"privileged_access_mfa": True, "access_logging_enabled": True},
    "google-workspace": {"privileged_access_mfa": True, "access_logging_enabled": True},
    "hrms": {"terminated_users_with_active_accounts": 0},
}


def test_dpdp_pack_is_a_readiness_subset_with_all_four_sources():
    pack = load().framework("DPDP")
    types = {e.artefact_type for req in pack.requirements for e in req.evidence_requirements}
    assert {"AWS_SNAPSHOT", "M365_SNAPSHOT", "GOOGLE_WORKSPACE_SNAPSHOT", "HRMS_SNAPSHOT"} <= types
    assert len(pack.requirements) == 9


def test_all_four_connectors_pull_structured_evidence(client, bootstrap, monkeypatch):
    org_id, _ = bootstrap(client, frameworks=["DPDP"])
    headers = {"authorization": f"org:{org_id}"}

    for source in SOURCES:
        monkeypatch.setenv(connectors._env_key(source, "URL"), f"https://collector.test/{source}")

    monkeypatch.setattr(
        connectors.requests,
        "get",
        lambda url, **_: Response(SOURCES[url.rsplit("/", 1)[-1]]),
    )

    for source in SOURCES:
        response = client.post(f"/connectors/{source}/sync", headers=headers)
        assert response.status_code == 202, response.text

    status = client.get("/connectors", headers=headers).json()
    assert {row["source"] for row in status if row["status"] == "READY"} == set(SOURCES)

    readiness = client.get("/analytics/readiness/DPDP", headers=headers).json()
    by_clause = {row["clause"]: row["verdict"] for row in readiness["clauses"]}
    assert by_clause["Rule 6 - AWS baseline"] == "PASS"
    assert by_clause["Rule 6 - M365 baseline"] == "PASS"
    assert by_clause["Rule 6 - Google Workspace baseline"] == "PASS"
    assert by_clause["Rule 6 - HRMS baseline"] == "PASS"


def test_unconfigured_connector_fails_plainly(client, bootstrap):
    org_id, _ = bootstrap(client, frameworks=["DPDP"])
    response = client.post("/connectors/aws/sync", headers={"authorization": f"org:{org_id}"})
    assert response.status_code == 409
    assert "not configured" in response.json()["detail"]
