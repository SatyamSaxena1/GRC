"""Native extraction per format, with source location kept.

Native text first, always. The VLM is a fallback for documents native parsing
cannot read — and the decision to fall back is made here by deterministic
heuristics, never by asking a model whether it needs OCR.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import string
from dataclasses import dataclass

logger = logging.getLogger("app.documents")

# A text page below this many characters is treated as unreadable natively.
MIN_CHARS_PER_PAGE = 100
# Fraction of pages that must be readable for the document to skip the VLM.
MIN_READABLE_PAGE_RATIO = 0.6
# Below this fraction of printable characters, treat a page as unreadable even
# when it has enough characters — catches mojibake from a bad encoding or a
# corrupted font mapping, which a length-only check lets straight through.
MIN_PRINTABLE_RATIO = 0.6
_PRINTABLE = set(string.printable)

# Rasterization resolution for pages the VLM has to read. A named, tunable
# constant rather than a hidden guess, per ADR-008.
VLM_RENDER_DPI = int(os.environ.get("VLM_RENDER_DPI", "200"))


@dataclass(frozen=True)
class DocumentPage:
    page_number: int
    text: str
    source_type: str = "native"  # native | vlm
    source_ref: str = ""         # sheet!cell range, or "" for paged formats


def _pdf_pages(data: bytes) -> list[DocumentPage]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return [
        DocumentPage(page_number=i + 1, text=page.extract_text() or "")
        for i, page in enumerate(reader.pages)
    ]


def is_encrypted_pdf(filename: str, data: bytes) -> bool:
    """True when a PDF requires a password to open at all.

    Checked once, upfront (app/service.py), independent of parse()/read_document
    — a locked file's extraction result is empty for a completely different
    reason than a scan needing OCR or a model being unavailable, and deserves an
    honest "this file is password-protected" rather than masquerading as either
    of those. Never raises: an unreadable/corrupt file is `parse()`'s problem,
    not this check's — a false `False` here just means the ordinary path runs
    and reports its own failure.
    """
    if not filename.lower().endswith(".pdf"):
        return False
    try:
        from pypdf import PdfReader

        return bool(PdfReader(io.BytesIO(data)).is_encrypted)
    except Exception:  # noqa: BLE001 - answer "not encrypted" rather than crash the pipeline
        return False


def _docx_pages(data: bytes) -> list[DocumentPage]:
    """DOCX has no page concept until rendered; paragraphs and tables become one
    logical page, with table cells kept as pipe-joined rows."""
    import docx

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return [DocumentPage(page_number=1, text="\n".join(parts))]


def _xlsx_pages(data: bytes) -> list[DocumentPage]:
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    pages = []
    for index, sheet in enumerate(workbook.worksheets, start=1):
        lines = []
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    lines.append(f"{sheet.title}!{cell.coordinate}: {cell.value}")
        pages.append(DocumentPage(
            page_number=index, text="\n".join(lines), source_ref=sheet.title
        ))
    workbook.close()
    return pages


def _csv_pages(data: bytes) -> list[DocumentPage]:
    text = data.decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    lines = [f"row {i}: " + " | ".join(r) for i, r in enumerate(rows, start=1) if any(r)]
    return [DocumentPage(page_number=1, text="\n".join(lines))]


def _text_pages(data: bytes) -> list[DocumentPage]:
    return [DocumentPage(page_number=1, text=data.decode("utf-8", errors="replace"))]


PARSERS = {
    ".pdf": _pdf_pages,
    ".docx": _docx_pages,
    ".xlsx": _xlsx_pages,
    ".csv": _csv_pages,
    ".txt": _text_pages,
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def parse(filename: str, data: bytes) -> list[DocumentPage]:
    """Native parse. Images return an empty page list — they have no native text
    and must go through the VLM."""
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension in IMAGE_EXTENSIONS:
        return []
    parser = PARSERS.get(extension, _text_pages)
    try:
        return parser(data)
    except Exception as exc:  # a corrupt/unsupported file is not a crash
        logger.warning("native_parse_failed ext=%s error=%s", extension, exc)
        return []


def _page_unreadable(page: DocumentPage) -> bool:
    """A page counts as unreadable when it's too short, or long enough but
    mostly non-printable (the signature of a bad encoding, not a scan) — the
    single check both needs_vision() and pages_needing_vision() key off, so
    the two can't drift out of sync with each other."""
    text = page.text.strip()
    if len(text) < MIN_CHARS_PER_PAGE:
        return True
    printable = sum(1 for c in text if c in _PRINTABLE)
    return (printable / len(text)) < MIN_PRINTABLE_RATIO


def needs_vision(filename: str, pages: list[DocumentPage]) -> bool:
    """Deterministic: images always, empty parses always, and paged documents
    whose pages came back mostly empty or unreadable (the signature of a
    scanned PDF or a bad encoding)."""
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension in IMAGE_EXTENSIONS:
        return True
    if not pages:
        return True
    readable = sum(1 for p in pages if not _page_unreadable(p))
    return (readable / len(pages)) < MIN_READABLE_PAGE_RATIO


def pages_needing_vision(pages: list[DocumentPage]) -> list[int]:
    """Only the unreadable pages get rasterized — never the whole document."""
    return [p.page_number for p in pages if _page_unreadable(p)]


def render_pdf_page(data: bytes, page_number: int, dpi: int = VLM_RENDER_DPI) -> bytes | None:
    """PNG bytes for one PDF page, or None when no renderer is installed.
    pypdf cannot rasterize, so this needs PyMuPDF; absence degrades to
    'no vision fallback', never to a crash."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("pdf_render_unavailable — install pymupdf for scanned-PDF support")
        return None
    with fitz.open(stream=data, filetype="pdf") as doc:
        page = doc[page_number - 1]
        return page.get_pixmap(dpi=dpi).tobytes("png")


def to_text(pages: list[DocumentPage]) -> str:
    """Flatten with page markers so extracted quotes stay attributable."""
    return "\n".join(
        f"[page {p.page_number}{('/' + p.source_ref) if p.source_ref else ''}]\n{p.text}"
        for p in pages
    )
