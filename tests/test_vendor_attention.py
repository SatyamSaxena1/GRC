"""Vendor reviews in the daily attention list (issue 83): overdue ones surface in-app; chat gets a count, no names."""

from __future__ import annotations

from app.routers.notifications import CONTENT, _attention_items
from app import monitor

H = lambda org: {"authorization": f"org:{org}"}  # noqa: E731


def _report(client, org, db):
    return monitor.attention_report(db, org, CONTENT).to_dict()


def test_a_never_reviewed_vendor_is_listed_and_a_reviewed_one_is_not(client, bootstrap, db):
    org, _ = bootstrap(client)
    client.post("/vendors", json={"name": "Stripe", "service": "Payments", "data_access": "SENSITIVE",
                                  "criticality": "HIGH"}, headers=H(org))
    v2 = client.post("/vendors", json={"name": "Slackish", "service": "Chat", "data_access": "NONE",
                                       "criticality": "LOW"}, headers=H(org)).json()
    assert client.post(f"/vendors/{v2['id']}/review", json={"note": "checked access scope, contract terms and the security report"},
                       headers=H(org)).status_code == 200

    report = _report(client, org, db)
    assert [v["title"] for v in report["vendors"]] == ["Stripe"]
    assert report["total"] >= 1

    in_app = [i for i in _attention_items(report, report["checked_at"]) if i["kind"] == "VENDOR_REVIEW"]
    assert in_app[0]["message"].startswith("Stripe") and in_app[0]["link"] == "/vendors"

    chat = [i for i in _attention_items(report, report["checked_at"], names=False) if i["kind"] == "VENDOR_REVIEW"]
    assert len(chat) == 1 and "Stripe" not in chat[0]["message"] and chat[0]["message"].startswith("1 vendor")


def test_an_offboarded_vendor_needs_no_review(client, bootstrap, db):
    org, _ = bootstrap(client)
    v = client.post("/vendors", json={"name": "Old", "service": "x", "data_access": "NONE", "criticality": "LOW"},
                    headers=H(org)).json()
    client.patch(f"/vendors/{v['id']}", json={"status": "OFFBOARDED"}, headers=H(org))
    assert _report(client, org, db)["vendors"] == []
