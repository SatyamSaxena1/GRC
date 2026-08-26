"""Upload is a trust boundary. These are the checks that keep it one."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.upload_security import (
    MAX_UPLOAD_BYTES, UploadRejected, read_limited, sanitize_filename, validate_upload,
)

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<</Type/Catalog>>\nendobj\ntrailer\n%%EOF\n"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452") + b"\x00" * 64


def docx_bytes() -> bytes:
    """Minimal OOXML container — enough for signature sniffing to see a zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<document/>")
    return buf.getvalue()


@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "passwd"),  # basename only: the path is discarded, not escaped
    ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
    ("/absolute/path/policy.pdf", "policy.pdf"),
    ("weird name!@#$.pdf", "weird_name_.pdf"),
    ("", "unnamed"),
    ("...", "unnamed"),
])
def test_filename_sanitization_defeats_traversal(raw, expected):
    assert sanitize_filename(raw) == expected


def test_oversized_upload_is_rejected_without_buffering_everything():
    oversized = io.BytesIO(b"x" * (MAX_UPLOAD_BYTES + 1024))
    with pytest.raises(UploadRejected, match="exceeds"):
        read_limited(oversized)


def test_extension_not_on_allowlist_is_rejected():
    with pytest.raises(UploadRejected, match="unsupported"):
        validate_upload(io.BytesIO(b"MZ\x90\x00"), "payload.exe")


def test_content_must_match_extension():
    """A PNG renamed to .pdf is a mismatch, not a PDF."""
    with pytest.raises(UploadRejected, match="does not match"):
        validate_upload(io.BytesIO(PNG), "actually_an_image.pdf")


def test_binary_disguised_as_txt_is_rejected():
    with pytest.raises(UploadRejected, match="does not match"):
        validate_upload(io.BytesIO(PNG), "notes.txt")


def test_empty_file_is_rejected():
    with pytest.raises(UploadRejected, match="empty"):
        validate_upload(io.BytesIO(b""), "empty.pdf")


@pytest.mark.parametrize("data,name", [
    (PDF, "policy.pdf"),
    (PNG, "screenshot.png"),
    (b"plain text policy", "policy.txt"),
    (b"a,b\n1,2\n", "data.csv"),
    (docx_bytes(), "policy.docx"),
])
def test_valid_uploads_are_accepted_and_hashed(data, name):
    result = validate_upload(io.BytesIO(data), name)
    assert result.size_bytes == len(data)
    assert len(result.sha256) == 64
    assert result.filename == name


def test_sha256_is_recorded_on_upload(client, bootstrap, upload):
    import hashlib

    org_id, _ = bootstrap(client)
    content = b"an access control policy"
    evidence_id = upload(client, org_id, content=content).json()["evidence_id"]
    detail = client.get(f"/evidence/{evidence_id}",
                        headers={"authorization": f"org:{org_id}"}).json()
    assert detail["sha256"] == hashlib.sha256(content).hexdigest()


def test_duplicate_upload_is_detected(client, bootstrap, upload):
    org_id, _ = bootstrap(client)
    content = b"an access control policy"
    first = upload(client, org_id, content=content)
    assert first.status_code == 202

    second = upload(client, org_id, content=content)
    assert second.status_code == 409
    assert second.json()["detail"]["evidence_id"] == first.json()["evidence_id"]


def test_rejected_upload_creates_no_evidence_row(client, bootstrap, db):
    from app.models import Evidence

    org_id, _ = bootstrap(client)
    resp = client.post("/evidence", headers={"authorization": f"org:{org_id}"},
                       files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert resp.status_code == 400

    from sqlalchemy.orm import Session
    from app import db as db_module
    with Session(db_module.engine) as s:
        assert s.query(Evidence).count() == 0


def test_storage_refuses_to_overwrite_an_existing_object(tmp_path):
    from app.storage import LocalStorage

    storage = LocalStorage(str(tmp_path))
    storage.put("tenant/a/evidence/e/v1/policy.pdf", b"v1 bytes")
    with pytest.raises(FileExistsError):
        storage.put("tenant/a/evidence/e/v1/policy.pdf", b"different bytes")
    assert storage.get("tenant/a/evidence/e/v1/policy.pdf") == b"v1 bytes"
