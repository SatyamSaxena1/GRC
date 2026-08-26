"""Exercises S3Storage against a real MinIO container — named in the README's
Known Limitations as untested ("MinIO/S3 storage is written but never run").
Skipped automatically unless MinIO is reachable, so CI stays green without
docker — bring it up and run this before trusting the S3 path.

    docker compose up -d minio createbuckets
    pytest tests/test_storage_s3.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.storage import S3Storage

ENDPOINT = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")
BUCKET = os.environ.get("S3_BUCKET", "grc-evidence")
ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin")
SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin")


def _minio_reachable() -> bool:
    try:
        import boto3
        from botocore.config import Config

        boto3.client(
            "s3", endpoint_url=ENDPOINT, aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY, region_name="us-east-1",
            config=Config(connect_timeout=1, retries={"max_attempts": 0}),
        ).list_buckets()
        return True
    except Exception:  # noqa: BLE001 - any connectivity failure means "skip", not "fail"
        return False


pytestmark = pytest.mark.skipif(not _minio_reachable(), reason=f"MinIO not reachable at {ENDPOINT}")


@pytest.fixture()
def storage(monkeypatch):
    # S3Storage always reads credentials from env (see storage.py) — the
    # constructor only takes bucket/endpoint_url — so these must be set here
    # even though _minio_reachable() above already proved the credentials work.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", ACCESS_KEY)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET_KEY)
    return S3Storage(bucket=BUCKET, endpoint_url=ENDPOINT)


def test_put_get_roundtrip(storage):
    key = f"test/{uuid.uuid4()}/object.txt"
    storage.put(key, b"hello minio")
    assert storage.get(key) == b"hello minio"


def test_put_refuses_to_overwrite_an_existing_key(storage):
    """The storage-level half of evidence-version immutability (see storage.py
    docstring) — must hold against a real bucket, not only LocalStorage."""
    key = f"test/{uuid.uuid4()}/object.txt"
    storage.put(key, b"v1")
    with pytest.raises(FileExistsError):
        storage.put(key, b"v2")
    assert storage.get(key) == b"v1"  # the refused write must not have landed


def test_url_returns_a_working_presigned_url(storage):
    import requests

    key = f"test/{uuid.uuid4()}/object.txt"
    storage.put(key, b"presigned check")
    url = storage.url(key, expires_s=60)
    assert url.startswith("http")

    resp = requests.get(url, timeout=5)
    assert resp.status_code == 200
    assert resp.content == b"presigned check"


def test_evidence_upload_pipeline_runs_against_real_minio(client, bootstrap, monkeypatch):
    """The endpoint-level path, not just the Storage protocol directly — proves
    process_evidence's storage.get()/put() calls actually work against MinIO."""
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setenv("S3_ENDPOINT_URL", ENDPOINT)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", ACCESS_KEY)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET_KEY)

    org_id, _ = bootstrap(client)
    resp = client.post("/evidence", headers={"authorization": f"org:{org_id}"},
                       params={"artefact_type": "POLICY"},
                       files={"file": ("policy.txt", b"an access control policy", "text/plain")})
    assert resp.status_code == 202
    evidence_id = resp.json()["evidence_id"]

    status = client.get(f"/evidence/{evidence_id}/status",
                        headers={"authorization": f"org:{org_id}"}).json()
    assert status["status"] in {"READY", "NEEDS_REVIEW"}  # reached a terminal state, not FAILED
