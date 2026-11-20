"""Package A, no database: D-01 file checks, D-02 storage key safety, private store, direct PDF text reading, OCR adapters."""

import hashlib
import io

import pytest

from app.ai import ocr
from app.ai.storage import PrivateStore
from app.engine import doc_files
from app.services.errors import ServiceError

pytest.importorskip("pypdf")
reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 20
TIFF = b"II*\x00" + b"0" * 20
XML = b'<?xml version="1.0"?><ENVELOPE/>'
MB = 1024 * 1024


def make_pdf(pages: list[str]) -> bytes:
    buf = io.BytesIO()
    c = reportlab_canvas.Canvas(buf)
    for text in pages:
        if text:
            c.drawString(72, 750, text)
        c.showPage()
    c.save()
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ D-01 file type by content


def test_D01_type_is_decided_by_content_not_by_name():
    assert doc_files.sniff_content_type(make_pdf(["x"])) == "application/pdf"
    assert doc_files.sniff_content_type(PNG) == "image/png"
    assert doc_files.sniff_content_type(JPEG) == "image/jpeg"
    assert doc_files.sniff_content_type(TIFF) == "image/tiff"
    assert doc_files.sniff_content_type(XML) == "application/xml"
    assert doc_files.sniff_content_type("<ENVELOPE/>".encode("utf-16")) == "application/xml"
    assert doc_files.sniff_content_type(b"MZ\x90\x00 an executable") is None
    assert doc_files.sniff_content_type(b"plain text") is None


def test_D01_an_exe_renamed_to_pdf_is_rejected_and_empty_and_too_large_files_too():
    assert not doc_files.check_upload(b"MZ\x90\x00 program", "purchase_invoice", 15 * MB).ok
    empty = doc_files.check_upload(b"", "purchase_invoice", 15 * MB)
    assert not empty.ok and "empty" in empty.reason
    big = doc_files.check_upload(PNG + b"0" * (2 * MB), "other", 1 * MB)
    assert not big.ok and "1 MB" in big.reason
    assert doc_files.check_upload(PNG, "other", 1 * MB) == doc_files.FileCheck(True, "image/png", "png")


def test_D01_xml_only_for_tally_documents_and_images_not_for_tally():
    assert doc_files.check_upload(XML, "tally_xml", 15 * MB).ok
    assert doc_files.check_upload(XML, "tally_export", 15 * MB).ok
    assert not doc_files.check_upload(XML, "purchase_invoice", 15 * MB).ok
    assert not doc_files.check_upload(PNG, "tally_xml", 15 * MB).ok


# ------------------------------------------------------------------------------------------------ D-02 hash and key safety


def test_D02_sha256_matches_the_known_digest_of_abc():
    assert doc_files.sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert doc_files.sha256_hex(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_D02_generated_key_has_no_part_of_the_uploaded_name():
    key = doc_files.storage_key("0F5A7C1E-0000-4000-8000-000000000001", "a" * 64, "pdf")
    assert key == "0f5a7c1e-0000-4000-8000-000000000001/" + "a" * 64 + ".pdf"
    assert doc_files.clean_filename("..\\..\\windows\\evil.pdf") == "evil.pdf"
    assert doc_files.clean_filename("/etc/passwd") == "passwd"
    assert doc_files.clean_filename("  ") == "document"
    assert doc_files.clean_filename("a\x00b.pdf") == "ab.pdf"


@pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path.pdf", "C:/files/a.pdf", "a//b.pdf", "a/../b.pdf", "UPPER/a.pdf", "dir/",
                                 "a\\b.pdf", "", "..", "a/b/..", "c:\\x.pdf"])
def test_D02_unsafe_keys_are_refused(key):
    assert not doc_files.is_safe_key(key)


def test_D02_safe_keys_are_accepted():
    assert doc_files.is_safe_key("abc/" + "0" * 64 + ".pdf")


# ------------------------------------------------------------------------------------------------ private store


def test_D02_store_saves_reads_streams_and_leaves_no_temp_files(tmp_path):
    store = PrivateStore(tmp_path / "docs")
    key = "c1/" + "1" * 64 + ".pdf"
    store.save(key, b"hello")
    assert store.exists(key)
    assert store.read(key) == b"hello"
    assert b"".join(store.open(key)) == b"hello"
    assert [p.name for p in (tmp_path / "docs" / "c1").iterdir()] == ["1" * 64 + ".pdf"]


def test_D02_store_refuses_traversal_keys_before_touching_the_disk(tmp_path):
    store = PrivateStore(tmp_path / "docs")
    for key in ["../outside.pdf", "/etc/passwd", "C:/x.pdf", "a/../../b.pdf"]:
        for call in (lambda k=key: store.save(k, b"x"), lambda k=key: store.read(k), lambda k=key: store.exists(k)):
            with pytest.raises(ServiceError) as err:
                call()
            assert err.value.code == "invalid_storage_key"
    assert not (tmp_path / "outside.pdf").exists()


def test_D02_store_refuses_a_symlink_that_leaves_the_root(tmp_path):
    root, outside = tmp_path / "docs", tmp_path / "secret"
    outside.mkdir()
    (outside / "x.pdf").write_bytes(b"secret")
    (root / "c1").mkdir(parents=True)
    try:
        (root / "c1" / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted on this machine")
    with pytest.raises(ServiceError) as err:
        PrivateStore(root).read("c1/link/x.pdf")
    assert err.value.code == "invalid_storage_key"


def test_D01_store_without_a_folder_says_store_unavailable():
    for root in (None, "", "  "):
        with pytest.raises(ServiceError) as err:
            PrivateStore(root)
        assert err.value.code == "store_unavailable" and "DOCUMENT_STORE_DIR" in err.value.message


def test_D01_store_unwritable_root_says_store_unavailable(tmp_path):
    blocker = tmp_path / "file-not-folder"
    blocker.write_bytes(b"x")
    with pytest.raises(ServiceError) as err:
        PrivateStore(blocker).save("c1/" + "2" * 64 + ".pdf", b"x")
    assert err.value.code == "store_unavailable"


# ------------------------------------------------------------------------------------------------ direct PDF reading


def test_D01_text_pdf_is_read_directly_page_by_page():
    pages = ocr.PdfTextReader().read_pages(make_pdf(["Invoice B-101 Total 1,180.00", "Page two Supplier ABC"]))
    assert [(p.page_no, p.method) for p in pages] == [(1, "pdf_text"), (2, "pdf_text")]
    assert "Invoice B-101 Total 1,180.00" in pages[0].text
    assert "Supplier ABC" in pages[1].text
    assert pages[0].engine_version.startswith("pypdf-") and pages[0].mean_confidence is None


def test_D01_a_page_without_a_text_layer_comes_back_empty_not_guessed():
    pages = ocr.PdfTextReader().read_pages(make_pdf(["", "Has text"]))
    assert pages[0].text == "" and "Has text" in pages[1].text


def test_D01_page_count_and_unreadable_pdfs():
    assert ocr.pdf_page_count(make_pdf(["a", "b", "c"])) == 3
    for bad in (b"%PDF-1.4 this is not a pdf", b"%PDF-"):
        with pytest.raises(ServiceError) as err:
            ocr.pdf_page_count(bad)
        assert err.value.code == "file_rejected"


def test_D01_password_protected_pdf_is_rejected():
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(make_pdf(["secret"]))).pages:
        writer.add_page(page)
    writer.encrypt("pw")
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(ServiceError) as err:
        ocr.pdf_page_count(out.getvalue())
    assert err.value.code == "file_rejected" and "password" in err.value.message


def test_D01_direct_reader_refuses_images():
    with pytest.raises(ServiceError) as err:
        ocr.PdfTextReader().read_pages(PNG, "image/png")
    assert err.value.code == "invalid_method"


# ------------------------------------------------------------------------------------------------ OCR adapters (optional libraries)


def test_D01_ocr_engines_fail_clearly_when_the_library_is_missing(monkeypatch):
    monkeypatch.setattr(ocr, "_have", lambda module: False)
    for method, hint in (("tesseract", "Tesseract"), ("paddleocr", "PaddleOCR")):
        with pytest.raises(ServiceError) as err:
            ocr.ocr_for(method).read_pages(PNG, "image/png")
        assert err.value.code == "ocr_unavailable" and hint in err.value.message and "pip install" in err.value.message
    assert ocr.available_ocr() == []


def test_D01_tesseract_program_missing_is_reported_even_if_the_python_package_is_there(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("pytesseract")

    def no_program():
        raise RuntimeError("tesseract is not installed")

    fake.get_tesseract_version = no_program
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setattr(ocr, "_have", lambda module: module == "pytesseract")
    with pytest.raises(ServiceError) as err:
        ocr.TesseractOcr().read_pages(PNG, "image/png")
    assert err.value.code == "ocr_unavailable" and "program was not found" in err.value.message


def test_D01_unknown_ocr_method_is_refused():
    with pytest.raises(ServiceError) as err:
        ocr.ocr_for("magic")
    assert err.value.code == "invalid_method"
    with pytest.raises(ServiceError) as err2:
        ocr.ocr_for("pdf_text")
    assert err2.value.code == "invalid_method"
