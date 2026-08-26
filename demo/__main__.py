"""The whole slice, end to end, printed step by step.

    python -m demo

Runs against a throwaway SQLite database and storage directory so it is safe to
re-run. Uses the real API, the real pipeline, and the real model when Ollama is
available — nothing here is simulated.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

WORKDIR = Path(tempfile.mkdtemp(prefix="grc-demo-"))
os.environ["DATABASE_URL"] = f"sqlite:///{WORKDIR / 'demo.db'}"
os.environ["EVIDENCE_STORAGE_DIR"] = str(WORKDIR / "storage")

from fastapi.testclient import TestClient  # noqa: E402

from app import db as db_module  # noqa: E402
from app.ai.ollama import OllamaGateway  # noqa: E402
from app.main import app  # noqa: E402

POLICY_V1 = Path("tests/fixtures/access_control_policy_v1.txt")
step_number = 0


def step(title: str) -> None:
    global step_number
    step_number += 1
    print(f"\n{step_number:2}. {title}")


def show(label: str, value) -> None:
    print(f"      {label:28} {value}")


def main() -> int:
    from sqlalchemy import create_engine

    db_module.engine = create_engine(os.environ["DATABASE_URL"])

    gateway = OllamaGateway()
    print("=" * 78)
    print("GRC thin vertical slice — end-to-end demonstration")
    print("=" * 78)
    show("model", f"{gateway.model or 'unconfigured'} "
                  f"({'available' if gateway.available() else 'UNAVAILABLE — expect null extraction'})")
    show("workdir", WORKDIR)

    with TestClient(app) as client:
        step("Create the auditee tenant, subscribed to ISO 27001 and PCI DSS")
        org = client.post("/admin/organizations", json={
            "name": "Asteron Systems Pvt. Ltd.", "frameworks": ["ISO-27001", "PCI-DSS"],
        }).json()
        auditee = {"authorization": f"org:{org['id']}"}
        show("organization", org["id"])

        step("Create the audit firm and an engagement scoped to both frameworks")
        firm = client.post("/admin/audit-firms", json={"name": "Meridian Assurance LLP"}).json()
        engagement = client.post("/admin/engagements", json={
            "audit_firm_id": firm["id"], "org_id": org["id"],
            "frameworks": ["ISO-27001", "PCI-DSS"],
        }).json()
        auditor = {"authorization": f"auditor:{engagement['id']}"}
        show("engagement", engagement["id"])

        step("Upload the access control policy (V1)")
        response = client.post("/evidence", headers=auditee,
                               files={"file": (POLICY_V1.name, POLICY_V1.read_bytes(), "text/plain")})
        v1 = response.json()["evidence_id"]
        show("http status", f"{response.status_code} (accepted, processing in background)")

        detail = client.get(f"/evidence/{v1}", headers=auditee).json()
        show("sha256", detail["sha256"])
        show("stored as", f"tenant/{org['id']}/evidence/{v1}/v1/...")
        show("status", detail["status"])

        step("Duplicate upload is rejected by content hash")
        duplicate = client.post("/evidence", headers=auditee,
                                files={"file": ("copy.txt", POLICY_V1.read_bytes(), "text/plain")})
        show("http status", f"{duplicate.status_code} (already uploaded)")

        step("Malformed upload is rejected at the trust boundary")
        bad = client.post("/evidence", headers=auditee,
                          files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")})
        show("http status", f"{bad.status_code} — {bad.json()['detail']}")

        step("Extracted attributes, each with page-level provenance")
        for attribute in client.get(f"/evidence/{v1}/attributes", headers=auditee).json():
            if attribute["value"] is None:
                continue
            pages = ", ".join(str(s["page"]) for s in attribute["sources"] if s.get("page"))
            show(attribute["name"], f"{attribute['value']!r}  [page {pages or '?'}]")

        step("Deterministic evaluation — same evidence, both frameworks, independently")
        links = client.get(f"/evidence/{v1}/evaluations", headers=auditee).json()
        for link in sorted(links, key=lambda l: (l["framework"], l["clause"])):
            show(f"{link['framework']} {link['clause']}", link["verdict"])

        step("Gaps carry the actual value, the required value, and what to do")
        for gap in client.get("/gaps", headers=auditee).json():
            if gap["status"] != "OPEN":
                continue
            print(f"      {gap['framework']} {gap['clause']} — {gap['attribute']}")
            print(f"        actual={gap['actual_value']!r} required={gap['required_value']!r}")
            print(f"        action: {gap['required_action']}")

        step("A remediation task exists for every gap")
        tasks = client.get("/tasks", headers=auditee).json()
        show("open tasks", len([t for t in tasks if t["status"] == "OPEN"]))

        step("Reuse analytics — one upload, many controls")
        reuse = client.get("/analytics/reuse", headers=auditee).json()
        show("evidence artefacts", reuse["distinct_evidence"])
        show("control links created", reuse["total_links"])
        show("uploads avoided", reuse["avoided_uploads"])
        show("evidence reuse rate", f"{reuse['reuse_rate'] * 100:.0f}%")
        show("effort saved", f"{reuse['effort_hours_saved']} hours")

        step("Control owner least privilege")
        user = client.post("/admin/users", json={
            "email": "owner@asteron.test", "org_id": org["id"], "role": "CONTROL_OWNER",
        }).json()
        controls = client.get("/controls", headers=auditee).json()
        assigned = next(c for c in controls if c["clause"] == "A.5.15")
        unassigned = next(c for c in controls if c["clause"] == "8.3.6")
        client.post("/admin/control-assignments",
                    json={"org_control_id": assigned["id"], "user_id": user["id"]})
        owner = {"authorization": f"user:{user['id']}"}
        assigned_status = client.get("/controls/" + assigned["id"], headers=owner).status_code
        unassigned_status = client.get("/controls/" + unassigned["id"], headers=owner).status_code
        show("assigned control", f"GET -> {assigned_status}")
        show("unassigned control", f"GET -> {unassigned_status} (invisible, not merely read-only)")
        show("controls listed", len(client.get("/controls", headers=owner).json()))

        step("Day-1 readiness for a framework not yet subscribed")
        solo = client.post("/admin/organizations", json={
            "name": "ISO-only Ltd.", "frameworks": ["ISO-27001"],
        }).json()
        solo_headers = {"authorization": f"org:{solo['id']}"}
        client.post("/evidence", headers=solo_headers,
                    files={"file": (POLICY_V1.name, POLICY_V1.read_bytes(), "text/plain")})
        ready = client.get("/analytics/readiness/PCI-DSS", headers=solo_headers).json()
        show("organisation", "subscribed to ISO 27001 only")
        show("PCI DSS readiness today", f"{ready['readiness'] * 100:.0f}% "
                                        f"({ready['satisfied']}/{ready['total_requirements']} satisfied)")
        for clause in ready["clauses"]:
            show(f"  PCI {clause['clause']}", clause["verdict"])

        step("Upload the corrected policy (V2)")
        corrected = POLICY_V1.read_text(encoding="utf-8").replace(
            "Minimum password length: 8 characters.",
            "Minimum password length: 14 characters.",
        ).replace(
            "Scope note: this version does not expressly identify or include a Cardholder Data Environment (CDE)\nor payment-processing infrastructure.",
            "Scope note: this version expressly includes the Cardholder Data Environment (CDE)\nand payment-processing infrastructure.",
        )
        v2 = client.post(f"/evidence/{v1}/versions", headers=auditee,
                         files={"file": ("access_control_policy_v2.txt",
                                         corrected.encode(), "text/plain")}).json()["evidence_id"]

        lineage = client.get(f"/evidence/{v2}/versions", headers=auditee).json()
        for version in lineage:
            show(f"version {version['version']}", f"{version['lifecycle_status']} ({version['id'][:8]})")

        step("V2 re-evaluated; V1 remains permanently retrievable")
        v2_links = client.get(f"/evidence/{v2}/evaluations", headers=auditee).json()
        for link in sorted(v2_links, key=lambda l: (l["framework"], l["clause"])):
            show(f"{link['framework']} {link['clause']}", link["verdict"])

        step("Gaps resolved by the new evidence — history retained, not deleted")
        resolved = [g for g in client.get("/gaps", headers=auditee).json()
                    if g["status"] == "RESOLVED_BY_EVIDENCE"]
        show("resolved gaps", len(resolved))
        for gap in resolved[:4]:
            show(f"  {gap['clause']} {gap['attribute']}", f"resolved by {gap['resolved_by_evidence_id'][:8]}")

        step("Auditor reviews and records a COMPLIANT verdict")
        target = next(l for l in v2_links if l["clause"] == "A.5.15")
        verdict = client.post(f"/audit/links/{target['id']}/verdict", headers=auditor,
                              json={"verdict": "COMPLIANT", "reason": "evidence reviewed"}).json()
        show("auditor verdict", verdict["auditor_verdict"])
        show("control locked", verdict["locked"])

        step("Auditee can no longer modify the locked control")
        control = next(c for c in client.get("/controls", headers=auditee).json()
                       if c["clause"] == "A.5.15")
        blocked = client.post(f"/controls/{control['id']}/submit", headers=auditee)
        show("http status", f"{blocked.status_code} — {blocked.json()['detail']}")

        step("Upload V3 after the lock — the locked verdict is untouched")
        client.post(f"/evidence/{v2}/versions", headers=auditee,
                    files={"file": ("v3.txt", (corrected + "\nMinor clarification.\n").encode(),
                                    "text/plain")})
        after = client.get(f"/evidence/{v2}/evaluations", headers=auditee).json()
        still_locked = next(l for l in after if l["clause"] == "A.5.15")
        show("verdict after V3", f"{still_locked['verdict']} (locked={still_locked['locked']})")

        step("The auditor is notified that evidence changed after the lock")
        history = client.get(f"/evidence/{v2}/history", headers=auditee).json()
        for event in history:
            if event["action"] == "EVIDENCE_CHANGED_AFTER_LOCK":
                show("event", f"{event['action']} on {event['detail']['clause']}")

        step("Cross-tenant isolation")
        other = client.post("/admin/organizations",
                            json={"name": "Unrelated Corp", "frameworks": []}).json()["id"]
        show("other tenant reads evidence",
             f"{client.get(f'/evidence/{v1}', headers={'authorization': f'org:{other}'}).status_code} (not found)")

        step("Closing the engagement revokes auditor access immediately")
        client.post(f"/admin/engagements/{engagement['id']}/close")
        show("auditor reads evidence",
             f"{client.get(f'/evidence/{v1}', headers=auditor).status_code} (not found)")

        step("The full history is queryable and hash-chained")
        from sqlalchemy.orm import Session
        from app.audit_log import verify_chain
        with Session(db_module.engine) as db:
            show("audit chain intact", verify_chain(db))
        for event in client.get(f"/evidence/{v1}/history", headers=auditee).json():
            show(event["at"][:19], f"{event['action']} by {event['actor'][:24]}")

    print("\n" + "=" * 78)
    print("Demo complete.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(WORKDIR, ignore_errors=True)
