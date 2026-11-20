"""Package B: strict Tally XML reader (D-30, D-35, D-36). Synthetic, hand-written XML only. Expected values typed literally."""

import codecs
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("defusedxml")

from app.importers.tally_xml import TallyParseError, parse_tally_xml

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "tally" / "sample_company.xml"


def wrap(inner: str, head: str = '<?xml version="1.0" encoding="UTF-8"?>') -> bytes:
    return (f"{head}<ENVELOPE><BODY><IMPORTDATA><REQUESTDATA><TALLYMESSAGE>{inner}</TALLYMESSAGE>"
            "</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>").encode()


def voucher(entries: str, extra: str = "", date_text: str = "20260415") -> str:
    return (f'<VOUCHER VCHTYPE="Journal"><DATE>{date_text}</DATE><VOUCHERNUMBER>9</VOUCHERNUMBER>{extra}{entries}</VOUCHER>')


def entry(name="Cash", amount="-10.00", deemed="Yes", tag="ALLLEDGERENTRIES.LIST") -> str:
    return (f"<{tag}><LEDGERNAME>{name}</LEDGERNAME><ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE>"
            f"<AMOUNT>{amount}</AMOUNT></{tag}>")


def test_D30_sample_file_is_read_with_counts_and_values():
    tally = parse_tally_xml(FIXTURE.read_bytes())
    assert tally.company_name == "Synthetic Traders (Test)"
    assert (len(tally.groups), len(tally.ledgers), len(tally.stock_items), len(tally.vouchers)) == (2, 8, 2, 7)
    assert tally.ignored == {"UNIT": 1}
    rahul = next(x for x in tally.ledgers if x.name == "Rahul Enterprises")
    assert (rahul.parent, rahul.opening_balance) == ("Retail Debtors", "-12000.00")
    widget = next(x for x in tally.stock_items if x.name == "Widget")
    assert (widget.unit, widget.hsn) == ("Nos", "8471")
    sale = tally.vouchers[0]
    assert (sale.voucher_type, sale.voucher_date, sale.number, sale.guid) == ("Sales", date(2026, 4, 15), "1", "guid-sales-1")
    assert [(e.ledger_name, e.amount, e.deemed_positive) for e in sale.entries] == [
        ("Rahul Enterprises", Decimal("-11800.00"), True), ("Sales - Goods", Decimal("10000.00"), False),
        ("Output IGST", Decimal("1800.00"), False)]
    assert sale.entries[0].bill_allocations == 1


def test_D36_cancelled_optional_flags_are_read():
    tally = parse_tally_xml(FIXTURE.read_bytes())
    flags = {v.guid: (v.is_cancelled, v.is_optional) for v in tally.vouchers}
    assert flags["guid-sales-cancelled"] == (True, False)
    assert flags["guid-rec-optional"] == (False, True)
    assert flags["guid-sales-1"] == (False, False)


def test_D30_dtd_and_entities_are_refused():
    xml = (b'<?xml version="1.0"?><!DOCTYPE ENVELOPE [<!ENTITY x "boom">]><ENVELOPE><BODY><IMPORTDATA><REQUESTDATA>'
           b"<TALLYMESSAGE><LEDGER NAME=\"&x;\"/></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    with pytest.raises(TallyParseError, match="DTD or entity"):
        parse_tally_xml(xml)


def test_D30_not_well_formed_is_refused_with_reason():
    with pytest.raises(TallyParseError, match="not well-formed"):
        parse_tally_xml(b"<ENVELOPE><BODY></ENVELOPE>")


@pytest.mark.parametrize("data, message", [
    (b"", "empty"),
    (b"\xff\xfe\x00\x01\x02", "not"),  # broken UTF-16
    (b"<HTML><BODY/></HTML>", "top element is <HTML>"),
    (b"<ENVELOPE><BODY/></ENVELOPE>", "REQUESTDATA was not found"),
])
def test_D30_unknown_shapes_are_refused(data, message):
    with pytest.raises(TallyParseError, match=message):
        parse_tally_xml(data)


def test_D30_unknown_element_in_message_is_refused_by_name():
    with pytest.raises(TallyParseError, match="Unknown element <SURPRISE>"):
        parse_tally_xml(wrap("<SURPRISE/>"))


def test_D30_message_without_anything_to_import_is_refused():
    with pytest.raises(TallyParseError, match="holds no group"):
        parse_tally_xml(wrap('<UNIT NAME="Nos"/>'))


def test_D30_utf16_with_bom_is_read():
    data = wrap('<LEDGER NAME="Cash"><PARENT>Cash-in-Hand</PARENT></LEDGER>').decode("utf-8")
    tally = parse_tally_xml(codecs.BOM_UTF16_LE + data.encode("utf-16-le"))
    assert [x.name for x in tally.ledgers] == ["Cash"]


def test_D30_illegal_character_reference_is_removed_not_fatal():
    tally = parse_tally_xml(wrap('<LEDGER NAME="Cash"><PARENT>Cash-in-Hand</PARENT><OPENINGBALANCE>&#4;-10.00</OPENINGBALANCE></LEDGER>'))
    assert tally.ledgers[0].opening_balance == "-10.00"


def test_D35_amount_with_three_decimals_is_rejected_not_rounded():
    with pytest.raises(TallyParseError, match="at most 2 decimals") as info:
        parse_tally_xml(wrap(voucher(entry(amount="-10.005"))))
    assert info.value.rule_id == "D-35"


def test_D35_entry_without_sign_flag_is_rejected():
    bad = "<ALLLEDGERENTRIES.LIST><LEDGERNAME>Cash</LEDGERNAME><AMOUNT>-10.00</AMOUNT></ALLLEDGERENTRIES.LIST>"
    with pytest.raises(TallyParseError, match="ISDEEMEDPOSITIVE is missing"):
        parse_tally_xml(wrap(voucher(bad)))


def test_D30_bad_date_and_missing_type_are_rejected():
    with pytest.raises(TallyParseError, match="YYYYMMDD"):
        parse_tally_xml(wrap(voucher(entry(), date_text="15-04-2026")))
    with pytest.raises(TallyParseError, match="not a real date"):
        parse_tally_xml(wrap(voucher(entry(), date_text="20260230")))
    with pytest.raises(TallyParseError, match="voucher type is missing"):
        parse_tally_xml(wrap("<VOUCHER><DATE>20260415</DATE></VOUCHER>"))


def test_D30_unknown_action_is_rejected():
    with pytest.raises(TallyParseError, match="ACTION 'Delete'"):
        parse_tally_xml(wrap('<VOUCHER VCHTYPE="Journal" ACTION="Delete"><DATE>20260415</DATE></VOUCHER>'))


def test_D35_accounting_allocations_inside_inventory_entries_are_read_and_counted():
    inner = ("<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Widget</STOCKITEMNAME><ACCOUNTINGALLOCATIONS.LIST>"
             "<LEDGERNAME>Sales - Goods</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>100.00</AMOUNT>"
             "</ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>")
    v = parse_tally_xml(wrap(voucher(inner))).vouchers[0]
    assert v.inventory_lines == 1
    assert [(e.ledger_name, e.from_inventory) for e in v.entries] == [("Sales - Goods", True)]


def test_D30_name_may_come_from_name_list():
    tally = parse_tally_xml(wrap("<GROUP><NAME.LIST><NAME>Retail</NAME></NAME.LIST><PARENT>Sundry Debtors</PARENT></GROUP>"))
    assert (tally.groups[0].name, tally.groups[0].parent) == ("Retail", "Sundry Debtors")
