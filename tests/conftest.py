"""Shared fixtures. Each test gets its own SQLite file and storage dir, so no
test can see another's rows or objects."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import db as db_module
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setattr(db_module, "engine", create_engine(f"sqlite:///{tmp_path / 'test.db'}"))
    with TestClient(app) as c:  # startup -> init_db() against the fresh engine
        yield c


@pytest.fixture()
def db():
    from sqlalchemy.orm import Session

    with Session(db_module.engine) as session:
        yield session


def _bootstrap(client, frameworks=("ISO-27001", "PCI-DSS")):
    """One org, one audit firm, one active engagement scoped to those frameworks."""
    org = client.post("/admin/organizations",
                      json={"name": "Acme", "frameworks": list(frameworks)}).json()
    firm = client.post("/admin/audit-firms", json={"name": "BigFour"}).json()
    engagement = client.post("/admin/engagements", json={
        "audit_firm_id": firm["id"], "org_id": org["id"], "frameworks": list(frameworks),
    }).json()
    return org["id"], engagement["id"]


def _upload(client, org_id, content=b"an access control policy", name="policy.txt",
            artefact_type="POLICY", mime="text/plain"):
    return client.post("/evidence", headers={"authorization": f"org:{org_id}"},
                       params={"artefact_type": artefact_type},
                       files={"file": (name, content, mime)})


@pytest.fixture()
def bootstrap():
    def _call(client, frameworks=("ISO-27001", "PCI-DSS")):
        return _bootstrap(client, frameworks)
    return _call


@pytest.fixture()
def upload():
    return _upload
