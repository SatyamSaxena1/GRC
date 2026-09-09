"""Live pipeline events and gap remediation drafting.

The event stream is a *preview* of work that gets persisted anyway — so the
tests that matter are about it never becoming load-bearing: it is authorized
like every other read, it closes itself, and a finished run doesn't leave a
client hanging.
"""

from __future__ import annotations

import threading

from app import events


# ------------------------------------------------------------------ event bus


def test_subscriber_receives_published_events_then_stops_on_done():
    received = []

    def watch():
        for event, data in events.subscribe("evidence-1"):
            received.append((event, data))

    t = threading.Thread(target=watch)
    t.start()
    # wait until the subscriber has registered before publishing
    for _ in range(200):
        if events.has_subscribers("evidence-1"):
            break
    events.publish("evidence-1", "status", {"status": "ANALYZING"})
    events.publish("evidence-1", "attribute", {"name": "password_min_length"})
    events.publish("evidence-1", "done", {})
    t.join(timeout=5)

    assert [e for e, _ in received] == ["status", "attribute", "done"]
    assert not events.has_subscribers("evidence-1"), "subscriber must deregister on done"


def test_publishing_with_nobody_watching_is_a_no_op():
    """The pipeline publishes unconditionally; nothing may blow up when the
    browser has gone away."""
    events.publish("nobody-here", "status", {"status": "READY"})
    assert not events.has_subscribers("nobody-here")


# ------------------------------------------------------------------ endpoints


def test_event_stream_is_scoped_to_the_owning_org(client, bootstrap, upload):
    org_a, _ = bootstrap(client)
    org_b, _ = bootstrap(client)
    evidence_id = upload(client, org_a).json()["evidence_id"]

    denied = client.get(f"/evidence/{evidence_id}/events",
                        headers={"authorization": f"org:{org_b}"})
    assert denied.status_code == 404  # existence itself is not leaked


def test_stream_closes_immediately_for_an_already_finished_run(client, bootstrap, upload):
    """A client opening the stream after processing ended must get the final
    status and a done, not hang waiting for events that will never come."""
    org_id, _ = bootstrap(client)
    evidence_id = upload(client, org_id).json()["evidence_id"]

    body = client.get(f"/evidence/{evidence_id}/events",
                      headers={"authorization": f"org:{org_id}"}).text
    assert "event: status" in body
    assert "event: done" in body


def test_remediation_draft_is_scoped_and_never_writes(client, bootstrap, upload):
    org_a, _ = bootstrap(client)
    org_b, _ = bootstrap(client)
    upload(client, org_a)

    gaps = client.get("/gaps?status=OPEN", headers={"authorization": f"org:{org_a}"}).json()
    assert gaps, "extraction is unavailable in tests, so gaps are expected"
    gap = gaps[0]

    denied = client.post(f"/gaps/{gap['id']}/draft-remediation",
                         headers={"authorization": f"org:{org_b}"})
    assert denied.status_code == 404

    ok = client.post(f"/gaps/{gap['id']}/draft-remediation",
                     headers={"authorization": f"org:{org_a}"})
    assert ok.status_code == 200
    body = ok.json()
    assert set(body) == {"draft", "evidence_needed"}
    # No model configured in tests -> empty draft, never an error and never a guess
    assert body["draft"] == ""

    after = client.get("/gaps?status=OPEN", headers={"authorization": f"org:{org_a}"}).json()
    assert [g["id"] for g in after] == [g["id"] for g in gaps], "drafting must not change the record"
    assert after[0]["status"] == "OPEN", "drafting must never close a gap"
