"""Seed a demo organisation with real evidence from D:\\GRC\\unc, then print the
identity to sign into the frontend with.

Requires a running backend (`uvicorn app.main:app`). Uses the real HTTP API end
to end — no direct DB writes — so it's exactly what the frontend itself would do.

    python scripts/seed_demo.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

BASE = "http://localhost:8000"
REPO_ROOT = Path(__file__).resolve().parent.parent
UNC = REPO_ROOT / "unc"
POLICY_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "access_control_policy_v1.txt"

# (path, artefact_type, mime) — the real PCI ASV scan reports found in D:\GRC\unc,
# plus the repo's own realistic access-control policy fixture for POLICY coverage.
UPLOADS: list[tuple[Path, str, str]] = [
    (POLICY_FIXTURE, "POLICY", "text/plain"),
    *(
        (p, "SCAN_REPORT", "application/pdf")
        for p in sorted(UNC.glob("**/*.pdf"))
    ),
]


def post(path: str, **kwargs) -> dict:
    resp = requests.post(f"{BASE}{path}", timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


def get(path: str, **kwargs) -> dict:
    resp = requests.get(f"{BASE}{path}", timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    try:
        requests.get(f"{BASE}/health/live", timeout=5).raise_for_status()
    except requests.RequestException:
        print(f"backend not reachable at {BASE} — start it first: uvicorn app.main:app")
        return 1

    missing = [p for p, _, _ in UPLOADS if not p.exists()]
    if missing:
        print("missing expected file(s):", *missing, sep="\n  ")
        return 1

    print("=== creating demo organisation ===")
    org = post("/admin/organizations", json={
        "name": "Aurionpro Singapore", "frameworks": ["ISO-27001", "PCI-DSS"],
    })
    firm = post("/admin/audit-firms", json={"name": "Meridian Assurance LLP"})
    engagement = post("/admin/engagements", json={
        "audit_firm_id": firm["id"], "org_id": org["id"],
        "frameworks": ["ISO-27001", "PCI-DSS"],
    })
    headers = {"Authorization": f"org:{org['id']}"}
    print(f"  org id:         {org['id']}")
    print(f"  engagement id:  {engagement['id']}")

    print("\n=== uploading real evidence ===")
    evidence_ids = []
    for path, artefact_type, mime in UPLOADS:
        with path.open("rb") as fh:
            result = post(
                "/evidence",
                params={"artefact_type": artefact_type},
                headers=headers,
                files={"file": (path.name, fh, mime)},
            )
        evidence_ids.append(result["evidence_id"])
        print(f"  {path.name:45} -> {result['evidence_id']}  ({artefact_type})")

    print("\n=== waiting for extraction + evaluation to finish ===")
    for evidence_id in evidence_ids:
        for _ in range(60):
            status = get(f"/evidence/{evidence_id}/status", headers=headers)
            if status["status"] in {"READY", "FAILED", "NEEDS_REVIEW"}:
                print(f"  {evidence_id} -> {status['status']}")
                break
            time.sleep(1)
        else:
            print(f"  {evidence_id} -> still processing after 60s, moving on")

    reuse = get("/analytics/reuse", headers=headers)
    readiness = get("/analytics/readiness", headers=headers)
    print("\n=== reuse & readiness ===")
    print(f"  reuse rate:       {reuse['reuse_rate'] * 100:.0f}%  "
          f"({reuse['avoided_uploads']} uploads avoided, {reuse['effort_hours_saved']}h saved)")
    for fw in readiness:
        print(f"  {fw['framework']:12} readiness {fw['readiness'] * 100:.0f}%  "
              f"({fw['satisfied']}/{fw['total_requirements']} satisfied)")

    print("\n" + "=" * 70)
    print("Sign into the frontend (http://localhost:5173) with:")
    print(f"  tab: Organisation   id: {org['id']}")
    print(f"  tab: Auditor        id: {engagement['id']}   (to review and lock controls)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
