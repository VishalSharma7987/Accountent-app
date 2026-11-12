"""The downloadable .xlsx template for voucher import (same columns as the test packs' vouchers.csv)."""

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.importers.voucher_excel import COLUMNS, SHEET_NAME

NOTES = [
    "How to fill the Vouchers sheet",
    "",
    "1. One row per voucher line. Rows with the same ref_id are ONE voucher (your own label: V1, V2, ...).",
    ("2. date: an Excel date or text like 2026-04-05 or 05-04-2026. Every row of a voucher has the same date, "
    "voucher_type, narration, reference_no and party_ledger."),
    "3. voucher_type: contra, payment, receipt, sales, purchase, credit_note, debit_note or journal.",
    "4. ledger_name: must match a ledger of the client (capital letters do not matter). The import never creates ledgers.",
    ("5. debit / credit: one of them on each line, plain amounts with at most 2 decimals (numbers or text; "
    "thousands commas in text are ignored). A formula must have been calculated and saved by Excel."),
    "6. narration is required. reference_no is required for purchase and debit_note (supplier bill number).",
    "7. party_ledger: the customer or supplier ledger, when the voucher has one; it must also be one of the lines.",
    "",
    "What happens on upload",
    ("- First a dry run: every voucher is checked with the same rules as the voucher screen and shown OK or with its "
    "errors and Excel row numbers. Nothing is saved."),
    "- Then you choose which OK vouchers to import. They are saved as drafts only; nothing is approved or posted.",
    "",
    "Before uploading, delete the example voucher (rows 2-3 of the Vouchers sheet).",
]


def build_template() -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = SHEET_NAME
    sheet.append(list(COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", start_color="305496")
        cell.alignment = Alignment(horizontal="center")
    sheet.freeze_panes = "A2"

    example = date(2026, 4, 5)
    sheet.append(["V1", example, "payment", "Rent", 1000, None, "Example: shop rent paid in cash", None, None])
    sheet.append(["V1", example, "payment", "Cash", None, 1000, "Example: shop rent paid in cash", None, None])
    for row in sheet.iter_rows(min_row=2, max_row=1000):
        row[1].number_format = "yyyy-mm-dd"
        row[4].number_format = "#,##0.00"
        row[5].number_format = "#,##0.00"
    for letter, width in zip("ABCDEFGHI", (10, 12, 14, 28, 14, 14, 36, 16, 26), strict=True):
        sheet.column_dimensions[letter].width = width

    notes = wb.create_sheet("Notes")
    for text in NOTES:
        notes.append([text])
    notes["A1"].font = Font(bold=True, size=13)
    notes.column_dimensions["A"].width = 120

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
