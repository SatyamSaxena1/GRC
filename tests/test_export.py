"""GET /export/compliance.csv — a downloadable audit package, the one thing
Vanta/Drata-style tools are most consistently asked for: something an auditor
or exec can take away instead of only viewing live in-app."""

from __future__ import annotations

import csv
import io


def rows_for(client, org_id):
    resp = client.get("/export/compliance.csv", headers={"authorization": f"org:{org_id}"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    return list(csv.reader(io.StringIO(resp.text)))


def test_export_has_one_row_per_control_with_a_header(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    upload(client, org_id)

    rows = rows_for(client, org_id)
    assert rows[0] == ["framework", "clause", "title", "verdict", "auditor_verdict", "locked",
                       "owner_emails", "open_gaps"]
    assert len(rows) > 1  # header plus at least one control


def test_export_is_org_isolated(client, bootstrap, upload):
    org_a, _ = bootstrap(client)
    org_b, _ = bootstrap(client)
    upload(client, org_a)

    a_rows = rows_for(client, org_a)
    b_rows = rows_for(client, org_b)
    assert len(a_rows) > 1
    assert len(b_rows) == 1  # header only, no controls
