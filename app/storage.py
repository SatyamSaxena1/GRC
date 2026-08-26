"""Evidence object storage behind one interface.

Local disk by default so the slice runs with no infrastructure; S3/MinIO when
STORAGE_BACKEND=s3. Evidence versions are immutable — put() refuses to overwrite
an existing key, which is the storage-level half of the versioning guarantee.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


def object_key(org_id: str, evidence_id: str, version: int, filename: str) -> str:
    return f"tenant/{org_id}/evidence/{evidence_id}/v{version}/{filename}"


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def url(self, key: str, expires_s: int = 900) -> str: ...


class LocalStorage:
    def __init__(self, root: str | None = None):
        self.root = Path(root or os.environ.get("EVIDENCE_STORAGE_DIR", "./evidence_storage"))

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        if path.exists():
            raise FileExistsError(f"evidence objects are immutable; {key} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def url(self, key: str, expires_s: int = 900) -> str:
        # ponytail: local files have no signed URL; callers stream via the API instead.
        return f"file://{self._path(key).resolve()}"


class S3Storage:
    def __init__(self, bucket: str | None = None, endpoint_url: str | None = None):
        import boto3

        self.bucket = bucket or os.environ["S3_BUCKET"]
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or os.environ.get("S3_ENDPOINT_URL"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )

    def put(self, key: str, data: bytes) -> str:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
            return key
        raise FileExistsError(f"evidence objects are immutable; {key} already exists")

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def url(self, key: str, expires_s: int = 900) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_s
        )


def get_storage() -> Storage:
    if os.environ.get("STORAGE_BACKEND", "local").lower() == "s3":
        return S3Storage()
    return LocalStorage()
