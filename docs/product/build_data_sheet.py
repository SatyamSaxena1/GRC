"""Builds docs/product/GRC-Technical-Data-Sheet.pdf, a ten-page technical data sheet.

    python docs/product/build_data_sheet.py

Every number on the chart pages is computed from the content packs in app/content, so the sheet
cannot drift from the product; the prose is what the repository does today, and the Boundaries box
says what it does not. Update the module and feature text here when a feature ships.
"""

import collections
import glob
import os
from datetime import date
from pathlib import Path

import yaml
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]


def load_packs() -> dict:
    """Framework x control-domain data from the content packs, as shipped."""
    content = ROOT / "app" / "content"
    ucos = yaml.safe_load((content / "uco.yaml").read_text(encoding="utf-8"))["ucos"]
    dom = {u["code"]: u["domain"] for u in ucos}
    out = {"cc": 0, "fws": [], "reqs": {}, "rule": {}, "M": {}, "U": {}, "dom": dom, "titles": {u["code"]: u["title"] for u in ucos},
           "coverage": collections.Counter()}
    reach = collections.defaultdict(set)
    for f in sorted(glob.glob(str(content / "*.yaml"))):
        name = os.path.basename(f)
        if name.startswith(("glossary", "uco")):
            continue
        d = yaml.safe_load(open(f, encoding="utf-8"))
        code = d["framework"]["code"]
        out["fws"].append(code)
        out["reqs"][code] = len(d["requirements"])
        # A requirement with no mappings has no rule yet: it is met by a named person's attestation (ADR-060).
        out["rule"][code] = sum(1 for q in d["requirements"] if q.get("mappings"))
        if code == "SOC-2":   # the Security (Common Criteria) clauses, CC1.1 to CC9.2: 33 in the standard
            out["cc"] = sum(1 for q in d["requirements"] if str(q["clause"]).startswith("CC"))
        counts = collections.Counter()
        for q in d["requirements"]:
            for m in q.get("mappings", []):
                counts[dom.get(m["uco"], "?")] += 1
                reach[m["uco"]].add(code)
                out["coverage"][m["coverage"]] += 1
        out["M"][code] = dict(counts)
    out["U"] = {k: sorted(v) for k, v in reach.items()}
    return out


PACKS = load_packs()
N_FW, N_REQ, N_UCO = len(PACKS["fws"]), sum(PACKS["reqs"].values()), len(PACKS["dom"])
N_MAP = sum(PACKS["coverage"].values())
N_RULE = sum(PACKS["rule"].values())     # requirements a rule judges from evidence
N_ATT = N_REQ - N_RULE                    # requirements met by a person's attestation
N_ISO, N_CC = PACKS["reqs"]["ISO-27001"], PACKS["cc"]   # ISO 27001 has 93 Annex A controls; SOC 2 has 33 CC criteria
TOTAL_PAGES = 10
MAX_REACH = max(len(v) for v in PACKS["U"].values())
WORDS = {9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
OUT = str(ROOT / "docs" / "product" / "GRC-Technical-Data-Sheet.pdf")
W, H = A4
NAVY, CYAN, TEAL = HexColor("#1b2a4e"), HexColor("#19b3e6"), HexColor("#1496b8")
INK, MUTED, RULE = HexColor("#222b3a"), HexColor("#5b6678"), HexColor("#d7dde6")
TINT, TINT2 = HexColor("#e9f6fb"), HexColor("#f4f6f9")
GREEN, AMBER = HexColor("#1f9d6b"), HexColor("#c98a12")
M = 36  # page margin

NAME = "GRC Evidence Platform"
REPO = "github.com/SatyamSaxena1/GRC"
DEMO = "grc-demo-vu2u.onrender.com"      # the role-switching demo on throwaway data
LIVE = "grc.blinkedit.me"                 # the live service, with a read-only public demo (ADR-062)

c = canvas.Canvas(OUT, pagesize=A4)
c.setTitle(f"{NAME} - Technical Data Sheet")
c.setAuthor("GRC Evidence Platform")


def text(x, y, s, size=9, font="Helvetica", color=INK):
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawString(x, y, s)


def para(x, y, s, width, size=9, font="Helvetica", color=INK, lead=None):
    """Draw wrapped text from the top y downwards; returns the y below it."""
    lead = lead or size * 1.38
    for line in simpleSplit(s, font, size, width):
        y -= lead
        text(x, y, line, size, font, color)
    return y


def bullets(x, y, items, width, size=8.4, gap=2.2):
    for it in items:
        lines = simpleSplit(it, "Helvetica", size, width - 10)
        for i, line in enumerate(lines):
            y -= size * 1.32
            if i == 0:
                text(x, y, "•", size, color=TEAL)
            text(x + 10, y, line, size)
        y -= gap
    return y


def header_bar(title, y=H - 78):
    c.setFillColor(NAVY)
    c.rect(M, y, W - 2 * M, 28, fill=1, stroke=0)
    c.setFillColor(CYAN)
    c.rect(M, y, 5, 28, fill=1, stroke=0)
    text(M + 16, y + 9, title, 14, "Helvetica-Bold", white)


def chrome(n):
    """Wordmark top right, footer with page and source."""
    text(W - M - 138, H - 34, "GRC", 15, "Helvetica-Bold", NAVY)
    text(W - M - 138 + c.stringWidth("GRC", "Helvetica-Bold", 15) + 5, H - 34, "Evidence Platform", 10, "Helvetica-Bold", TEAL)
    c.setStrokeColor(RULE)
    c.line(M, 30, W - M, 30)
    text(M, 18, f"{REPO}  |  Technical data sheet  |  built from the repository, {n}/{TOTAL_PAGES}", 7, color=MUTED)


def table(x, y, widths, rows, head=None, size=8.2, pad=5, label_bold=True, zebra=False):
    """Rows are (label, text) or (label, [bullets]). Returns y below the table."""
    tw = sum(widths)
    if head:
        c.setFillColor(TEAL)
        c.rect(x, y - 18, tw, 18, fill=1, stroke=0)
        cx = x
        for w, h in zip(widths, head):
            text(cx + 8, y - 12.5, h, 8.6, "Helvetica-Bold", white)
            cx += w
        y -= 18
    for i, (label, body) in enumerate(rows):
        items = body if isinstance(body, list) else [body]
        h = pad
        wrapped = []
        for it in items:
            ls = simpleSplit(it, "Helvetica", size, widths[1] - 22)
            wrapped.append(ls)
            h += len(ls) * size * 1.3 + 1.6
        lab = simpleSplit(label, "Helvetica-Bold", size + 0.4, widths[0] - 14)
        h = max(h + pad, len(lab) * (size + 0.4) * 1.3 + 2 * pad)
        if zebra and i % 2 == 0:
            c.setFillColor(TINT2)
            c.rect(x, y - h, tw, h, fill=1, stroke=0)
        c.setFillColor(TINT)
        c.rect(x, y - h, widths[0], h, fill=1, stroke=0)
        c.setStrokeColor(RULE)
        c.rect(x, y - h, tw, h, fill=0, stroke=1)
        ty = y - pad - (h - 2 * pad - len(lab) * (size + 0.4) * 1.3) / 2
        for ln in lab:
            ty -= (size + 0.4) * 1.3
            text(x + 7, ty + 2.5, ln, size + 0.4, "Helvetica-Bold" if label_bold else "Helvetica", NAVY)
        by = y - pad + 1
        for ls in wrapped:
            for j, ln in enumerate(ls):
                by -= size * 1.3
                if isinstance(body, list) and j == 0:
                    text(x + widths[0] + 8, by, "•", size, color=TEAL)
                text(x + widths[0] + 18 if isinstance(body, list) else x + widths[0] + 8, by, ln, size)
            by -= 1.6
        y -= h
    return y


def tile(x, y, w, h, title, body):
    c.setFillColor(TINT2)
    c.roundRect(x, y - h, w, h, 5, fill=1, stroke=0)
    c.setFillColor(CYAN)
    c.rect(x, y - h, 3.5, h, fill=1, stroke=0)
    text(x + 12, y - 15, title, 8.8, "Helvetica-Bold", NAVY)
    para(x + 12, y - 19, body, w - 20, 8.4, color=INK, lead=11)


# ---- drawing helpers and the chart/diagram pages
from reportlab.lib.colors import Color

RED = HexColor("#d64545")
PALE = HexColor("#cfd9ee")


def box(x, y, w, h, title, sub="", fill=NAVY, fg=white, subfg=PALE, tsize=8.6, ssize=7.2, r=5, dash=False, stroke=None):
    """y is the bottom edge."""
    c.setFillColor(fill)
    if stroke:
        c.setStrokeColor(stroke)
    if dash:
        c.setDash(3, 2)
    c.roundRect(x, y, w, h, r, fill=1, stroke=1 if (dash or stroke) else 0)
    c.setDash()
    tl = simpleSplit(title, "Helvetica-Bold", tsize, w - 10)
    sl = simpleSplit(sub, "Helvetica", ssize, w - 10) if sub else []
    total = len(tl) * tsize * 1.2 + len(sl) * ssize * 1.25
    ty = y + h / 2 + total / 2
    for ln in tl:
        ty -= tsize * 1.2
        c.setFont("Helvetica-Bold", tsize); c.setFillColor(fg)
        c.drawCentredString(x + w / 2, ty + 2, ln)
    for ln in sl:
        ty -= ssize * 1.25
        c.setFont("Helvetica", ssize); c.setFillColor(subfg)
        c.drawCentredString(x + w / 2, ty + 2, ln)


def arrow(x1, y1, x2, y2, color=CYAN, width=1.5):
    import math
    c.setStrokeColor(color); c.setLineWidth(width)
    c.line(x1, y1, x2, y2)
    a = math.atan2(y2 - y1, x2 - x1)
    for d in (0.5, -0.5):
        c.line(x2, y2, x2 - 6 * math.cos(a + d), y2 - 6 * math.sin(a + d))
    c.setLineWidth(1)


def label(x, y, s, size=7.4, color=MUTED, font="Helvetica", center=False):
    c.setFont(font, size); c.setFillColor(color)
    (c.drawCentredString if center else c.drawString)(x, y, s)


def heat(v, vmax):
    """White to teal by value."""
    t = 0 if not v else 0.22 + 0.78 * (v / vmax)
    return Color(1 - t * (1 - 0.078), 1 - t * (1 - 0.588), 1 - t * (1 - 0.722))


# ------------------------------------------------------------------ page: architecture + lifecycle
def page_architecture(n):
    c.showPage(); chrome(n)
    header_bar("System Architecture")
    y = H - 104
    label(M, y, "USERS", 7.4, TEAL, "Helvetica-Bold")
    chips = ["Org admin", "Control owner", "Compliance viewer", "Auditor", "Firm admin"]
    cw = (W - 2 * M - 4 * 6) / 5
    for i, t in enumerate(chips):
        box(M + i * (cw + 6), y - 26, cw, 20, t, fill=TINT, fg=NAVY, tsize=7.8, r=10)
    arrow(W / 2, y - 28, W / 2, y - 42)
    box(M, y - 76, W - 2 * M, 32, "Web app: React + Vite single-page app", "role-aware workspace · evidence map · guided tours · live processing view",
        fill=TEAL, tsize=9.4)
    arrow(W / 2, y - 78, W / 2, y - 92)

    # API container
    top = y - 94
    ch = 176
    c.setFillColor(TINT2); c.setStrokeColor(RULE)
    c.roundRect(M, top - ch, W - 2 * M, ch, 8, fill=1, stroke=1)
    label(M + 12, top - 15, "FASTAPI SERVICE  ·  modular monolith, one process", 8, NAVY, "Helvetica-Bold")
    inner = [
        ("Evidence pipeline", "upload → validate → extract → evaluate"),
        ("Decision engine", "versioned YAML content packs, deterministic rules"),
        ("Auditor workspace", "verdicts, locks, exceptions, messages"),
        ("Audit log", "per-tenant hash chain, signed checkpoints"),
        ("Review engine", "Review Standards for code review"),
        ("Connections", "uploaded snapshots and change-control evidence"),
    ]
    bw = (W - 2 * M - 24 - 2 * 8) / 3
    for i, (t1, t2) in enumerate(inner):
        bx = M + 12 + (i % 3) * (bw + 8)
        by = top - 36 - (i // 3) * 66 - 52
        box(bx, by, bw, 52, t1, t2, fill=NAVY if i != 1 else TEAL, tsize=8.8, ssize=7.2)
    arrow(W / 2, top - ch, W / 2, top - ch - 14)

    # data row
    ry = top - ch - 16
    store = [
        ("PostgreSQL", "row-level security, FORCE; append-only audit trigger"),
        ("Object storage", "S3-compatible (MinIO, R2, Supabase) or local disk"),
        ("Model host", "Ollama · LM Studio · any OpenAI-compatible host"),
        ("Identity provider", "OIDC, RS256 JWT verified against its keys"),
    ]
    sw = (W - 2 * M - 3 * 7) / 4
    for i, (t1, t2) in enumerate(store):
        box(M + i * (sw + 7), ry - 56, sw, 56, t1, t2, fill=white, fg=NAVY, subfg=MUTED, tsize=8.6, ssize=7, stroke=TEAL)
    # externals
    ey = ry - 56 - 14
    box(M, ey - 40, (W - 2 * M) / 2 - 4, 40, "Read-only collectors and uploads", "GitHub · GitLab · Bitbucket pulled; AWS · M365 · Google Workspace · HR by customer-run script",
        fill=TINT, fg=NAVY, subfg=MUTED, tsize=8.6, ssize=7)
    box(M + (W - 2 * M) / 2 + 4, ey - 40, (W - 2 * M) / 2 - 4, 40, "Outputs", "CSV / XLSX report · OSCAL export · CISO Assistant sync · signed checkpoints",
        fill=TINT, fg=NAVY, subfg=MUTED, tsize=8.6, ssize=7)

    # lifecycle
    y = ey - 40 - 28
    header_bar("Evidence Lifecycle", y - 28)
    y -= 46
    steps = [("Upload", "file or connector"), ("Validate", "size · MIME · SHA-256 · scan"), ("Store", "versioned, immutable"),
             ("Extract", "native text, then VLM"), ("Evaluate", "every subscribed framework"), ("Verdict", "auditor records it"),
             ("Lock", "control closes")]
    sw = (W - 2 * M - 6 * 8) / 7
    for i, (t1, t2) in enumerate(steps):
        fill = TEAL if i == 4 else (NAVY if i < 5 else HexColor("#2a3f73"))
        box(M + i * (sw + 8), y - 52, sw, 52, t1, t2, fill=fill, tsize=8.8, ssize=6.6)
        if i < 6:
            arrow(M + i * (sw + 8) + sw + 0.5, y - 26, M + (i + 1) * (sw + 8) - 0.5, y - 26)
    y -= 52 + 14
    label(M, y, "Status shown to the user:", 7.6, MUTED, "Helvetica-Bold")
    x = M + 112
    for t, col in [("STORED", MUTED), ("EXTRACTING", CYAN), ("ANALYZING", CYAN), ("EVALUATING", TEAL),
                   ("READY", GREEN), ("NEEDS_REVIEW", AMBER), ("FAILED", RED)]:
        wd = c.stringWidth(t, "Helvetica-Bold", 7) + 14
        c.setFillColor(col); c.roundRect(x, y - 3, wd, 13, 6, fill=1, stroke=0)
        label(x + wd / 2, y + 0.5, t, 7, white, "Helvetica-Bold", True)
        x += wd + 5
    y = para(M, y - 14, "A new version supersedes the old one and resolves the gaps it fixes; the old version's gaps and verdicts stay on record. "
             "If the model is unavailable the file is stored and flagged, never silently passed.", W - 2 * M, 8.4, "Helvetica-Oblique", MUTED)


# ------------------------------------------------------------------ page: reuse charts (real data from the content packs)
SHORT = {"CIS-CONTROLS": "CIS v8", "DPDP": "DPDP", "GDPR": "GDPR", "HIPAA": "HIPAA", "ISO-27001": "ISO 27001",
         "NIST-AI-RMF": "NIST AI RMF", "NIST-CSF": "NIST CSF", "PCI-DSS": "PCI DSS", "SOC-2": "SOC 2"}
DOMS = [("IAM", "IAM"), ("DATA_PROTECTION", "Data prot."), ("VULNERABILITY_MANAGEMENT", "Vuln. mgmt"),
        ("LOGGING", "Logging"), ("CHANGE_MANAGEMENT", "Change mgmt"), ("PRIVACY", "Privacy"), ("AI_GOVERNANCE", "AI gov.")]


def page_reuse(n):
    c.showPage(); chrome(n)
    header_bar("Evidence Reuse in Numbers")
    y = para(M, H - 84, "Computed from the content packs in the repository. The same unified control objective is satisfied "
             "once and counted by every framework that maps to it, which is why one document can serve several frameworks.",
             W - 2 * M, 9.2)
    req = PACKS["reqs"]; U = PACKS["U"]
    total_req = sum(req.values()); maps = sum(len(v) for v in U.values())
    # KPI tiles
    y -= 10
    kp = [(str(N_FW), "frameworks"), (str(total_req), "requirements listed"), (str(N_RULE), "judged by rules"),
          (str(len(PACKS["dom"])), "unified objectives"), (str(N_MAP), "mappings")]
    kw = (W - 2 * M - 4 * 8) / 5
    for i, (big, small) in enumerate(kp):
        x = M + i * (kw + 8)
        c.setFillColor(NAVY); c.roundRect(x, y - 52, kw, 52, 6, fill=1, stroke=0)
        label(x + 12, y - 30, big, 22, white, "Helvetica-Bold")
        label(x + 12, y - 45, small, 7.8, PALE)
    y -= 52 + 22

    # chart A: reach
    half = (W - 2 * M - 20) / 2
    label(M, y, "Objectives that reach the most frameworks", 9.4, NAVY, "Helvetica-Bold")
    label(M, y - 11, f"frameworks mapping to the objective, out of {N_FW}", 7.4)
    reach = sorted(((len(v), k) for k, v in U.items()), reverse=True)[:8]
    by = y - 20
    for i, (cnt, code) in enumerate(reach):
        yy = by - i * 21
        t = PACKS["titles"][code]
        t = t if len(t) <= 46 else t[:45].rstrip() + "…"
        label(M, yy - 7, code.replace("UCO-", ""), 7, NAVY, "Helvetica-Bold")
        label(M + 46, yy - 7, t, 6.3, MUTED)
        bx0, bwid = M + 210, 90
        c.setFillColor(TINT2); c.rect(bx0, yy - 11, bwid, 11, fill=1, stroke=0)
        c.setFillColor(TEAL if cnt >= 6 else CYAN); c.rect(bx0, yy - 11, bwid * cnt / 9, 11, fill=1, stroke=0)
        label(bx0 + bwid * cnt / 9 + 4, yy - 8.6, str(cnt), 7.4, NAVY, "Helvetica-Bold")
    # chart B: donut of coverage kinds
    dx = M + 330
    cx, cy, ro, ri = dx + 96, y - 62, 44, 25
    label(dx, y, "Mapping coverage", 9.4, NAVY, "Helvetica-Bold")
    label(dx, y - 11, f"{N_MAP} mappings, {WORDS.get(N_FW, N_FW)} packs", 7.4)
    parts = [(k, PACKS["coverage"][k], c_) for k, c_ in (("FULL", TEAL), ("SUPPORTING", CYAN), ("PARTIAL", AMBER))]
    ang = 90
    for name, val, col in parts:
        ext = -360 * val / N_MAP
        c.setFillColor(col); c.setStrokeColor(white)
        c.wedge(cx - ro, cy - ro, cx + ro, cy + ro, ang, ext, fill=1, stroke=1)
        ang += ext
    c.setFillColor(white); c.circle(cx, cy, ri, fill=1, stroke=0)
    label(cx, cy - 4, str(N_MAP), 15, NAVY, "Helvetica-Bold", True)
    for i, (name, val, col) in enumerate(parts):
        lx, ly = dx + 4 + i * 66, cy - ro - 18
        c.setFillColor(col); c.rect(lx, ly, 8, 8, fill=1, stroke=0)
        label(lx + 12, ly + 1, f"{name.title()} {val}", 7.4, INK, "Helvetica-Bold")
        label(lx + 12, ly - 8, f"{round(100 * val / N_MAP)}%", 6.6, MUTED)
    y = by - 8 * 21 - 16

    # chart C: heatmap
    label(M, y, "Framework × control domain", 9.4, NAVY, "Helvetica-Bold")
    label(M, y - 11, "requirement-to-objective mappings; darker means more", 7.4)
    y -= 22
    cols = 7; lw = 78; rw = 34
    cellw = (W - 2 * M - lw - rw) / cols
    for j, (_, short) in enumerate(DOMS):
        label(M + lw + rw + j * cellw + cellw / 2, y - 8, short, 6.8, NAVY, "Helvetica-Bold", True)
    label(M + lw + rw / 2 - 2, y - 8, "Rule/all", 6.4, NAVY, "Helvetica-Bold", True)
    y -= 14
    vmax = max(v for row in PACKS["M"].values() for v in row.values())
    for i, fw in enumerate(sorted(PACKS["M"], key=lambda f: -req[f])):
        yy = y - i * 19
        label(M, yy - 12, SHORT[fw], 8, NAVY, "Helvetica-Bold")
        c.setFillColor(TINT2); c.rect(M + lw, yy - 16, rw - 4, 16, fill=1, stroke=0)
        label(M + lw + (rw - 4) / 2, yy - 12, f"{PACKS['rule'][fw]}/{req[fw]}", 7.4, NAVY, "Helvetica-Bold", True)
        for j, (dk, _) in enumerate(DOMS):
            v = PACKS["M"][fw].get(dk, 0)
            c.setFillColor(heat(v, vmax)); c.setStrokeColor(white)
            c.rect(M + lw + rw + j * cellw, yy - 16, cellw, 16, fill=1, stroke=1)
            if v:
                label(M + lw + rw + j * cellw + cellw / 2, yy - 12, str(v), 8, white if v / vmax > 0.5 else NAVY, "Helvetica-Bold", True)
    y -= 9 * 19 + 14
    para(M, y, "Reading it: the AI RMF pack maps only to AI governance, while the security frameworks share identity and access, data protection "
         "and vulnerability objectives, "
         f"so the most widely shared objectives reach {WORDS.get(MAX_REACH, MAX_REACH)} of the {WORDS.get(N_FW, N_FW)} frameworks. "
         f"Every ISO 27001 Annex A control and almost every SOC 2 Security criterion is now listed, but a rule judges only {N_RULE} of the "
         f"{N_REQ} requirements; the other {N_ATT} are met by a named person's dated attestation until a rule can be written. "
         f"The mapping counts above are of the {N_RULE} rule-judged requirements, as shipped.",
         W - 2 * M, 8.4, "Helvetica-Oblique", MUTED)


# ------------------------------------------------------------------ page: integrity diagrams
def page_integrity(n):
    c.showPage(); chrome(n)
    header_bar("Integrity by Design")
    y = H - 104
    label(M, y, "Tamper-evident audit chain", 10, NAVY, "Helvetica-Bold")
    label(M, y - 12, "each event commits to the hash of the one before it; one chain per organisation", 7.6)
    names = [("Genesis", "seals pre-chain rows"), ("Upload", "EVIDENCE_UPLOADED"), ("Verdict", "AUDITOR_VERDICT"), ("Lock", "CONTROL_LOCKED"), ("Head", "latest event")]
    bw = (W - 2 * M - 4 * 22) / 5
    ty = y - 74
    for i, (t1, t2) in enumerate(names):
        x = M + i * (bw + 22)
        box(x, ty, bw, 46, t1, t2, fill=NAVY, tsize=8.8, ssize=6.8)
        label(x + 6, ty - 9, f"hash {chr(97 + i)}…", 6.6, MUTED, "Helvetica-Oblique")
        if i < 4:
            arrow(x + bw, ty + 23, x + bw + 22, ty + 23)
            label(x + bw + 11, ty + 29, "prev", 6, MUTED, center=True)
    # checkpoint
    cxp = M + 3 * (bw + 22) + bw / 2
    c.setStrokeColor(GREEN); c.setFillColor(GREEN); c.setLineWidth(1.2)
    c.line(cxp, ty + 46, cxp, ty + 70)
    c.setLineWidth(1)
    box(cxp - 96, ty + 70, 192, 30, "Signed checkpoint (Ed25519)", "chain position + head hash, kept by the auditor", fill=GREEN, tsize=8, ssize=6.6)
    # tamper scenario
    y2 = ty - 40
    label(M, y2, "If a past event is edited, inserted or deleted:", 8.4, NAVY, "Helvetica-Bold")
    tb = y2 - 54
    for i, (t1, ok) in enumerate([("Genesis", True), ("Upload", True), ("Verdict (edited)", False), ("Lock", False), ("Head", False)]):
        x = M + i * (bw + 22)
        box(x, tb, bw, 34, t1, "hash matches" if ok else ("hash changes" if i == 2 else "prev no longer matches"),
            fill=GREEN if ok else RED, tsize=7.8, ssize=6.4)
        if i < 4:
            arrow(x + bw, tb + 17, x + bw + 22, tb + 17, MUTED)
    label(M, tb - 14, "Verification fails at the first bad event: “event 3 does not hash to its recorded value”. "
          "On Postgres a trigger also refuses UPDATE and DELETE.", 7.6, MUTED, "Helvetica-Oblique")

    # verdict lifecycle
    y = tb - 44
    label(M, y, "Control verdict lifecycle", 10, NAVY, "Helvetica-Bold")
    label(M, y - 12, "the model never appears here: rules produce the engine verdict, a person records the opinion", 7.6)
    sy = y - 70
    sw = (W - 2 * M - 3 * 26) / 4
    st = [("Engine verdict", "PASS · PARTIAL · FAIL, with rule hash", TEAL), ("Auditor verdict", "named auditor, on an engagement", NAVY),
          ("Locked", "COMPLIANT or PASS closes the control", GREEN), ("Reopened", "unlock with a stated reason", AMBER)]
    for i, (t1, t2, col) in enumerate(st):
        x = M + i * (sw + 26)
        box(x, sy, sw, 46, t1, t2, fill=col, tsize=8.6, ssize=6.6)
        if i < 3:
            arrow(x + sw, sy + 23, x + sw + 26, sy + 23)
    # back arrow from reopened to auditor verdict (loop under)
    x4 = M + 3 * (sw + 26) + sw / 2; x2 = M + (sw + 26) + sw / 2
    c.setStrokeColor(AMBER); c.setLineWidth(1.4)
    c.line(x4, sy, x4, sy - 14); c.line(x4, sy - 14, x2, sy - 14); arrow(x2, sy - 14, x2, sy - 1, AMBER, 1.4)
    c.setLineWidth(1)
    label((x4 + x2) / 2, sy - 24, "a new verdict follows", 6.8, AMBER, "Helvetica-Bold", True)
    box(M, sy - 56, sw * 2 + 26, 24, "Segregation of duties", "the uploader of the evidence cannot record its verdict", fill=TINT, fg=NAVY, subfg=MUTED, tsize=7.8, ssize=6.6)
    box(M + 2 * (sw + 26), sy - 56, sw * 2 + 26, 24, "Verdict register", "every reopening and replacement kept as its own record, with its reason", fill=TINT, fg=NAVY, subfg=MUTED,
        tsize=7.8, ssize=6.6)

    # exception validity
    y = sy - 94
    label(M, y, "When a gap exception stops applying", 10, NAVY, "Helvetica-Bold")
    label(M, y - 12, "validity is recomputed on every read against the rule and the gap as they are now", 7.6)
    ey = y - 96
    box(M, ey, 84, 44, "Requested", "by the auditee", fill=NAVY, tsize=8.6, ssize=6.8)
    box(M + 116, ey, 84, 44, "Approved", "by an auditor", fill=GREEN, tsize=8.6, ssize=6.8)
    arrow(M + 84, ey + 22, M + 116, ey + 22)
    box(M, ey - 54, 84, 30, "Rejected", fill=MUTED, tsize=8.4)
    arrow(M + 42, ey, M + 42, ey - 24, MUTED)
    ends = [("Expired", "no exception lasts beyond 180 days", AMBER), ("Rule changed", "the requirement's pack definition hash differs", AMBER),
            ("Value changed", "the gap's actual value grew or moved", AMBER), ("Revoked", "withdrawn after approval", RED)]
    bus = M + 232
    ex = bus + 22
    for i, (t1, t2, col) in enumerate(ends):
        by = ey + 44 - 6 - (i + 1) * 28 + 28 - 4 + 0
        by = ey + 52 - i * 34
        box(ex, by - 28, W - M - ex, 28, f"{t1}  ·  {t2}", fill=col, tsize=7.8, r=4)
        arrow(bus, by - 14, ex, by - 14, MUTED, 1.1)
    c.setStrokeColor(MUTED); c.setLineWidth(1.1)
    c.line(M + 200, ey + 22, bus, ey + 22)
    c.line(bus, ey + 52 - 14, bus, ey + 52 - 3 * 34 - 14)
    c.setLineWidth(1)
    label(M + 158, ey - 14, "waives the gap while valid", 7, MUTED, "Helvetica-Oblique", True)


# ------------------------------------------------------------------ page: running the programme
def page_programme(n):
    c.showPage(); chrome(n)
    header_bar("Running the Programme")
    y = para(M, H - 84, "Beyond the audit loop, the boundary holds: where a number or a grade is produced (a risk score, a vendor tier, a "
             "training result), fixed rules produce it and a person signs. A model may suggest wording, never a score.",
             W - 2 * M, 9.2)
    rows = [
        ("Policy library", ["An admin writes and approves each version; every person accepts it for themselves",
                            "Editing the text is a new version that everyone accepts again; archiving keeps every version and acceptance",
                            "Templates whose figures already meet the frameworks' rules (ADR-038, ADR-056)"]),
        ("Training", ["Courses with lessons and graded scenario questions; fixed rules grade them, and the right answer and its reason appear after you answer",
                      "Best try per lesson counts: 80% or more is PASS, 50% or more PARTIAL; it repeats every year",
                      "An admin sees everyone's result and who is behind; every try is kept. A pass shows a person was given the material and answered, not that they are competent (ADR-063, ADR-064)"]),
        ("Risk register", ["A fixed five-by-five scale scores each risk; a person signs; heat map, treatment, owner and next review date",
                           "A model may suggest wording and never sets a score (ADR-057)"]),
        ("Vendors", ["A register with a rule-decided risk tier from data access, criticality and attestation",
                     "A current SOC 2 or ISO 27001 report on file lowers the tier only while its valid-until date has not passed (ADR-042, ADR-043)"]),
        ("Trust page and questionnaires", ["A public trust page, off by default and content-free (ADR-039)",
                                           "Security questionnaire answers drawn from stored verdicts (ADR-040)"]),
        ("First week and drift", ["A first-week checklist read from real data, never hand-ticked",
                                  "A weekly digest of controls that turned worse and sources that went quiet (ADR-041, ADR-058)"]),
        ("Plans and demo", ["Plans set by hand with limits on frameworks and people, a FREE plan, and no payment code; an ended trial is read-only (ADR-054, ADR-062)",
                            "A public read-only demo organisation: anyone can look, every change is refused by the server (ADR-062)"]),
    ]
    table(M, y - 12, [118, W - 2 * M - 118], rows, head=["Area", "What it does"], size=8.4, pad=7)


# ------------------------------------------------------------------ page 1: cover
c.setFillColor(CYAN)
c.rect(0, 160, 40, 290, fill=1, stroke=0)
c.saveState()
c.translate(27, 170)
c.rotate(90)
text(0, 0, "PRODUCT INFO", 17, "Helvetica-Bold", white)
c.restoreState()

text(M + 14, H - 80, "GRC", 44, "Helvetica-Bold", NAVY)
text(M + 14, H - 108, "Evidence Platform", 22, "Helvetica-Bold", TEAL)
text(M + 14, H - 130, "Evidence once, evaluated against every framework", 11.5, color=MUTED)

# pipeline motif
bx, by = M + 14, H - 250
for i, (t1, t2) in enumerate([("Document", "or connector"), ("Facts", "extracted"), ("Rules", "decide"), ("Auditor", "verdict")]):
    x = bx + i * 118
    c.setFillColor(NAVY if i != 2 else TEAL)
    c.roundRect(x, by, 100, 46, 6, fill=1, stroke=0)
    text(x + 10, by + 28, t1, 11.5, "Helvetica-Bold", white)
    text(x + 10, by + 14, t2, 8.6, color=HexColor("#cfd9ee"))
    if i < 3:
        c.setStrokeColor(CYAN)
        c.setLineWidth(1.6)
        c.line(x + 102, by + 23, x + 116, by + 23)
        c.line(x + 111, by + 28, x + 116, by + 23)
        c.line(x + 111, by + 18, x + 116, by + 23)
        c.setLineWidth(1)
text(bx, by - 18, "Every step lands in an append-only, hash-chained audit log.", 8.8, "Helvetica-Oblique", MUTED)

# title block
c.setFillColor(NAVY)
c.roundRect(60, 340, W - 60 - M, 96, 8, fill=1, stroke=0)
text(84, 392, "TECHNICAL", 34, "Helvetica-Bold", white)
text(84, 356, "DATA SHEET", 34, "Helvetica-Bold", white)

text(88, 306, NAME, 14, "Helvetica-Bold", NAVY)
y = para(
    88, 296,
    "A compliance evidence platform built on one rule: the model reads, the rules decide, a human signs. "
    "One uploaded document is evaluated once against every framework the organisation subscribes to, with "
    "page-level provenance, gaps and remediation tasks, and an auditor verdict that locks the control.",
    W - 88 - M, 10)
y = para(
    88, y - 6,
    "Verdicts come from versioned, deterministic rules rather than from a model, so a result can be "
    "replayed and explained after the fact, and a change of model never changes a past decision. "
    "Five parties are supported: an audit firm and its auditors, and an audited organisation with its "
    "org admin and control owners.",
    W - 88 - M, 10)
c.setFillColor(TINT)
c.rect(60, 96, W - 60 - M, 3, fill=1, stroke=0)
text(88, 76, f"{REPO}   |   read-only demo: {LIVE}", 8.6, color=MUTED)
text(88, 62, f"Data sheet generated from the repository, {date.today():%B %Y}. See page 9 for what is not yet covered.", 8, color=MUTED)

# ------------------------------------------------------------------ page 2: how it works
c.showPage(); chrome(2)
header_bar("How It Works")
y = para(M, H - 84, "Three parties each do the part they are good at, and nothing blurs the boundary between them. "
         "The boundary is what makes a verdict reproducible, resistant to prompt injection, and defensible to an auditor.",
         W - 2 * M, 9.4)
y -= 14
cols = [
    ("MODEL", "Extracts facts", ["Reads the document (native text first, a vision model only as a fallback)",
                                 "Reports what it says, with the quote and page it came from",
                                 "Local or remote: Ollama, LM Studio or any OpenAI-compatible endpoint",
                                 "Never decides pass or fail"], CYAN),
    ("RULES", "Decide, deterministically", ["Versioned content packs written in YAML",
                                            "One document evaluated against every subscribed framework",
                                            "Verdict records the rule hash, engine version and inputs",
                                            "Replayable: same facts and rules, same verdict"], TEAL),
    ("AUDITOR", "Signs and locks", ["A named human records the verdict",
                                    "Locking is enforced in the API and the data layer, not only the UI",
                                    "Uploader and verdict-giver can never be the same person",
                                    "Reopening is a recorded act with a reason"], NAVY),
]
cw = (W - 2 * M - 24) / 3
for i, (tag, ttl, its, col) in enumerate(cols):
    x = M + i * (cw + 12)
    c.setFillColor(col)
    c.roundRect(x, y - 36, cw, 36, 5, fill=1, stroke=0)
    text(x + 10, y - 15, tag, 8, "Helvetica-Bold", white)
    text(x + 10, y - 29, ttl, 11, "Helvetica-Bold", white)
    c.setFillColor(TINT2)
    c.rect(x, y - 36 - 170, cw, 170, fill=1, stroke=0)
    bullets(x + 8, y - 42, its, cw - 14, 9, 4)
y -= 36 + 170 + 20

c.setFillColor(NAVY)
c.roundRect(M, y - 40, W - 2 * M, 40, 6, fill=1, stroke=0)
text(M + 14, y - 17, "Audit log underneath", 10, "Helvetica-Bold", white)
text(M + 14, y - 31, "Per-tenant hash chain  ·  database refuses edits and deletes on Postgres  ·  "
     "signed checkpoints the auditor keeps  ·  offline verifier", 8.4, color=HexColor("#cfd9ee"))
y -= 58

header_bar("Five Roles, One Workspace", y - 28)
y -= 42
roles = [
    ("Org admin", "Audited organisation", "Uploads evidence, invites owners, registers controls, submits for review"),
    ("Control owner", "Audited organisation", "Works assigned tasks, fixes gaps, uploads new versions of evidence"),
    ("Compliance viewer", "Audited organisation", "Read-only view of readiness by framework, every gap and the audit trail"),
    ("Auditor", "Audit firm", "Records verdicts, locks controls, requests evidence; scoped to engaged frameworks only"),
    ("Firm admin", "Audit firm", "Approves onboarding, staffs auditors, tracks every client, opens an engagement"),
]
y = table(M, y - 8, [112, W - 2 * M - 112], [(a, f"{b}. {d}") for a, b, d in roles],
          head=["Role", "Party and what it does"], size=9, pad=8)
y -= 12
y = para(M, y, "Belonging to a firm grants access to nothing. Being staffed on an engagement is the grant, and an "
         "unstaffed client answers 404, indistinguishable from one that does not exist.", W - 2 * M, 8.6,
         "Helvetica-Oblique", MUTED)

page_architecture(3)

# ------------------------------------------------------------------ page 3: modules
c.showPage(); chrome(4)
header_bar("Modules & Features")
mods = [
    ("Evidence & Extraction", ["Upload with validation: size, name, MIME sniffing, allowlist, SHA-256, malware-scan hook",
                               "Versions supersede, never overwrite; soft delete keeps history",
                               "Page-level provenance for every extracted fact; quality and freshness scoring",
                               "Live processing view while a document is analysed"]),
    ("Compliance Engine", ["Nine content packs: ISO/IEC 27001:2022, PCI DSS 4.0.1, SOC 2, HIPAA Security Rule, GDPR, "
                           "DPDP 2023, NIST CSF 2.0, NIST AI RMF 1.0, CIS Controls v8",
                           f"Unified control objectives ({N_UCO}) so one fact satisfies several frameworks",
                           f"{N_ISO} of 93 ISO 27001 Annex A controls and {N_CC} of 33 SOC 2 Security criteria are listed; a requirement with no rule yet is met by a named person's dated attestation, shown as Attested, never as passed",
                           "Gaps carry the exact missing or short attribute and what to fix",
                           "Draft requirements from a law's own text (parsed deterministically), with a human review gate and an advisory model critique"]),
    ("Controls, Gaps & Tasks", ["Per-control verdicts, remediation tasks created from gaps, manual tasks and priorities",
                                "Auditor and auditee message threads: evidence requests, unlock requests, comments",
                                "Group tasks by the fix they share; assign, schedule and re-prioritise many at once",
                                "Control owners added and removed from the control page, optionally handing over open tasks",
                                "Notifications for expiring and expired evidence"]),
    ("Auditor Workspace", ["Verdicts that lock a control; reopening needs a stated reason",
                           "Segregation of duties enforced, not assumed",
                           "Signed audit-chain checkpoints (Ed25519) held by the auditor, verifiable offline",
                           "Verdict provenance: rule hash, engine version, inputs, Replay",
                           "Verdict history that is never edited: replacing a verdict adds a reopening and the new decision, each with its reason",
                           "Findings: an auditor raises one, the auditee responds, the auditor closes it; every step is audited",
                           "Overriding the rules' own verdict needs a stated reason"]),
    ("Gap Exceptions", ["Time-bound (180 days at most), approved by an auditor, never by the requester",
                        "Bound to the rule and the gap value: a changed rule or a bigger gap retires the exception",
                        "Computed at read time, so no scheduler is needed to expire one"]),
    ("Connectors & Change Control", ["AWS, Microsoft 365, Google Workspace and HR-leaver evidence comes from the customer's own read-only script, as yes/no answers uploaded with a token: we hold no cloud keys. A snapshot counts for 30 days, and a weekly GitHub Actions template runs them",
                                     "GitHub, GitLab and Bitbucket change control, pulled with a token the organisation saves encrypted",
                                     "Pre-merge change-control gate that runs the audit's own rules in CI",
                                     "Every run recorded as complete, partial or failed; a partial run is never read as a pass",
                                     "AI code review recorded as evidence, never as approval"]),
    ("Privacy & AI Governance", ["DPDP readiness, breach events and data-subject request log",
                                 "NIST AI RMF starter pack, AI policy and inventory artefact types",
                                 "Auditor-only AI summaries, clearly labelled as narration"]),
    ("Reporting & Integration", ["Compliance report as CSV or XLSX; OSCAL export; a weekly compliance report from what is already stored",
                                 "CISO Assistant sync of verdicts",
                                 "Optional webhook notices (Slack, Discord or your own endpoint) and a de-duplicated daily digest",
                                 "Ask AI: a helper that answers from stored data with read-only tools",
                                 "Evidence map, activity feed, glossary and guided tours"]),
]
table(M, H - 84, [118, W - 2 * M - 118], mods, head=["Module", "Key highlights"], size=8.3, pad=6)

page_programme(5)
page_reuse(6)
page_integrity(7)

# ------------------------------------------------------------------ page 4: features + security
c.showPage(); chrome(8)
header_bar("Distinctive Features")
y = para(M, H - 84, "What sets the platform apart from a document-store GRC tool is that the result is reproducible, "
         "attributable and tamper-evident.", W - 2 * M, 9.2)
tiles = [
    ("Evidence reuse", "One document evaluated once against every subscribed framework"),
    ("Deterministic verdicts", "Rules decide; the same inputs give the same result"),
    ("Replay", "Rules a verdict was judged against are kept, so it can be re-run later"),
    ("Hash-chained audit log", "Per-tenant chain; any edit, insert or delete breaks verification"),
    ("Auditor-held checkpoints", "Signed statements of the chain head, verified offline with a script"),
    ("Expiring exceptions", "Waivers lapse on time, on rule change or when the gap grows"),
    ("Tenant isolation in the DB", "Postgres row-level security, forced, not only app filters"),
    ("Segregation of duties", "Uploader cannot judge; exception requester cannot reopen"),
    ("Your own model", "Local, or any OpenAI-compatible host you choose; the model never decides a verdict"),
    ("Change-control evidence", "Collected from GitHub, GitLab and Bitbucket as it happens"),
    ("Findings workflow", "Raised by an auditor, answered by the auditee, closed on the record"),
    ("Alerts where you work", "Optional webhook notices and a daily digest; content-free by design"),
]
tw = (W - 2 * M - 12) / 2
y -= 8
for i, (t1, t2) in enumerate(tiles):
    x = M + (i % 2) * (tw + 12)
    yy = y - (i // 2) * 62
    tile(x, yy, tw, 54, t1, t2)
y -= ((len(tiles) + 1) // 2) * 62 + 18

header_bar("Platform Security", y - 28)
y -= 36
rows = [
    ("Authentication", "OIDC with RS256 JWT verification against the provider's keys; a production deploy refuses to start "
                       "without OIDC configured. Multi-factor policy is the identity provider's, not the platform's."),
    ("Tenant isolation", "Postgres row-level security with FORCE on tenant tables; firm and organisation are separate axes."),
    ("Audit integrity", "Per-tenant hash chain, database-level append-only trigger on Postgres, Ed25519-signed "
                        "checkpoints (when a signing key is configured), offline verification script."),
    ("Upload handling", "Size, filename, MIME sniff, extension agreement, allowlist, SHA-256 and a malware-scan hook "
                        "(ClamAV supported; the default scanner is a no-op)."),
    ("Roles and access", "Role-based access plus engagement scoping; read-only roles cannot write; unstaffed clients return 404."),
    ("Browser and operator", "Standard security headers on every response, and a Content-Security-Policy in report-only mode (not yet enforced). "
                             "Wrong operator keys are limited to ten per address in five minutes (ADR-065, ADR-066)."),
    ("Supply chain", "A weekly scan of known vulnerabilities in what ships (pip-audit, npm audit) and Dependabot update pull requests; "
                     "every change is a reviewed pull request behind a change-control gate."),
]
table(M, y, [112, W - 2 * M - 112], rows, size=8.3, pad=5)

# ------------------------------------------------------------------ page 5: benefits + deployment + boundaries
c.showPage(); chrome(9)
header_bar("Key Benefits")
ben = [
    ("Defensible results", ["A verdict names its rules, engine and inputs and can be replayed",
                            "The model never decides compliance"]),
    ("Evidence reuse", ["One upload satisfies several frameworks and yields precise, per-framework gaps",
                        "New versions resolve gaps and keep their history"]),
    ("Audit readiness", ["Append-only trail with before and after state and a reason",
                         "Auditor-held, signed checkpoints that outlive the platform's own word"]),
    ("Fits regulated work", ["Models can run locally or on your own host; storage is S3-compatible or local",
                             "Isolated tenants, firm and client axes"]),
    ("Faster remediation", ["Gaps become tasks automatically",
                            "Auditee and auditor talk inside the control, on the record"]),
]
y = table(M, H - 84, [118, W - 2 * M - 118], ben, size=8.8, pad=7)

y -= 18
header_bar("Deployment Model", y - 28)
y -= 36
dep = [
    ("Full stack, one command", "docker compose up brings up Postgres, MinIO (S3 storage), Ollama and the API serving the web app."),
    ("Managed pilot", "A Render blueprint: one web service with managed Postgres and S3-compatible storage (the live pilot uses Supabase for "
                      "both), the model hosted elsewhere; a separate stub-auth demo service for sharing, with throwaway data."),
    ("Your storage, your model", "S3-compatible object storage or local disk; Ollama, LM Studio or OpenAI-compatible endpoints."),
    ("Scheduled collection", "Expiry monitoring and connector sync run from cron, Task Scheduler or CI, and the customer's upload scripts from their own "
                             "scheduler or a GitHub Actions template; there is no in-process scheduler."),
]
y = table(M, y, [128, W - 2 * M - 128], dep, size=8.8, pad=7)

y -= 18
c.setFillColor(HexColor("#fff6e3"))
bh = 252
c.rect(M, y - bh, W - 2 * M, bh, fill=1, stroke=0)
c.setFillColor(AMBER)
c.rect(M, y - bh, 4, bh, fill=1, stroke=0)
text(M + 14, y - 17, "Boundaries — what this sheet does not claim", 10.5, "Helvetica-Bold", NAVY)
bullets(M + 14, y - 22, [
    f"{N_REQ} requirements are listed across {WORDS.get(N_FW, N_FW)} frameworks, but a rule judges only {N_RULE}; the other {N_ATT} (most of ISO 27001 and SOC 2) are a named person's attestation, which an auditor judges and the platform does not verify.",
    f"Of SOC 2, {N_CC} of the 33 Security (CC) criteria are listed; the availability, confidentiality, processing-integrity and privacy categories are covered only in part or not at all.",
    "Encryption at rest, backups and multi-factor sign-in depend on the hosting, storage and identity provider you choose.",
    "No third-party penetration test or security certification is claimed for the platform itself, and it has not had its own SOC 2 audit.",
    "The Content-Security-Policy is report-only: it reports violations and blocks nothing yet.",
    "The hosted pilot runs on free-tier hosting that sleeps when idle (a first request can take about a minute) and carries no uptime promise.",
    "The default malware scanner is a no-op; run ClamAV to scan uploads.",
    "Single web instance only: live updates, background uploads and request limits run in-process.",
    "Model-backed features (extraction, Ask AI, draft review help) need a reachable model. The hosted demo runs without one, so its evidence comes from collector snapshots.",
    "AWS, M365, Google Workspace and HRMS connectors have no totals to check against; completeness checks apply from the second run.",
], W - 2 * M - 28, 8.8, 3.4)

# ------------------------------------------------------------------ page 6: audience + CTA
c.showPage(); chrome(10)
header_bar("Who Should Use It?")
aud = [
    ("Audit firms", "Run client engagements with staffed auditors, scoped access and verdicts that lock."),
    ("Compliance officers", "See readiness by framework, every gap and the audit trail, read-only."),
    ("Security and IT teams", "Collect change-control and cloud evidence; fix gaps through assigned tasks."),
    ("AI governance leads", "Map AI policy and inventory evidence to NIST AI RMF alongside security frameworks."),
    ("Privacy teams", "Track DPDP readiness, breach events and data-subject requests."),
    ("Engineering leaders", "Gate merges on the same change-control rules the audit will apply."),
]
y = table(M, H - 84, [140, W - 2 * M - 140], aud, size=9, pad=7)

y -= 22
header_bar("See It In Action", y - 28)
y -= 42
y = para(M, y, "Two demos run. The live service has a read-only demo organisation anyone can look around: every change is refused. "
         "A separate demo has one-click personas for each of the five roles, on throwaway data that resets.", W - 2 * M, 9.4)
y -= 10
for i, (a, b) in enumerate([("Look around, read-only", f"https://{LIVE} — choose Try the demo on the sign-in page, no account"),
                            ("Play every role", f"https://{DEMO} — org admin, control owner, compliance viewer, auditor or firm admin"),
                            ("Read the source", f"https://{REPO} — start with the README and docs/adr")]):
    yy = y - i * 30
    c.setFillColor(CYAN)
    c.circle(M + 11, yy - 9, 10, fill=1, stroke=0)
    text(M + 7.5, yy - 12.4, str(i + 1), 10, "Helvetica-Bold", white)
    text(M + 30, yy - 7, a, 10, "Helvetica-Bold", NAVY)
    text(M + 30, yy - 19, b, 8.6, color=MUTED)
y -= 100
c.setFillColor(NAVY)
c.roundRect(M, y - 52, W - 2 * M, 52, 7, fill=1, stroke=0)
text(M + 18, y - 22, "The model reads. The rules decide. A human signs.", 13, "Helvetica-Bold", white)
text(M + 18, y - 39, "History is added to, never rewritten.", 10, color=CYAN)

c.save()
print("wrote", OUT)
