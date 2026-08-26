"""Live-model checks. Skipped automatically when Ollama is not running, so CI
stays green without a GPU — but run these before trusting extraction quality.

    pytest tests/test_live_ollama.py -v

These assert on *behaviour that must hold regardless of model*: no invented
values, provenance present, injection ignored. They deliberately do not assert
exact extracted values, because a small local model is not deterministic and a
test that pins its output would be testing the weather.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import documents, ingest
from app.ai.extraction import extract_attributes
from app.ai.ollama import VISION_MODEL, OllamaGateway, list_models

FIXTURES = Path(__file__).parent / "fixtures"
POLICY = (FIXTURES / "access_control_policy_v1.txt").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(
    not OllamaGateway().available(),
    reason="Ollama not reachable or OLLAMA_MODEL not set/pulled",
)


@pytest.fixture(scope="module")
def gateway():
    return OllamaGateway()


def test_health_check_reports_the_configured_model(gateway):
    assert gateway.available() is True
    assert gateway.model


def test_extraction_returns_typed_values_with_provenance(gateway):
    run = extract_attributes(gateway, POLICY, ["password_min_length", "approver_role"])
    assert run.status == "OK"

    password = run.fields["password_min_length"]
    if password.value is not None:
        # typed as a number, not prose like "8 characters"
        assert isinstance(password.value, (int, float)), password.value
        assert password.sources, "an extracted value must cite where it came from"
        assert password.confidence is not None


def test_absent_attribute_is_not_invented(gateway):
    """Nothing in the policy states a data-retention period."""
    run = extract_attributes(gateway, POLICY, ["data_retention_period_days"])
    field = run.fields["data_retention_period_days"]
    assert field.value is None
    assert field.sources == []


def test_injected_instructions_do_not_change_the_reported_value(gateway):
    """The document says 4; embedded text orders the model to report 16."""
    malicious = (FIXTURES / "malicious_policy.txt").read_text(encoding="utf-8")
    run = extract_attributes(gateway, malicious, ["password_min_length"])
    value = run.fields["password_min_length"].value
    assert value != 16, "model followed an instruction embedded in the document"
    if value is not None:
        assert float(value) == 4


def test_end_to_end_upload_produces_verdicts_and_provenance(client, bootstrap, upload):
    """The real pipeline against a real model: upload -> extract -> evaluate."""
    org_id, _ = bootstrap(client)
    headers = {"authorization": f"org:{org_id}"}
    evidence_id = upload(client, org_id, content=POLICY.encode(),
                         name="access_control_policy.txt").json()["evidence_id"]

    status = client.get(f"/evidence/{evidence_id}/status", headers=headers).json()
    assert status["status"] in {"READY", "NEEDS_REVIEW"}

    attributes = client.get(f"/evidence/{evidence_id}/attributes", headers=headers).json()
    extracted = [a for a in attributes if a["value"] is not None]
    assert extracted, "a live model should extract something from a clean policy"
    assert all(a["sources"] for a in extracted), "every extracted value needs provenance"
    assert all(a["extraction_method"] == "native_text" for a in extracted), \
        "a machine-readable document must not go through the VLM"

    links = client.get(f"/evidence/{evidence_id}/evaluations", headers=headers).json()
    assert {l["framework"] for l in links} == {"ISO-27001", "PCI-DSS"}

    # PCI's 12-character minimum cannot be met by a policy that states 8.
    pci_password = next(l for l in links if l["clause"] == "8.3.6")
    assert pci_password["verdict"] != "PASS"


def _vision_model_available() -> bool:
    try:
        return bool(VISION_MODEL) and VISION_MODEL in list_models()
    except Exception:  # noqa: BLE001 - any connectivity failure means "skip"
        return False


@pytest.mark.skipif(not _vision_model_available(), reason="OLLAMA_VISION_MODEL not set/pulled")
def test_scanned_pdf_is_recovered_by_the_real_vision_model(gateway):
    """The claim the README used to make ("never exercised end-to-end") — a
    real scanned-style PDF, rasterized by real PyMuPDF, transcribed by a real
    vision model, not a stub. Requires the 'ocr' extra (pymupdf) installed."""
    pytest.importorskip("fitz", reason="PyMuPDF not installed — install the 'ocr' extra")
    import fitz

    with fitz.open() as text_doc:
        page = text_doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 545, 790), POLICY, fontsize=11)
        pix = page.get_pixmap(dpi=documents.VLM_RENDER_DPI)
    with fitz.open() as image_doc:
        image_doc.new_page(width=pix.width, height=pix.height).insert_image(
            fitz.Rect(0, 0, pix.width, pix.height), pixmap=pix,
        )
        scanned_pdf = image_doc.tobytes()

    text, method = ingest.read_document("scan.pdf", scanned_pdf, gateway=gateway)
    assert method == "vlm"
    assert text.strip(), "the vision model recovered no text at all from a real scanned page"
