"""A downloadable compliance summary — the single most consistently requested
GRC feature (Vanta's "export controls," Drata's "pre-audit package"): an
auditor or executive needs something to take away, not only a live UI.

CSV via stdlib `csv`; XLSX via `openpyxl` — already a hard dependency (used to
parse .xlsx evidence in app/documents.py), so no new package for the export
side either. Both reuse the same control/gap/task sweeps
app/routers/analytics.py and app/routers/controls.py already do — this file
adds no new authorization rule, only the two output formats and, for the
per-view exports, the same filters those list pages already accept.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from app.auth import Actor, current_actor
from app.db import get_session
from app.routers import controls as controls_router
from app.routers.analytics import best_verdict, control_details

router = APIRouter(prefix="/export", tags=["export"])

COMPLIANCE_HEADER = ["framework", "clause", "title", "verdict", "auditor_verdict", "locked",
                     "owner_emails", "open_gaps"]


def _compliance_rows(actor: Actor, db: Session, *,
                     framework: str | None = None, verdict: str | None = None,
                     gap_status: str = "OPEN") -> list[list]:
    open_gaps: dict[tuple[str, str], int] = {}
    for gap in controls_router.list_gaps(status=gap_status, actor=actor, db=db):
        key = (gap["framework"], gap["clause"])
        open_gaps[key] = open_gaps.get(key, 0) + 1

    rows = []
    for control in control_details(actor, db):
        if framework and control["framework"] != framework:
            continue
        control_verdict = best_verdict(control["links"])
        if verdict and control_verdict != verdict:
            continue
        auditor_verdicts = sorted({l["auditor_verdict"] for l in control["links"] if l["auditor_verdict"]})
        rows.append([
            control["framework"], control["clause"], control["title"], control_verdict,
            ", ".join(auditor_verdicts), "yes" if control["locked"] else "no",
            "; ".join(control["owner_emails"]),
            open_gaps.get((control["framework"], control["clause"]), 0),
        ])
    return rows


def _xlsx_response(header: list[str], rows: list[list], filename: str) -> Response:
    """One sheet, a frozen header row, and an auto-filter over it — the three
    things that make a spreadsheet usable rather than just a grid of values."""
    wb = Workbook()
    ws: Worksheet = wb.active
    ws.title = "Export"
    ws.append(header)
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(header)).coordinate}{max(len(rows) + 1, 1)}"
    for col in ws.columns:
        width = max((len(str(cell.value)) for cell in col if cell.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(width + 2, 60)

    buffer = io.BytesIO()
    wb.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/compliance.csv")
def compliance_csv(framework: str | None = None, verdict: str | None = None,
                   actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COMPLIANCE_HEADER)
    writer.writerows(_compliance_rows(actor, db, framework=framework, verdict=verdict))
    return Response(
        content=buffer.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=compliance-export.csv"},
    )


@router.get("/compliance.xlsx")
def compliance_xlsx(framework: str | None = None, verdict: str | None = None,
                    actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    rows = _compliance_rows(actor, db, framework=framework, verdict=verdict)
    return _xlsx_response(COMPLIANCE_HEADER, rows, "compliance-export.xlsx")


GAPS_HEADER = ["framework", "clause", "attribute", "detail", "actual_value", "required_value",
              "required_action", "status"]


@router.get("/gaps.xlsx")
def gaps_xlsx(status: str | None = "OPEN", actor: Actor = Depends(current_actor),
             db: Session = Depends(get_session)):
    """Same filter GapsList.tsx's status select applies — export what's on screen."""
    rows = [
        [g["framework"], g["clause"], g["attribute"], g["detail"], g["actual_value"],
         g["required_value"], g["required_action"], g["status"]]
        for g in controls_router.list_gaps(status=status, actor=actor, db=db)
    ]
    return _xlsx_response(GAPS_HEADER, rows, "gaps-export.xlsx")


TASKS_HEADER = ["title", "framework", "clause", "required_action", "status", "priority",
               "owner_email", "due_at"]


@router.get("/tasks.xlsx")
def tasks_xlsx(status: str | None = None, priority: str | None = None,
              owner_user_id: str | None = None, q: str | None = None,
              actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """Same filters TasksList.tsx holds (status, priority, assignee, search)."""
    tasks = controls_router.list_tasks(status=status, priority=priority,
                                       owner_user_id=owner_user_id, q=q, actor=actor, db=db)
    rows = [
        [t["title"], t["framework"] or "", t["clause"] or "", t["required_action"] or "",
         t["status"], t["priority"] or "", t["owner_email"] or "", t["due_at"] or ""]
        for t in tasks
    ]
    return _xlsx_response(TASKS_HEADER, rows, "tasks-export.xlsx")
