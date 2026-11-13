"""Package D: GSTR-2B file reading (G-40). Fixtures are hand-made, not portal files."""

import io
import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.importers.gstr2b import Gstr2bFileError, parse_gstr2b

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gstr2b" / "gstr2b_sample_042026.json"


def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def dump(obj) -> bytes:
    return json.dumps(obj).encode()


def reject(obj) -> str:
    with pytest.raises(Gstr2bFileError) as info:
        parse_gstr2b(obj if isinstance(obj, bytes) else dump(obj))
    return str(info.value)


def test_G40_json_sample_parses_three_documents_with_literal_values():
    parsed = parse_gstr2b(FIXTURE.read_bytes())
    assert parsed.recipient_gstin == "27AAPFU0939F1ZV"
    assert parsed.period == date(2026, 4, 1)
    assert parsed.generated_on == date(2026, 5, 14)
    first, second, note = parsed.documents
    assert (first.section, first.doc_type, first.doc_no, first.doc_date) == ("b2b", "invoice", "INV-001", date(2026, 4, 10))
    assert (first.taxable_value, first.igst, first.cgst, first.sgst, first.cess) == (D("1000.00"), D("180.00"), D("0.00"), D("0.00"), D("0.00"))
    assert first.itc_available == "yes" and first.supplier_return_period == date(2026, 4, 1)
    assert first.supplier_filing_date == date(2026, 5, 11) and first.row_no == 1
    assert (second.itc_available, second.itc_reason, second.igst) == ("no", "POS", D("360.00"))
    assert (note.section, note.doc_type, note.doc_no, note.taxable_value, note.row_no) == ("cdnr", "credit_note", "CN-01", D("100.00"), 3)


def test_G40_amounts_are_decimals_never_floats():
    parsed = parse_gstr2b(FIXTURE.read_bytes())
    assert all(isinstance(d.taxable_value, D) for d in parsed.documents)


def test_G40_amount_with_three_decimals_rejects_whole_file_naming_the_row():
    data = sample()
    data["data"]["docdata"]["b2b"][0]["inv"][1]["igst"] = 360.005
    message = reject(data)
    assert "row 2" in message and "INV-002" in message and "decimal" in message.lower()


def test_G40_bad_supplier_gstin_missing_number_negative_amount_each_rejected():
    data = sample()
    data["data"]["docdata"]["b2b"][0]["ctin"] = "NOTAGSTIN"
    assert "not a valid GSTIN" in reject(data)
    data = sample()
    del data["data"]["docdata"]["b2b"][0]["inv"][0]["inum"]
    assert "document number is missing" in reject(data)
    data = sample()
    data["data"]["docdata"]["b2b"][0]["inv"][0]["txval"] = -5
    assert "negative" in reject(data)


def test_G40_bad_date_and_bad_period_rejected():
    data = sample()
    data["data"]["docdata"]["b2b"][0]["inv"][0]["dt"] = "2026/13/45"
    assert "not a date" in reject(data)
    data = sample()
    data["data"]["rtnprd"] = "132026"
    assert "not a month" in reject(data)


def test_G40_unknown_shape_is_rejected_not_guessed():
    assert "'data' object" in reject({"hello": 1})
    assert "not valid JSON" in reject(b"{broken")
    data = sample()
    data["data"]["surprise"] = 1
    assert "Unknown key(s) in 'data': surprise" in reject(data)
    data = sample()
    data["data"]["docdata"]["xyz"] = []
    assert "Unknown section(s)" in reject(data)
    data = sample()
    data["data"]["docdata"]["b2b"][0]["inv"][0]["mystery"] = 1
    assert "unknown key(s) mystery" in reject(data)
    assert "neither" in reject(b"plain text")


def test_G40_section_not_yet_supported_is_rejected_when_it_holds_documents_but_empty_is_fine():
    data = sample()
    data["data"]["docdata"]["impg"] = []
    parse_gstr2b(dump(data))
    data["data"]["docdata"]["impg"] = [{"boenum": "1"}]
    assert "impg" in reject(data) and "real portal file" in reject(data)


def test_G40_note_type_must_be_c_or_d():
    data = sample()
    data["data"]["docdata"]["cdnr"][0]["nt"][0]["typ"] = "X"
    assert "note type" in reject(data)
    data = sample()
    data["data"]["docdata"]["cdnr"][0]["nt"][0]["typ"] = "D"
    assert parse_gstr2b(dump(data)).documents[2].doc_type == "debit_note"


def test_G40_every_problem_is_listed_not_only_the_first():
    data = sample()
    data["data"]["docdata"]["b2b"][0]["inv"][0]["txval"] = -5
    data["data"]["docdata"]["b2b"][0]["inv"][1]["dt"] = "bad"
    with pytest.raises(Gstr2bFileError) as info:
        parse_gstr2b(dump(data))
    assert [p.row for p in info.value.problems] == [1, 2]


def _excel(rows_b2b, gstin="27AAPFU0939F1ZV", header_extra=True) -> bytes:
    wb = Workbook()
    readme = wb.active
    readme.title = "Read me"
    readme.append(["GSTR-2B"])
    readme.append(["GSTIN", gstin])
    ws = wb.create_sheet("B2B")
    ws.append(["Goods and Services Tax - GSTR-2B"])
    ws.append(["GSTIN of supplier", "Trade/Legal name", "Invoice number", "Invoice type", "Invoice Date", "Invoice Value(Rs)",
               "Place of supply", "Supply Attract Reverse Charge", "Taxable Value (Rs)", "Integrated Tax(Rs)", "Central Tax(Rs)",
               "State/UT Tax(Rs)", "Cess(Rs)", "GSTR-1/IFF/GSTR-1A/5 Period", "GSTR-1/IFF/GSTR-1A/5 Filing Date",
               "ITC Availability", "Reason"])
    for row in rows_b2b:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


EXCEL_ROW = ["29AAACB1234C1Z5", "Bharat Traders", "INV-001", "Regular", "10-04-2026", 1180.0, "27", "No", 1000.0, 180.0, 0, 0, 0,
             "042026", "11-05-2026", "Yes", None]


def test_G40_excel_b2b_sheet_parses_with_recipient_from_read_me():
    parsed = parse_gstr2b(_excel([EXCEL_ROW]))
    assert parsed.source_format == "excel" and parsed.recipient_gstin == "27AAPFU0939F1ZV" and parsed.period is None
    doc = parsed.documents[0]
    assert (doc.doc_no, doc.doc_date, doc.taxable_value, doc.igst, doc.itc_available) == ("INV-001", date(2026, 4, 10), D("1000.00"), D("180.00"), "yes")
    assert doc.reverse_charge is False


def test_G40_excel_bad_row_names_the_sheet_row():
    bad = list(EXCEL_ROW)
    bad[8] = 1000.123
    message = reject(_excel([EXCEL_ROW, bad]))
    assert "row 4" in message and "decimal" in message.lower()


def test_G40_excel_without_recipient_or_known_sheets_rejected():
    wb = Workbook()
    wb.active.title = "Other"
    out = io.BytesIO()
    wb.save(out)
    assert "recipient GSTIN was not found" in reject(out.getvalue())
    assert "not a readable" in reject(b"PK\x03\x04junk")

