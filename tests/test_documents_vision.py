"""Exercises the real render_pdf_page -> VLM path the README names as
"never exercised end-to-end" — not just the routing heuristic (already
covered in tests/test_extraction.py), the actual fitz rasterization and the
merge back into read_document(). Skipped automatically when PyMuPDF isn't
installed (it's an optional extra, see pyproject.toml's `ocr` group).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import documents, ingest

pytest.importorskip("fitz", reason="PyMuPDF not installed — install the 'ocr' extra")
import fitz  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def scanned_pdf_bytes(text: str) -> bytes:
    """Builds a real image-only PDF (no extractable text layer) by rendering
    `text` onto a page, rasterizing it, then embedding only the raster image
    into a fresh page — the same shape as a real scanned document."""
    with fitz.open() as text_doc:
        page = text_doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 545, 790), text, fontsize=11)
        pix = page.get_pixmap(dpi=150)

    with fitz.open() as image_doc:
        image_page = image_doc.new_page(width=pix.width, height=pix.height)
        image_page.insert_image(fitz.Rect(0, 0, pix.width, pix.height), pixmap=pix)
        return image_doc.tobytes()


class StubVisionGateway:
    """Scripts one transcription per call, mirroring StubGateway in
    tests/test_extraction.py but for complete_vision instead of complete_json."""
    provider = "stub"
    model = "stub-vision-model"

    def __init__(self, transcriptions: list[str]):
        self.transcriptions = list(transcriptions)
        self.images_seen: list[bytes] = []

    def available(self) -> bool:
        return True

    def complete_vision(self, system, user, images):
        self.images_seen.append(images[0])
        if not self.transcriptions:
            raise RuntimeError("no more scripted transcriptions")
        return self.transcriptions.pop(0)


def test_render_pdf_page_returns_real_png_bytes():
    pdf = scanned_pdf_bytes("Access Control Policy\nMinimum password length: 12 characters.")
    image = documents.render_pdf_page(pdf, page_number=1)

    assert image is not None
    assert image[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes — a real image came back


def test_render_pdf_page_indexes_pages_correctly():
    """page_number is 1-based at this API's boundary; fitz's doc[...] is
    0-based internally (render_pdf_page does page_number - 1) — page 2 here
    must render the second page's content, not the first's."""
    with fitz.open() as doc:
        doc.new_page().insert_textbox(fitz.Rect(50, 50, 545, 790), "PAGE ONE")
        doc.new_page().insert_textbox(fitz.Rect(50, 50, 545, 790), "PAGE TWO")
        data = doc.tobytes()

    page1 = documents.render_pdf_page(data, page_number=1)
    page2 = documents.render_pdf_page(data, page_number=2)
    assert page1 is not None and page2 is not None
    assert page1 != page2  # different content must rasterize to different bytes


def test_read_document_recovers_text_via_the_real_vision_path():
    """The actual gap the README names: a scanned PDF goes all the way
    through parse -> needs_vision -> render_pdf_page (real fitz) ->
    complete_vision (stubbed) -> merged text, and read_document reports it."""
    pdf = scanned_pdf_bytes("Access Control Policy\nMinimum password length: 12 characters.")
    gateway = StubVisionGateway(["Access Control Policy\nMinimum password length: 12 characters."])

    text, method = ingest.read_document("scan.pdf", pdf, gateway=gateway)

    assert method == "vlm"
    assert "Minimum password length: 12 characters" in text
    assert "[page 1]" in text
    assert gateway.images_seen and gateway.images_seen[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_read_document_leaves_readable_pages_alone_and_only_renders_unreadable_ones():
    """A mixed document: one real text page, one scanned page. Only the
    scanned page should trigger a render_pdf_page/complete_vision call."""
    with fitz.open() as doc:
        doc.new_page().insert_text((50, 72), "Readable native text. " * 20)
        text_only_pdf = doc.tobytes()  # sanity: this page has a real text layer

    scanned = scanned_pdf_bytes("Scanned page content: retention period 90 days.")

    with fitz.open(stream=text_only_pdf, filetype="pdf") as native_doc, \
         fitz.open(stream=scanned, filetype="pdf") as scan_doc:
        combined = fitz.open()
        combined.insert_pdf(native_doc)
        combined.insert_pdf(scan_doc)
        combined_bytes = combined.tobytes()

    gateway = StubVisionGateway(["Scanned page content: retention period 90 days."])
    text, method = ingest.read_document("mixed.pdf", combined_bytes, gateway=gateway)

    assert method == "vlm"
    assert "Readable native text" in text
    assert "retention period 90 days" in text
    assert len(gateway.images_seen) == 1  # only the scanned page was rasterized
