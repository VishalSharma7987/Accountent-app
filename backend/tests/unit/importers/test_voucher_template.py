import io
from decimal import Decimal

from openpyxl import load_workbook

from app.importers.voucher_excel import COLUMNS, parse_workbook
from app.importers.voucher_template import build_template


def test_template_has_the_import_columns_a_styled_header_and_a_notes_sheet():
    wb = load_workbook(io.BytesIO(build_template()))
    assert wb.sheetnames == ["Vouchers", "Notes"]
    sheet = wb["Vouchers"]
    assert [c.value for c in sheet[1]] == list(COLUMNS)
    assert all(c.font.bold for c in sheet[1])
    assert sheet.freeze_panes == "A2"
    notes = " ".join(str(c.value) for row in wb["Notes"].iter_rows() for c in row if c.value)
    for must_say in ("ref_id", "never creates ledgers", "drafts", "delete the example"):
        assert must_say in notes


def test_the_example_voucher_in_the_template_is_readable_by_the_parser():
    result = parse_workbook(build_template())
    assert len(result.vouchers) == 1
    example = result.vouchers[0]
    assert example.errors == []
    assert (example.voucher_type, len(example.lines)) == ("payment", 2)
    assert [(x.ledger_name, x.debit, x.credit) for x in example.lines] == [("Rent", Decimal(1000), None), ("Cash", None, Decimal(1000))]
