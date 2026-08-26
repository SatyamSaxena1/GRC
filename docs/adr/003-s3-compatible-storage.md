# ADR-003: S3-compatible evidence storage behind an interface

## Context
Evidence must be immutable and permanently retrievable: an auditor's opinion is
meaningless if the artefact behind it can change afterwards. Local disk does not
survive a multi-node deployment.

## Decision
A `Storage` protocol (`app/storage.py`) with two implementations: `LocalStorage`
(default, zero infrastructure) and `S3Storage` (MinIO in dev, AWS S3 in production).
Keys are `tenant/{org}/evidence/{id}/v{n}/{filename}`. `put()` refuses to overwrite an
existing key, so immutability is enforced at the storage layer rather than by
convention.

## Alternatives considered
- **Database BLOBs.** Simple, but bloats backups and makes streaming awkward.
- **Direct MinIO SDK calls.** Ties business logic to one vendor.

## Consequences
- Tenant is in the key path, so a bucket policy can enforce isolation too.
- Signed URLs work on S3; `LocalStorage.url()` returns a `file://` path, and callers
  must stream through the API instead.
- A new version never overwrites an old one, which is what makes V1 permanently
  retrievable after V2 supersedes it.
