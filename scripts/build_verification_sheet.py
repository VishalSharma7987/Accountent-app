"""Builds the printable verification sheet (Excel) for the accountants from a test pack folder.

    python scripts/build_verification_sheet.py [docs/test-packs/abc-traders-apr-2026]

Writes VERIFICATION_SHEET.xlsx into the pack folder. Re-runnable: it always rebuilds from the pack files.
The ledger workings are plain addition of the pack's own files (opening + voucher lines + reversals); they do NOT
use the accounting engine, so they are an independent check. The accountants tick/sign every sheet.
"""

import sys
from datetime import date
from decimal import Decimal
from itertools import groupby
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "tests" / "acceptance"))
from pack_loader import load_pack  # noqa: E402

INR = "[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00"  # 1,00,000.00 style
HEADER_FILL = PatternFill("solid", fgColor="DDE6F0")
TOTAL_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="999999")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRONG_WORDS = {  # plain-language reason for each rule id
    "V-01": "a voucher needs at least 2 lines", "V-02": "each line must have exactly one of debit / credit",
    "V-03": "amounts: not negative, at most 2 decimals", "V-04": "total debit must equal total credit",
    "V-05": "ledger must exist, belong to the client and be active", "V-06": "date must be inside a financial year",
    "V-07": "the period must be open (not locked)", "V-08": "the voucher-type rule is broken",
    "V-09": "narration is required", "V-10": "possible duplicate of an existing voucher",
    "V-13": "the party ledger must be one of the lines", "V-14": "reference no (bill number) is required",
}


def page(ws: Worksheet, title_rows: int, widths: list[float]) -> None:
    """Print setup: landscape, fit to one page wide, repeat the header rows, sensible column widths."""
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"1:{title_rows}"
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.oddFooter.center.text = "&A  -  page &P of &N"
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = ws.cell(row=title_rows + 1, column=1)


def header(ws: Worksheet, row: int, labels: list[str]) -> None:
    for col, label in enumerate(labels, start=1):
        c = ws.cell(row=row, column=col, value=label)
        c.font, c.fill, c.border = Font(bold=True), HEADER_FILL, BOX
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def put(ws: Worksheet, row: int, values: list, money_cols: tuple[int, ...] = (), bold: bool = False, fill=None) -> None:
    for col, value in enumerate(values, start=1):
        c = ws.cell(row=row, column=col, value=value)
        c.border = BOX
        c.alignment = Alignment(vertical="top", wrap_text=True)
        if col in money_cols and value not in (None, ""):
            c.number_format = INR
            c.alignment = Alignment(horizontal="right", vertical="top")
        if bold:
            c.font = Font(bold=True)
        if fill:
            c.fill = fill


def title(ws: Worksheet, text: str, pack_name: str, width_cols: int) -> None:
    ws.cell(row=1, column=1, value=f"{text}  -  {pack_name}").font = Font(bold=True, size=13)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width_cols)


def d(value: Decimal) -> Decimal | None:
    return value if value else None


def build(pack_dir: Path) -> Path:
    pack = load_pack(pack_dir)
    name = f"{pack.client.name} ({pack.client.fy_start:%B %Y} pack)"
    wb = Workbook()

    # ------------------------------------------------------------------ 1. opening balances
    ws = wb.active
    ws.title = "1 Opening balances"
    title(ws, "Opening balances on 01-04-2026", name, 4)
    header(ws, 2, ["Ledger", "Group", "Debit (Rs)", "Credit (Rs)"])
    row = 3
    for x in pack.ledgers:
        if x.opening_dr or x.opening_cr:
            put(ws, row, [x.name, x.group, d(x.opening_dr), d(x.opening_cr)], (3, 4))
            row += 1
    total_dr, total_cr = sum(x.opening_dr for x in pack.ledgers), sum(x.opening_cr for x in pack.ledgers)
    put(ws, row, ["TOTAL", "", total_dr, total_cr], (3, 4), True, TOTAL_FILL)
    put(ws, row + 1, ["Difference (must be nil)", "", total_dr - total_cr, None], (3,), True)
    put(ws, row + 3, ["Checked: opening debits = opening credits   [   ]", "", "", ""])
    page(ws, 2, [34, 24, 18, 18])

    # ------------------------------------------------------------------ 2. vouchers
    ws = wb.create_sheet("2 Vouchers")
    title(ws, "Correct vouchers (in the order they are posted)", name, 9)
    header(ws, 2, ["Ref", "Date", "Type", "Ledger", "Debit (Rs)", "Credit (Rs)", "Narration", "Reference no", "Party ledger"])
    row = 3
    for ref, group in groupby(pack.vouchers, key=lambda v: v.ref_id):
        lines = list(group)
        for i, v in enumerate(lines):
            put(ws, row, [ref if i == 0 else "", v.date if i == 0 else None, v.voucher_type if i == 0 else "", v.ledger_name,
                          d(v.debit), d(v.credit), v.narration if i == 0 else "", v.reference_no if i == 0 else "",
                          v.party_ledger if i == 0 else ""], (5, 6))
            if i == 0:
                ws.cell(row=row, column=2).number_format = "DD-MM-YYYY"
            row += 1
        put(ws, row, ["", "", "", f"Total {ref} (debit = credit)", sum(x.debit for x in lines), sum(x.credit for x in lines), "", "", ""],
            (5, 6), True, TOTAL_FILL)
        row += 1
    for r in pack.reversals:
        put(ws, row, [f"REV {r.ref_id}", r.reversal_date, "reversal", f"Reversal of {r.ref_id}: every Dr/Cr swapped", None, None,
                      r.reason, "", ""], bold=True)
        ws.cell(row=row, column=2).number_format = "DD-MM-YYYY"
        row += 1
    page(ws, 2, [9, 12, 12, 30, 15, 15, 44, 14, 20])

    # ------------------------------------------------------------------ 3. ledger workings (plain addition)
    ws = wb.create_sheet("3 Ledger workings")
    title(ws, "Ledger-wise workings (plain addition) - check each closing balance by hand", name, 7)
    header(ws, 2, ["Ledger / Date", "Voucher", "Debit (Rs)", "Credit (Rs)", "Balance (Rs)", "Dr/Cr", "Your check"])
    entries: dict[str, list[tuple[date, str, Decimal, Decimal]]] = {x.name: [] for x in pack.ledgers}
    reversed_refs = {r.ref_id: r for r in pack.reversals}
    for v in pack.vouchers:
        entries[v.ledger_name].append((v.date, v.ref_id, v.debit, v.credit))
        if v.ref_id in reversed_refs:
            entries[v.ledger_name].append((reversed_refs[v.ref_id].reversal_date, f"REV {v.ref_id}", v.credit, v.debit))
    row = 3
    for x in pack.ledgers:
        put(ws, row, [f"{x.name}  ({x.group})", "", "", "", "", "", ""], bold=True, fill=HEADER_FILL)
        row += 1
        balance = x.opening_dr - x.opening_cr
        put(ws, row, ["Opening", "", d(x.opening_dr), d(x.opening_cr), abs(balance) if balance else None,
                      "Dr" if balance > 0 else ("Cr" if balance < 0 else ""), ""], (3, 4, 5))
        row += 1
        total_d, total_c = x.opening_dr, x.opening_cr
        for on, ref, dr, cr in sorted(entries[x.name], key=lambda e: e[0]):  # stable: file order inside a date
            balance += dr - cr
            total_d, total_c = total_d + dr, total_c + cr
            put(ws, row, [on, ref, d(dr), d(cr), abs(balance) if balance else None,
                          "Dr" if balance > 0 else ("Cr" if balance < 0 else ""), ""], (3, 4, 5))
            ws.cell(row=row, column=1).number_format = "DD-MM-YYYY"
            row += 1
        put(ws, row, ["Total / closing", "", total_d, total_c, abs(balance) if balance else None,
                      "Dr" if balance > 0 else ("Cr" if balance < 0 else "nil"), "[   ]"], (3, 4, 5), True, TOTAL_FILL)
        row += 2
    page(ws, 2, [40, 14, 16, 16, 16, 8, 14])

    # ------------------------------------------------------------------ 4. expected trial balance
    ws = wb.create_sheet("4 Expected Trial Balance")
    title(ws, f"Expected Trial Balance as on {pack.client.pack_end_date:%d-%m-%Y}", name, 4)
    header(ws, 2, ["Group", "Ledger", "Debit (Rs)", "Credit (Rs)"])
    row = 3
    for line in pack.expected_tb:
        put(ws, row, [line.group_name, line.ledger_name, d(line.dr), d(line.cr)], (3, 4))
        row += 1
    put(ws, row, ["TOTAL", "", pack.expected_tb_total[0], pack.expected_tb_total[1]], (3, 4), True, TOTAL_FILL)
    put(ws, row + 2, ["Checked: total debit = total credit   [   ]", "", "", ""])
    page(ws, 2, [26, 34, 18, 18])

    # ------------------------------------------------------------------ 5. wrong vouchers
    ws = wb.create_sheet("5 Wrong vouchers")
    title(ws, "Deliberately wrong vouchers - each must be rejected with the rule shown", name, 8)
    header(ws, 2, ["Ref", "Date", "Type", "Ledger", "Debit", "Credit", "Rule that must reject it", "Why (and the word in the message)"])
    row = 3
    for ref, group in groupby(pack.invalid_vouchers, key=lambda v: v.ref_id):
        lines = list(group)
        for i, v in enumerate(lines):
            rule = lines[0].expected_rule_id
            put(ws, row, [ref if i == 0 else "", v.date if i == 0 else None, v.voucher_type if i == 0 else "", v.ledger_name,
                          v.debit, v.credit, rule if i == 0 else "",
                          f"{v.narration or '(no narration)'} - {WRONG_WORDS.get(rule, '')} [word: {v.expected_message_contains}]" if i == 0 else ""])
            if i == 0:
                ws.cell(row=row, column=2).number_format = "DD-MM-YYYY"
            row += 1
    if pack.locked_periods:
        put(ws, row + 1, [f"Months locked before these are tried: {', '.join(pack.locked_periods)}", "", "", "", "", "", "", ""], bold=True)
    page(ws, 2, [8, 12, 12, 26, 14, 14, 14, 70])

    # ------------------------------------------------------------------ 6. sign-off
    ws = wb.create_sheet("6 Sign-off")
    title(ws, "Sign-off", name, 2)
    rows = [
        ("Verified by (name, role)", ""), ("Date verified (YYYY-MM-DD)", ""),
        ("Method (T-accounts on paper / Tally / Excel)", ""), ("", ""),
        ("[   ] Opening balances: total debit = total credit", ""),
        ("[   ] Every voucher is correct and balanced (sheet 2)", ""),
        ("[   ] Every ledger's closing balance checked by hand (sheet 3)", ""),
        ("[   ] Trial Balance agrees and totals are equal (sheet 4)", ""),
        ("[   ] Every wrong voucher really is wrong, with the right rule (sheet 5)", ""),
        ("[   ] Data is dummy / anonymised", ""), ("", ""),
        ("Result:  [   ] Approved    [   ] Approved with changes    [   ] Rejected", ""),
        ("Notes / disagreements with the tool", ""), ("", ""), ("", ""), ("", ""),
        ("Signature", ""),
    ]
    for i, (a, b) in enumerate(rows, start=2):
        put(ws, i, [a, b])
        ws.row_dimensions[i].height = 22
    page(ws, 1, [70, 50])

    out = pack_dir / "VERIFICATION_SHEET.xlsx"
    wb.save(out)
    return out


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "test-packs" / "abc-traders-apr-2026"
    print("written:", build(folder))
