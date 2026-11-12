"""Excel voucher parser (pure): rows -> vouchers, with the Excel row number on every problem."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from xlsx_helpers import APRIL_5, GOOD_ROWS, inject_cached_value, make_xlsx

from app.importers.voucher_excel import (
    COLUMNS,
    LEGACY_COLUMNS,
    ImportFileError,
    ParsedAllocation,
    parse_workbook,
)

D = Decimal


def messages(voucher):
    return [(e.row, e.message) for e in voucher.errors]


def test_columns_are_exactly_the_pack_format():
    assert COLUMNS == (
        "ref_id", "date", "voucher_type", "ledger_name", "debit", "credit", "narration", "reference_no", "party_ledger",
        "bill_type", "bill_ref", "bill_amount", "due_date",
    )
    assert LEGACY_COLUMNS == COLUMNS[:9]


def test_two_valid_vouchers_are_parsed_with_their_row_numbers():
    result = parse_workbook(make_xlsx(GOOD_ROWS))
    assert [(v.ref_id, v.first_row, v.voucher_type, v.voucher_date, v.narration, v.reference_no, v.party_ledger)
            for v in result.vouchers] == [
        ("V1", 2, "payment", APRIL_5, "April rent", "", ""),
        ("V2", 4, "sales", date(2026, 4, 6), "Sale to Rahul", "INV-1", "Rahul Enterprises"),
    ]
    first, second = result.vouchers
    assert [(x.row, x.ledger_name, x.debit, x.credit) for x in first.lines] == [
        (2, "Rent", D("10000"), None), (3, "Cash", None, D("10000"))]
    # text amounts keep their text (commas stripped); the engine reads them later
    assert [(x.row, x.debit, x.credit) for x in second.lines] == [(4, "5000.50", None), (5, None, "5000.50")]
    assert first.errors == [] and second.errors == []


def test_rows_with_the_same_ref_id_stay_one_voucher_even_when_not_next_to_each_other():
    rows = [GOOD_ROWS[0], GOOD_ROWS[2], GOOD_ROWS[1], GOOD_ROWS[3]]
    result = parse_workbook(make_xlsx(rows))
    assert [(v.ref_id, [x.row for x in v.lines]) for v in result.vouchers] == [("V1", [2, 4]), ("V2", [3, 5])]


def test_blank_rows_are_skipped_and_row_numbers_still_match_the_sheet():
    rows = [GOOD_ROWS[0], [None] * 9, [None, "  ", None, None, None, None, None, None, None], GOOD_ROWS[1]]
    result = parse_workbook(make_xlsx(rows))
    assert [x.row for x in result.vouchers[0].lines] == [2, 5]


# ------------------------------------------------------------------------------------------------ file level


def test_a_missing_or_renamed_column_is_a_file_error_that_lists_the_expected_header():
    bad = make_xlsx(GOOD_ROWS, header=[*COLUMNS[:6], "remarks", *COLUMNS[7:]])
    with pytest.raises(ImportFileError) as info:
        parse_workbook(bad)
    assert str(info.value) == (
        "The first row of the sheet must be exactly: ref_id, date, voucher_type, ledger_name, debit, credit, "
        "narration, reference_no, party_ledger, bill_type, bill_ref, bill_amount, due_date (found: ref_id, date, "
        "voucher_type, ledger_name, debit, credit, remarks, reference_no, party_ledger, bill_type, bill_ref, "
        "bill_amount, due_date)."
    )


def test_header_check_ignores_case_and_surrounding_spaces():
    header = [f" {c.upper()} " for c in COLUMNS]
    assert len(parse_workbook(make_xlsx(GOOD_ROWS, header=header)).vouchers) == 2


@pytest.mark.parametrize("garbage", [b"", b"not an excel file", b"PK\x03\x04broken"])
def test_a_file_that_is_not_an_xlsx_is_a_file_error(garbage):
    with pytest.raises(ImportFileError, match=r"not a valid Excel \(\.xlsx\) file"):
        parse_workbook(garbage)


def test_a_sheet_with_a_header_but_no_rows_is_a_file_error():
    with pytest.raises(ImportFileError, match="no voucher rows"):
        parse_workbook(make_xlsx([]))


# ------------------------------------------------------------------------------------------------- dates


@pytest.mark.parametrize(
    "cell",
    [datetime(2026, 4, 5, 0, 0), date(2026, 4, 5), "2026-04-05", "05-04-2026", " 05-04-2026 ", "5-4-2026"],
)
def test_dates_accepted_as_excel_dates_or_text(cell):
    rows = [["V1", cell, "payment", "Rent", 1, None, "n", None, None], ["V1", cell, "payment", "Cash", None, 1, "n", None, None]]
    voucher = parse_workbook(make_xlsx(rows)).vouchers[0]
    assert (voucher.voucher_date, voucher.errors) == (APRIL_5, [])


@pytest.mark.parametrize("cell", ["April 5", "2026-02-30", "31/04/2026", "05.04.2026", 46000, None, ""])
def test_a_bad_date_is_reported_on_its_row(cell):
    rows = [["V1", cell, "payment", "Rent", 1, None, "n", None, None], ["V1", cell, "payment", "Cash", None, 1, "n", None, None]]
    voucher = parse_workbook(make_xlsx(rows)).vouchers[0]
    assert voucher.voucher_date is None
    assert messages(voucher)[0] == (2, "date must be a real date, as an Excel date or text like 2026-04-05 or 05-04-2026")


# ------------------------------------------------------------------------------------------------ headers


@pytest.mark.parametrize(
    ("cell", "expected"), [("Payment", "payment"), (" CONTRA ", "contra"), ("Credit Note", "credit_note"), ("debit_note", "debit_note")]
)
def test_voucher_type_is_normalised(cell, expected):
    rows = [["V1", APRIL_5, cell, "Rent", 1, None, "n", None, None], ["V1", APRIL_5, cell, "Cash", None, 1, "n", None, None]]
    assert parse_workbook(make_xlsx(rows)).vouchers[0].voucher_type == expected


def test_an_unknown_voucher_type_is_reported_on_its_row():
    rows = [["V1", APRIL_5, "expense", "Rent", 1, None, "n", None, None], ["V1", APRIL_5, "expense", "Cash", None, 1, "n", None, None]]
    voucher = parse_workbook(make_xlsx(rows)).vouchers[0]
    assert messages(voucher) == [(2, "voucher_type must be one of contra, payment, receipt, sales, purchase, credit_note, debit_note, journal (found: 'expense')")]


def test_lines_of_one_voucher_must_agree_on_date_type_narration_reference_and_party():
    rows = [
        ["V1", APRIL_5, "payment", "Rent", 1, None, "first", "R1", "Sharma Suppliers"],
        ["V1", "2026-04-06", "receipt", "Cash", None, 1, "second", "R2", "Rahul Enterprises"],
    ]
    voucher = parse_workbook(make_xlsx(rows)).vouchers[0]
    assert messages(voucher) == [
        (3, "date differs from the voucher's first row (row 2)"),
        (3, "voucher_type differs from the voucher's first row (row 2)"),
        (3, "narration differs from the voucher's first row (row 2)"),
        (3, "reference_no differs from the voucher's first row (row 2)"),
        (3, "party_ledger differs from the voucher's first row (row 2)"),
    ]


def test_ref_id_may_be_a_number_and_may_not_be_blank():
    rows = [[7, APRIL_5, "payment", "Rent", 1, None, "n", None, None], [7.0, APRIL_5, "payment", "Cash", None, 1, "n", None, None],
            [None, APRIL_5, "payment", "Rent", 1, None, "n", None, None]]
    result = parse_workbook(make_xlsx(rows))
    assert [v.ref_id for v in result.vouchers] == ["7", "(row 4)"]
    assert messages(result.vouchers[1]) == [(4, "ref_id is empty: rows of one voucher share a ref_id")]


# ------------------------------------------------------------------------------------------------ amounts


def line_amounts(cell_debit, cell_credit=None):
    rows = [["V1", APRIL_5, "payment", "Rent", cell_debit, cell_credit, "n", None, None]]
    voucher = parse_workbook(make_xlsx(rows)).vouchers[0]
    return voucher.lines[0].debit, voucher.lines[0].credit, voucher.errors


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (10000, D("10000")),
        (10000.5, D("10000.5")),
        (0.1, D("0.1")),
        ("1,000.50", "1000.50"),
        (" 250 ", "250"),
        ("1,00,000", "100000"),
        ("10.005", "10.005"),  # still text: the engine rejects it with rule V-03 and the row number
        ("abc", "abc"),
        ("-5", "-5"),
        ("", None),
        (None, None),
    ],
)
def test_amount_cells_numbers_and_text(cell, expected):
    debit, credit, errors = line_amounts(cell)
    assert (debit, credit, errors) == (expected, None, [])


def test_a_calculated_number_that_is_not_an_exact_2_decimal_amount_keeps_its_exact_value_for_the_engine():
    """0.1 + 0.2 as Excel stores it. The parser must not round it away: the engine rejects it under V-03."""
    data = make_xlsx([["V1", APRIL_5, "payment", "Rent", None, 1, "n", None, None]])
    # replace the debit cell by a formula, then give it the result Excel would have saved
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data))
    wb.active["E2"] = "=0.1+0.2"
    out = io.BytesIO()
    wb.save(out)
    data = inject_cached_value(out.getvalue(), "E2", "0.30000000000000004")
    voucher = parse_workbook(data).vouchers[0]
    assert voucher.errors == []
    assert voucher.lines[0].debit == D("0.30000000000000004")


def test_a_formula_without_a_saved_result_is_reported_on_its_row():
    data = make_xlsx([["V1", APRIL_5, "payment", "Rent", "=1000+500", None, "n", None, None]])
    voucher = parse_workbook(data).vouchers[0]
    assert messages(voucher) == [(2, "debit holds a formula with no saved result; open the file in Excel, save it, and upload it again")]


def test_a_true_false_cell_is_not_an_amount():
    voucher = parse_workbook(make_xlsx([["V1", APRIL_5, "payment", "Rent", True, None, "n", None, None]])).vouchers[0]
    assert messages(voucher) == [(2, "debit is a TRUE/FALSE value, not an amount")]


def test_text_cells_are_trimmed_but_never_rewritten():
    rows = [["V1", APRIL_5, "payment", "  Rent ", 1, None, "  April rent  ", "  CHQ-1 ", " Sharma Suppliers "]]
    voucher = parse_workbook(make_xlsx(rows)).vouchers[0]
    assert (voucher.narration, voucher.reference_no, voucher.party_ledger, voucher.lines[0].ledger_name) == (
        "April rent", "CHQ-1", "Sharma Suppliers", "Rent")


def test_a_missing_ledger_name_is_reported_on_its_row():
    rows = [["V1", APRIL_5, "payment", None, 1, None, "n", None, None]]
    assert messages(parse_workbook(make_xlsx(rows)).vouchers[0]) == [(2, "ledger_name is empty")]


def test_the_old_nine_column_header_is_still_accepted():
    assert len(parse_workbook(make_xlsx(GOOD_ROWS, header=LEGACY_COLUMNS)).vouchers) == 2


# ------------------------------------------------------------------------------------ bill allocations


def bill_row(ledger, dr, cr, *bill, ref="V1", vtype="sales", reference="INV-1"):
    """bill = (bill_type, bill_ref, bill_amount, due_date) cells; ledger None/dr None/cr None = continuation row."""
    return [ref, APRIL_5, vtype, ledger, dr, cr, "n", reference, "Rahul Enterprises", *bill]


@pytest.mark.parametrize(
    ("cell", "kind"),
    [("New Ref", "new_ref"), ("new_ref", "new_ref"), (" NEW  REF ", "new_ref"), ("Against Ref", "against_ref"),
     ("against_ref", "against_ref"), ("ADVANCE", "advance"), ("On Account", "on_account"), ("on_account", "on_account")],
)
def test_bill_type_is_case_and_space_insensitive(cell, kind):
    rows = [bill_row("Rahul Enterprises", 100, None, cell, "INV-1", 100), bill_row("Sales", None, 100)]
    voucher = parse_workbook(make_xlsx(rows)).vouchers[0]
    assert voucher.errors == []
    assert voucher.lines[0].allocations == [ParsedAllocation(2, kind, "INV-1", D("100"), None)]
    assert voucher.lines[1].allocations == []


def test_continuation_rows_add_allocations_to_the_line_above_and_are_not_lines():
    rows = [
        bill_row("Rahul Enterprises", 1000, None, "Against Ref", "OB1", 600),
        bill_row(None, None, None, "New Ref", "INV-9", "400.00", "2026-05-05"),
        bill_row("Sales", None, 1000),
    ]
    voucher = parse_workbook(make_xlsx(rows)).vouchers[0]
    assert voucher.errors == []
    assert [(x.row, x.ledger_name) for x in voucher.lines] == [(2, "Rahul Enterprises"), (4, "Sales")]
    assert voucher.lines[0].allocations == [
        ParsedAllocation(2, "against_ref", "OB1", D("600"), None),
        ParsedAllocation(3, "new_ref", "INV-9", "400.00", date(2026, 5, 5)),
    ]


def test_bill_amount_follows_the_amount_rules_text_commas_stripped_and_exact_floats_kept():
    rows = [bill_row("Rahul Enterprises", 1, None, "New Ref", "A", "1,000.50"),
            bill_row(None, None, None, "New Ref", "B", 0.5),
            bill_row(None, None, None, "New Ref", "C", "10.005")]
    allocations = parse_workbook(make_xlsx(rows)).vouchers[0].lines[0].allocations
    assert [a.amount for a in allocations] == ["1000.50", D("0.5"), "10.005"]  # "10.005" is rejected later by the engine (B-05)


def test_bill_cell_problems_are_reported_on_their_rows():
    rows = [
        bill_row("Rahul Enterprises", 100, None, "Settle", "A", 100),
        bill_row(None, None, None, None, "B", 5),
        bill_row(None, None, None, "New Ref", "C", None),
        bill_row(None, None, None, "New Ref", "D", True),
        bill_row(None, None, None, "New Ref", "E", 5, "soon"),
    ]
    voucher = parse_workbook(make_xlsx(rows)).vouchers[0]
    assert messages(voucher) == [
        (2, "bill_type must be one of New Ref, Against Ref, Advance, On Account (found: 'Settle')"),
        (3, "bill_type must be one of New Ref, Against Ref, Advance, On Account (bill_type is empty)"),
        (4, "bill_amount is empty"),
        (5, "bill_amount is a TRUE/FALSE value, not an amount"),
        (6, "due_date must be a real date, as an Excel date or text like 2026-04-05 or 05-04-2026"),
    ]


def test_a_continuation_row_of_an_unknown_voucher_is_an_ordinary_row_with_its_problems():
    voucher = parse_workbook(make_xlsx([bill_row(None, None, None, "New Ref", "A", 5)])).vouchers[0]
    assert ("ledger_name is empty" in [m for _, m in messages(voucher)]) and voucher.lines[0].allocations[0].amount == D("5")
