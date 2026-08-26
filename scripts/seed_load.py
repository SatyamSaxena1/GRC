"""Create a realistic synthetic workload for the local GRC frontend.

Uses the public HTTP API end to end, so tenancy, uploads, background processing,
evaluation, task creation, assignments and role scoping are exercised exactly as
they are from the browser.

    python scripts/seed_load.py
    python scripts/seed_load.py --documents 25 --controls 80 --users 5
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

import requests


def policy_document(index: int) -> bytes:
    """Vary compliance facts so the evaluator produces mixed verdicts/gaps."""
    password_length = (8, 10, 12, 14)[index % 4]
    scope = "Corporate IT and the Cardholder Data Environment (CDE)" if index % 3 else "Corporate IT"
    approval = "Approved by the CISO on 12 March 2026." if index % 5 else "Draft - approval pending."
    return f"""Synthetic Access Control Policy {index + 1:03d}
Document ID: LOAD-{index + 1:03d}
Version: {1 + index // 10}
Effective date: 12 March 2026
Next review date: 12 March 2027
{approval}
Scope: {scope}
Minimum password length: {password_length} characters.
MFA is required for remote and administrative access.
Access rights are reviewed quarterly and removed when no longer required.
This document is synthetic test data generated for the local GRC workspace.
""".encode()


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def request(self, method: str, path: str, **kwargs):
        response = requests.request(method, f"{self.base}{path}", timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--documents", type=int, default=12)
    parser.add_argument("--controls", type=int, default=36)
    parser.add_argument("--users", type=int, default=3)
    parser.add_argument("--wait", action="store_true", help="wait up to three minutes for analysis")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if min(args.documents, args.controls, args.users) < 1:
        raise SystemExit("--documents, --controls and --users must all be positive")

    api = Api(args.base)
    try:
        api.get("/health/live")
    except requests.RequestException:
        print(f"backend not reachable at {args.base} - start uvicorn app.main:app first")
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    org = api.post("/admin/organizations", json={
        "name": f"Synthetic Load Lab {stamp}",
        "frameworks": ["ISO-27001", "PCI-DSS"],
    })
    firm = api.post("/admin/audit-firms", json={"name": f"Load Test Assurance {stamp}"})
    engagement = api.post("/admin/engagements", json={
        "audit_firm_id": firm["id"],
        "org_id": org["id"],
        "frameworks": ["ISO-27001", "PCI-DSS"],
    })
    auth = {"Authorization": f"org:{org['id']}"}
    print(f"organisation: {org['id']}", flush=True)
    print(f"auditor:      {engagement['id']}", flush=True)

    users = [
        api.post("/admin/users", json={
            "email": f"owner{index + 1}.{stamp}@load.test",
            "org_id": org["id"],
            "role": "CONTROL_OWNER",
        })
        for index in range(args.users)
    ]
    print(f"owner:        {users[0]['id']}", flush=True)

    controls = []
    for index in range(args.controls):
        framework = "ISO-27001" if index % 2 == 0 else "PCI-DSS"
        control = api.post("/admin/controls", json={
            "org_id": org["id"], "framework": framework, "clause": f"LOAD-{index + 1:03d}",
        })
        controls.append(control)
        api.post("/admin/control-assignments", json={
            "org_control_id": control["id"], "user_id": users[index % len(users)]["id"],
        })

    evidence_ids = []
    for index in range(args.documents):
        result = api.post(
            "/evidence",
            params={"artefact_type": "POLICY"},
            headers=auth,
            files={"file": (f"synthetic_policy_{index + 1:03d}.txt", policy_document(index), "text/plain")},
        )
        evidence_ids.append(result["evidence_id"])
        print(f"accepted document {index + 1}/{args.documents}", flush=True)

    if args.wait:
        pending = set(evidence_ids)
        deadline = time.monotonic() + 180
        while pending and time.monotonic() < deadline:
            for evidence_id in list(pending):
                status = api.get(f"/evidence/{evidence_id}/status", headers=auth)["status"]
                if status in {"READY", "FAILED", "NEEDS_REVIEW"}:
                    pending.remove(evidence_id)
            if pending:
                time.sleep(1)
        if pending:
            print(f"warning: {len(pending)} document(s) still processing")

    gaps = api.get("/gaps", headers=auth)
    tasks = api.get("/tasks", headers=auth)
    reuse = api.get("/analytics/reuse", headers=auth)

    print("\nSynthetic workload ready")
    print(f"  organisation: {org['id']}")
    print(f"  auditor:      {engagement['id']}")
    print(f"  owner:        {users[0]['id']}")
    print(f"  documents:    {len(evidence_ids)}")
    print(f"  controls:     {len(controls)} synthetic + evaluated framework controls")
    print(f"  gaps/tasks:   {len(gaps)}/{len(tasks)}")
    print(f"  reuse links:  {reuse['total_links']}")
    print("\nSign in at http://localhost:5173 using the ids above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
