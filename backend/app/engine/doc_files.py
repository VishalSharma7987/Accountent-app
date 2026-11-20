"""File checks of the document intake (rule D-01 and the storage-key safety behind D-02). Pure Python: no DB, web, LLM or OCR imports.

The type of an uploaded file is decided from its first bytes, never from its name or the content type the browser claims.
The stored name is generated from client id + SHA-256; the original name is kept only as (sanitised) metadata.
"""

import hashlib
import re
from dataclasses import dataclass

XML_DOC_TYPES = ("tally_xml", "tally_export")
EXTENSION = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/tiff": "tif", "application/xml": "xml"}
IMAGE_TYPES = ("image/png", "image/jpeg", "image/tiff")

_SAFE_KEY = re.compile(r"^[a-z0-9][a-z0-9_./-]*$")  # same shape as the database CHECK documents_storage_key_safe


@dataclass(frozen=True)
class FileCheck:
    ok: bool
    content_type: str | None = None
    extension: str | None = None
    reason: str | None = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_content_type(data: bytes) -> str | None:
    """PDF, PNG, JPEG, TIFF or XML by content; None when the bytes are none of them."""
    head = data[:2048]
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if _looks_like_xml(head):
        return "application/xml"
    return None


def _looks_like_xml(head: bytes) -> bool:
    for bom, encoding in ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if head.startswith(bom):
            body = head[len(bom):]
            body = body[: len(body) // 2 * 2] if encoding.startswith("utf-16") else body
            try:
                return body.decode(encoding, errors="ignore").lstrip().startswith("<")
            except UnicodeError:
                return False
    return head.lstrip().startswith((b"<?xml", b"<"))


def check_upload(data: bytes, doc_type: str, max_bytes: int) -> FileCheck:
    """D-01: not empty, within the size limit, and of a type that fits the document type (XML only for Tally documents)."""
    if not data:
        return FileCheck(False, reason="The file is empty.")
    if len(data) > max_bytes:
        return FileCheck(False, reason=f"The file is larger than the limit of {max_bytes // (1024 * 1024)} MB.")
    found = sniff_content_type(data)
    wants_xml = doc_type in XML_DOC_TYPES
    if found is None or (found == "application/xml") != wants_xml:
        allowed = "an XML file" if wants_xml else "a PDF, PNG, JPEG or TIFF file"
        return FileCheck(False, reason=f"This document type needs {allowed}; the content of the file is something else (D-01).")
    return FileCheck(True, content_type=found, extension=EXTENSION[found])


def storage_key(client_id: object, sha256: str, extension: str) -> str:
    """Generated key: <client id>/<sha256>.<ext>. Nothing from the uploaded file name is used."""
    key = f"{str(client_id).lower()}/{sha256}.{extension}"
    if not is_safe_key(key):
        raise ValueError("generated storage key is not safe")
    return key


def is_safe_key(key: str) -> bool:
    """No '..', no leading '/', no drive letter, no '//', no backslash, no trailing '/', lower-case simple characters only."""
    return bool(_SAFE_KEY.fullmatch(key)) and ".." not in key and "//" not in key and not key.endswith("/")


def clean_filename(name: str | None) -> str:
    """Original name as metadata: directory parts and control characters removed; never used as a path."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().strip(".")
    return (base or "document")[:200]
