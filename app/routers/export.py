"""A downloadable compliance summary — the single most consistently requested
GRC feature (Vanta's "export controls," Drata's "pre-audit package"): an
auditor or executive needs something to take away, not only a live UI.

CSV, not PDF: stdlib `csv`, no new dependency, opens natively in Excel/Sheets.
A PDF is a real upgrade path if asked for later, not needed to prove the
feature. Reuses the same control/gap sweep app/routers/analytics.py's
dashboard endpoint already does — this file adds no new authorization rule.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import Actor, current_actor
from app.db import get_session
from app.routers import controls as controls_router
from app.routers.analytics import best_verdict, control_details

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/compliance.csv")
def compliance_csv(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    open_gaps: dict[tuple[str, str], int] = {}
    for gap in controls_router.list_gaps(status="OPEN", actor=actor, db=db):
        key = (gap["framework"], gap["clause"])
        open_gaps[key] = open_gaps.get(key, 0) + 1

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["framework", "clause", "title", "verdict", "auditor_verdict", "locked",
                     "owner_emails", "open_gaps"])
    for control in control_details(actor, db):
        verdict = best_verdict(control["links"])
        auditor_verdicts = sorted({l["auditor_verdict"] for l in control["links"] if l["auditor_verdict"]})
        writer.writerow([
            control["framework"], control["clause"], control["title"], verdict,
            ", ".join(auditor_verdicts), "yes" if control["locked"] else "no",
            "; ".join(control["owner_emails"]),
            open_gaps.get((control["framework"], control["clause"]), 0),
        ])

    return Response(
        content=buffer.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=compliance-export.csv"},
    )
