"""Package B: Tally export text (D-38, D-39). Hand-typed expectations; the round trip uses the strict reader."""

from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("defusedxml")

from app.engine.tally_export import (
    ExportGroup,
    ExportHeader,
    ExportLedger,
    ExportLine,
    ExportVoucher,
    build_export,
)
from app.importers.tally_xml import parse_tally_xml

D = Decimal
HEADER = ExportHeader("Test & Sons <Traders>", "2026-27", date(2026, 4, 1), date(2027, 3, 31), "both")


def sale(**kw):
    base = {"voucher_type": "sales", "voucher_date": date(2026, 4, 15), "number": "SAL/2026-27/0001", "narration": "Goods to Rahul",
                "reference_no": "INV-1", "party_ledger": "Rahul & Co",
                "lines": (ExportLine("Rahul & Co", D("11800.00"), D("0.00")), ExportLine("Sales", D("0.00"), D("10000.00")),
                       ExportLine("Output IGST", D("0.00"), D("1800.00")))}
    base.update(kw)
    return ExportVoucher(**base)


def test_D38_debit_is_negative_yes_and_credit_positive_no():
    xml = build_export(HEADER, [], [], [sale()]).xml
    assert ("<LEDGERNAME>Rahul &amp; Co</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-11800.00</AMOUNT>") in xml
    assert ("<LEDGERNAME>Sales</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>10000.00</AMOUNT>") in xml
    assert "<DATE>20260415</DATE>" in xml and '<VOUCHER VCHTYPE="Sales" ACTION="Create">' in xml


def test_D38_masters_come_before_vouchers_and_groups_before_ledgers():
    xml = build_export(HEADER, [ExportGroup("Retail Debtors", "Sundry Debtors")], [ExportLedger("Rahul & Co", "Retail Debtors")],
                       [sale()]).xml
    assert xml.index("<GROUP ") < xml.index("<LEDGER ") < xml.index("<VOUCHER ")


def test_D38_header_records_client_year_range_and_version():
    xml = build_export(HEADER, [], [], [sale()]).xml
    assert "financial year: 2026-27" in xml and "range: 2026-04-01 to 2027-03-31" in xml and "engine tally-export-1" in xml
    assert "<SVCURRENTCOMPANY>Test &amp; Sons &lt;Traders&gt;</SVCURRENTCOMPANY>" in xml


def test_D38_names_are_escaped_and_file_reads_back_with_same_values():
    result = build_export(HEADER, [ExportGroup('Q "x" <y>', "Sundry Debtors")], [ExportLedger("O'Neil & Sons", 'Q "x" <y>')],
                          [sale(narration="a < b & c")])
    back = parse_tally_xml(result.xml.encode("utf-8"))
    assert (back.groups[0].name, back.groups[0].parent) == ('Q "x" <y>', "Sundry Debtors")
    assert back.ledgers[0].name == "O'Neil & Sons"
    v = back.vouchers[0]
    assert (v.number, v.reference, v.party_ledger, v.narration) == ("SAL/2026-27/0001", "INV-1", "Rahul & Co", "a < b & c")
    assert [(e.ledger_name, e.amount, e.deemed_positive) for e in v.entries] == [
        ("Rahul & Co", D("-11800.00"), True), ("Sales", D("10000.00"), False), ("Output IGST", D("1800.00"), False)]
    assert (result.master_count, result.voucher_count) == (2, 1)


def test_D39_long_name_and_illegal_character_are_reported_not_hidden():
    long_name = "L" * 120
    result = build_export(HEADER, [], [ExportLedger(long_name, "Sundry Debtors"), ExportLedger("Bad\x04Name", "Sundry Debtors")], [])
    assert any("120 characters" in w for w in result.warnings)
    assert any("'BadName'" in w and "character that XML cannot hold" in w for w in result.warnings)
    assert long_name in result.xml  # never shortened


def test_D39_duplicate_names_differing_by_case_are_reported():
    result = build_export(HEADER, [], [ExportLedger("Cash", "Cash-in-hand"), ExportLedger("CASH", "Cash-in-hand")], [])
    assert any("appears twice" in w for w in result.warnings)


def test_D38_credit_note_type_name():
    xml = build_export(HEADER, [], [], [sale(voucher_type="credit_note")]).xml
    assert 'VCHTYPE="Credit Note"' in xml
