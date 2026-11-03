"""Seed a demo organisation for the "who owns the AI decision" demo, then print the
identities to sign in with.

    python scripts/seed_ai_demo.py [--base http://localhost:8000]

What it leaves behind, all through the real HTTP API (no direct DB writes):
  1. Asteron's AI governance policy, version 1, then version 2 uploaded as a new version
     (the ai-policy-asteron samples in frontend/src/demo/samples.json, so the demo panel
     and this script upload the very same text);
  2. a GitHub change-control snapshot whose AI-reviewed merges are the "AI code review"
     evidence, if the backend has DPDP_GITHUB_COLLECTOR_URL configured (skipped otherwise);
  3. one verdict locked by the auditor (NIST AI RMF GOVERN 2.1: roles and escalation);
  4. an auditor checkpoint of the audit chain, saved next to this run's output, if the
     backend has AUDIT_CHECKPOINT_SIGNING_KEY set.

Needs stub auth (local/dev). Version 2's verdicts depend on the model reading the
document; the samples' `expect` blocks say what a correct reading produces.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evaluation import samples as lib  # noqa: E402

FRAMEWORKS = ["NIST-AI-RMF", "ISO-27001", "SOC-2"]
LOCK_CLAUSE = ("NIST-AI-RMF", "GOVERN 2.1")


class Api:
    def __init__(self, base: str, admin_key: str | None):
        self.base = base.rstrip("/")
        self.admin = {"X-Admin-Key": admin_key} if admin_key else {}

    def call(self, method: str, path: str, auth: str | None = None, ok=(200, 201, 202), **kw):
        headers = {**kw.pop("headers", {}), **({"Authorization": auth} if auth else {})}
        resp = requests.request(method, f"{self.base}{path}", headers=headers, timeout=60, **kw)
        if resp.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp


def wait_ready(api: Api, org: str, evidence_id: str, timeout_s: int = 300) -> str:
    for _ in range(timeout_s // 2):
        status = api.call("GET", f"/evidence/{evidence_id}/status", org).json()["status"]
        if status in {"READY", "FAILED", "NEEDS_REVIEW"}:
            return status
        time.sleep(2)
    return "STILL_PROCESSING"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--admin-key", help="X-Admin-Key, when the backend sets ADMIN_API_KEY")
    ap.add_argument("--out", default=".", help="where to save the auditor checkpoint")
    args = ap.parse_args()
    api = Api(args.base, args.admin_key)
    api.call("GET", "/health/live")

    samples = {s["id"]: s for s in lib.load()["samples"]}
    runid = uuid.uuid4().hex[:6]
    v1, v2 = (lib.render(samples[i], date.today(), runid) for i in ("ai-policy-asteron", "ai-policy-asteron-v2"))

    print("=== organisation, audit firm, engagement ===")
    org = api.call("POST", "/admin/organizations", headers=api.admin,
                   json={"name": "Asteron Systems (demo)", "frameworks": FRAMEWORKS}).json()
    firm = api.call("POST", "/admin/audit-firms", headers=api.admin, json={"name": "Meridian Assurance LLP"}).json()
    engagement = api.call("POST", "/admin/engagements", headers=api.admin, json={
        "audit_firm_id": firm["id"], "org_id": org["id"], "frameworks": FRAMEWORKS}).json()
    as_org, as_auditor = f"org:{org['id']}", f"auditor:{engagement['id']}"

    print("=== AI policy v1, then v2 as a new version ===")
    files = lambda s: {"file": (s["filename"], "\n".join(s["body"]) + "\n", "text/plain")}  # noqa: E731
    first = api.call("POST", "/evidence", as_org, params={"artefact_type": "AI_POLICY"}, files=files(v1)).json()
    print(f"  v1 {first['evidence_id']} -> {wait_ready(api, as_org, first['evidence_id'])}")
    second = api.call("POST", f"/evidence/{first['evidence_id']}/versions", as_org,
                      params={"artefact_type": "AI_POLICY"}, files=files(v2)).json()
    v2_id = second["evidence_id"]
    print(f"  v2 {v2_id} -> {wait_ready(api, as_org, v2_id)}")

    print("=== AI code review evidence (GitHub change control) ===")
    resp = api.call("POST", "/connectors/github/sync", as_org, ok=(202, 409, 502))
    print("  synced" if resp.status_code == 202 else f"  skipped: {resp.json().get('detail')}")

    print("=== auditor locks a verdict ===")
    links = api.call("GET", f"/evidence/{v2_id}/evaluations", as_auditor).json()
    link = next((l for l in links if (l["framework"], l["clause"]) == LOCK_CLAUSE), None)
    if link is None or link["verdict"] != "PASS":
        print(f"  skipped: {LOCK_CLAUSE[1]} is {link and link['verdict']} (the model may have missed a fact)")
    else:
        api.call("POST", f"/audit/links/{link['id']}/lock", as_auditor, json={
            "verdict": "PASS", "reason": "Roles and escalation path reviewed against policy v2"})
        print(f"  locked {LOCK_CLAUSE[1]} on v2")

    print("=== auditor checkpoint ===")
    resp = api.call("POST", "/audit/checkpoints", as_auditor, ok=(200, 503))
    if resp.status_code == 200:
        out = Path(args.out) / f"asteron-checkpoint-{runid}.json"
        out.write_text(resp.text, encoding="utf-8")
        print(f"  saved {out}")
    else:
        print(f"  skipped: {resp.json().get('detail')}")

    print("\n" + "=" * 70)
    print(f"Organisation id: {org['id']}   (login tab: Organisation)")
    print(f"Auditor id:      {engagement['id']}   (login tab: Auditor)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
