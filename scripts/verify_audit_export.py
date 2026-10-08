"""Verify an exported audit chain and a checkpoint offline, without trusting the platform.

    python scripts/verify_audit_export.py audit-events.ndjson audit-checkpoint-42.json \\
        --public-key <base64 from GET /audit/checkpoint-keys>

Self-contained on purpose: the Python standard library plus `cryptography`, and none of the
platform's code. It recomputes every hash in the chain from the exported rows, checks the
genesis seal over the rows written before per-tenant chains, checks the checkpoint's signature
with the public key you supply, and checks the event the checkpoint certifies is still there,
unchanged. Exit 0 when everything holds, 1 with the reasons when anything does not (ADR-023).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

CONTENT_FIELDS = ("actor", "action", "entity_type", "entity", "org_id", "detail", "before", "after", "reason")


def _digest(prev_hash: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{prev_hash}{body}".encode()).hexdigest()


def _content(e: dict) -> dict:
    return {k: e[k] for k in CONTENT_FIELDS}


def _seal(rows: list[dict]) -> str:
    h = hashlib.sha256()
    for e in rows:
        h.update(json.dumps({**_content(e), "id": e["id"], "at": e["at"]}, sort_keys=True, default=str).encode())
    return h.hexdigest()


def verify_chain(events: list[dict]) -> list[str]:
    chained = sorted((e for e in events if e["chain_seq"] is not None), key=lambda e: e["chain_seq"])
    legacy = [e for e in events if e["chain_seq"] is None]
    if not chained:
        return ["the export has no chained events"]
    problems, prev_hash = [], ""
    for expected, e in enumerate(chained, start=1):
        payload = {**_content(e), "v": 2, "chain": e["chain"], "chain_seq": e["chain_seq"], "at": e["at"]}
        if e["chain_seq"] != expected:
            return [f"event {expected} is missing"]
        if e["prev_hash"] != prev_hash or e["entry_hash"] != _digest(prev_hash, payload):
            return [f"event {expected} does not hash to its recorded value"]
        prev_hash = e["entry_hash"]
    genesis = chained[0]
    if genesis["action"] != "CHAIN_GENESIS":
        return ["the chain does not start with its genesis event"]
    until = genesis["detail"]["legacy_until"]
    sealed = sorted((e for e in legacy if e["at"] <= until), key=lambda e: (e["seq"], e["id"]))
    if len(sealed) != genesis["detail"]["legacy_events"] or _seal(sealed) != genesis["detail"]["legacy_digest"]:
        problems.append("events from before the chain no longer match its genesis seal")
    return problems


def verify_checkpoint(events: list[dict], checkpoint: dict, public_key_b64: str) -> list[str]:
    body = {k: v for k, v in checkpoint.items() if k != "signature"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        key.verify(base64.b64decode(checkpoint["signature"]["value"]), canonical)
    except (InvalidSignature, ValueError, KeyError):
        return ["the checkpoint's signature does not verify with this public key"]
    by_seq = {e["chain_seq"]: e for e in events if e["chain_seq"] is not None}
    event = by_seq.get(checkpoint["chain_seq"])
    if event is None:
        return [f"event {checkpoint['chain_seq']} the checkpoint certifies is not in the export"]
    if event["entry_hash"] != checkpoint["head_hash"]:
        return [f"event {checkpoint['chain_seq']} has changed since the checkpoint"]
    genesis = by_seq.get(1, {})
    if genesis.get("entry_hash") != checkpoint["genesis_hash"]:
        return ["the chain was restarted since the checkpoint"]
    # Rows the previous code wrote after genesis, during a deploy: covered by digest.
    unchained, after = checkpoint["unchained"], genesis["detail"]["legacy_until"]
    rows = sorted((e for e in events if e["chain_seq"] is None and after < e["at"]
                   and unchained["until"] is not None and e["at"] <= unchained["until"]),
                  key=lambda e: (e["seq"], e["id"]))
    if len(rows) != unchained["count"] or _seal(rows) != unchained["digest"]:
        return ["events written outside the chain during a deploy have changed since the checkpoint"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("events", help="audit-events.ndjson from GET /audit/events.ndjson")
    parser.add_argument("checkpoint", nargs="?", help="a checkpoint JSON file you kept")
    parser.add_argument("--public-key", help="base64 Ed25519 public key from GET /audit/checkpoint-keys")
    args = parser.parse_args(argv)
    with open(args.events, encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh if line.strip()]
    problems = verify_chain(events)
    if args.checkpoint:
        if not args.public_key:
            parser.error("--public-key is required to verify a checkpoint")
        with open(args.checkpoint, encoding="utf-8") as fh:
            problems += verify_checkpoint(events, json.load(fh), args.public_key)
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"OK: {sum(1 for e in events if e['chain_seq'] is not None)} chained events verify"
              + (" and the checkpoint holds" if args.checkpoint else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
