"""Upload validation. Uploaded files are untrusted input from a trust boundary,
so nothing here is skipped for brevity.

size -> filename sanitization -> MIME sniff -> extension/MIME agreement
-> allowlist -> SHA-256 -> malware scan.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import BinaryIO, Protocol

import filetype

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 25 * 1024 * 1024))
CHUNK = 1024 * 1024

# extension -> the MIME types we accept for it
ALLOWED: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".txt": {"text/plain"},
    ".csv": {"text/plain", "text/csv"},
}
TEXT_EXTENSIONS = {".txt", ".csv"}


class UploadRejected(Exception):
    """Rejected at the trust boundary. The message is safe to return to the caller."""


@dataclass(frozen=True)
class ValidatedUpload:
    data: bytes
    original_filename: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str


def sanitize_filename(name: str) -> str:
    """Defeat path traversal and control characters; keep something human-readable."""
    name = (name or "unnamed").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".")
    name = re.sub(r"_{2,}", "_", name)
    if not name:
        name = "unnamed"
    stem, dot, ext = name.rpartition(".")
    return (stem[:120] + dot + ext[:10]) if dot else name[:120]


def read_limited(stream: BinaryIO, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read at most limit+1 bytes so an oversized upload never lands in memory whole."""
    chunks, total = [], 0
    while True:
        chunk = stream.read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UploadRejected(f"file exceeds the {limit} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _looks_like_text(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sniff_mime(data: bytes, extension: str) -> str:
    kind = filetype.guess(data)
    if kind is not None:
        return kind.mime
    # filetype only knows binary signatures; text formats have none.
    if _looks_like_text(data):
        return "text/plain"
    return "application/octet-stream"


def validate_upload(stream: BinaryIO, original_filename: str) -> ValidatedUpload:
    filename = sanitize_filename(original_filename)
    extension = os.path.splitext(filename)[1].lower()

    if extension not in ALLOWED:
        raise UploadRejected(f"unsupported file type '{extension or filename}'")

    data = read_limited(stream)
    if not data:
        raise UploadRejected("file is empty")

    mime_type = sniff_mime(data, extension)
    if mime_type not in ALLOWED[extension]:
        raise UploadRejected(
            f"file content ({mime_type}) does not match its '{extension}' extension"
        )
    if extension in TEXT_EXTENSIONS and not _looks_like_text(data):
        raise UploadRejected(f"file content does not match its '{extension}' extension")

    return ValidatedUpload(
        data=data,
        original_filename=original_filename or filename,
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


# ----------------------------------------------------------------- malware scanning


class MalwareScanner(Protocol):
    def scan(self, data: bytes) -> None:
        """Raise UploadRejected when the payload is malicious."""


class NoopScanner:
    """Local/dev default. Deliberately does nothing and says so — it is not a
    claim that uploads are clean. Set MALWARE_SCANNER=clamav in deployments."""

    name = "noop"

    def scan(self, data: bytes) -> None:
        return None


class ClamAVScanner:
    """Talks to clamd over TCP (INSTREAM). Used when MALWARE_SCANNER=clamav."""

    name = "clamav"

    def __init__(self, host: str | None = None, port: int | None = None):
        self.host = host or os.environ.get("CLAMAV_HOST", "localhost")
        self.port = int(port or os.environ.get("CLAMAV_PORT", 3310))

    def scan(self, data: bytes) -> None:
        import socket
        import struct

        with socket.create_connection((self.host, self.port), timeout=30) as sock:
            sock.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), CHUNK):
                chunk = data[i:i + CHUNK]
                sock.sendall(struct.pack("!L", len(chunk)) + chunk)
            sock.sendall(struct.pack("!L", 0))
            response = sock.recv(4096).decode(errors="replace")
        if "FOUND" in response:
            raise UploadRejected(f"malware detected: {response.strip()}")


def get_scanner() -> MalwareScanner:
    if os.environ.get("MALWARE_SCANNER", "noop").lower() == "clamav":
        return ClamAVScanner()
    return NoopScanner()
