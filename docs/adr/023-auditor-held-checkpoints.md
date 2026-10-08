# ADR-023: Auditor-held signed checkpoints of the audit chain, verifiable offline

> **Status:** Proposed. The external-anchor idea from the earlier Trishul attempt, held by the
> auditor rather than an object-lock bucket.

## Context
The audit trail is hash-chained per tenant and append-only in the database. That defends against
a careless edit, but not against whoever controls the database: they can rewrite the trail and
recompute every hash, and the chain will still verify. A chain only proves something against a
copy of its head held somewhere the platform cannot reach.

Trishul published tenant heads hourly to an S3 Object Lock bucket in a separate AWS account. It
worked, but its checkpoints carried no position, no event count and no signature, and nothing
flagged a tenant missing from one. It also needed infrastructure this deployment does not have.
This product's own pitch says the auditor, not the vendor, holds the record of what was approved
(docs/product/change-control-evidence.md).

## Decision
**The auditor takes and keeps the checkpoints.**

- `POST /audit/checkpoints` (an auditor acting under an engagement) returns a JSON file. It holds
  the format, the issuer, the organisation, its chain, the head's position (`chain_seq`) and
  hash, the event count, the genesis hash, the previous checkpoint's position and hash, and the
  creation time. It is **signed with Ed25519** over its canonical JSON.
  - Issuing refuses a chain that does not verify (409), because certifying a broken chain would
    launder it.
  - With no key configured it refuses (503) rather than issuing an unsigned checkpoint, since an
    unsigned file proves nothing about who issued it.
  - Each checkpoint is itself recorded in the chain as `AUDIT_CHECKPOINT_ISSUED`.
- `POST /audit/checkpoints/verify` (either side) checks:
  - the signature;
  - that the checkpoint belongs to this organisation;
  - that the certified event is still at its position with the same hash;
  - that the genesis is unchanged;
  - that the whole chain still verifies.

  So anything at or before the checkpoint that was edited, inserted or deleted is caught, unless
  the signing key itself was used to forge a new checkpoint. That is exactly what holding the old
  one defeats.
- **Offline verification.** `GET /audit/events.ndjson` exports the chain (plus the pre-chain rows
  its genesis sealed), and `GET /audit/checkpoint-keys` publishes the public keys.
  `scripts/verify_audit_export.py` uses only the standard library and `cryptography`. It
  recomputes every hash and checks a checkpoint, so an auditor needn't run or trust any platform
  code.
- **Keys.** `AUDIT_CHECKPOINT_SIGNING_KEY` holds the base64 of the raw 32-byte Ed25519 private
  key, set as a secret on each service. Rotate by moving the old *public* key into
  `AUDIT_CHECKPOINT_RETIRED_KEYS`, so old checkpoints still verify.
- The **Activity** page shows the chain's status, and lets an auditor download a checkpoint or
  export the chain, and anyone verify a checkpoint file.

## Consequences
- Protection covers what precedes the latest checkpoint an auditor holds. Events after it are
  covered only by the database's append-only trigger, so auditors should take one at milestones
  (fieldwork start, each lock session, engagement close).
- A lost signing key means new checkpoints need a new key. Old ones still verify against the
  published public key.
- Nothing new runs on a schedule. A scheduled public anchor (for example a protected Git branch)
  remains possible later, and would complement this rather than replace it.
