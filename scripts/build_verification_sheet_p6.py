"""Builds the printable verification sheet (Excel) for the Phase 6 (period-end and final accounts) test pack.

    python scripts/build_verification_sheet_p6.py [docs/test-packs/phase6-full-year-accounts-2026-27]

Writes VERIFICATION_SHEET.xlsx into the pack folder. Everything shown is READ from the pack files (the inputs and the hand-typed
expected answers); no figure is computed here. The accountants re-work each section, tick it and sign.
Same look as the Phase 1-5 sheets (scripts/build_verification_sheet.py).
"""

import csv
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_verification_sheet import TOTAL_FILL, header, page, put, title

DEFAULT_PACK = ROOT / "docs" / "test-packs" / "phase6-full-year-accounts-2026-27"
CLIENTS = (("proprietor", "Ramesh Hardware Traders (proprietor, trading)", "1"),
           ("partnership", "Sharma and Verma Associates (partnership 3:2, service)", "2"),
           ("company", "Orion Trading Company Pvt Ltd (company, Schedule III)", "3"))
NUMERIC = {  # columns shown as Indian-format numbers
    "opening_dr", "opening_cr", "debit", "credit", "amount", "previous_amount", "opening_accumulated", "depreciation", "closing_accumulated",
    "opening_cost", "additions", "disposals", "closing_cost", "depreciation_for_year", "net_block", "opening_wdv", "additions_full",
    "additions_half", "closing_wdv", "residual", "cost_value", "write_down", "remuneration_annual",
}


def read(folder: Path, name: str) -> list[dict]:
    path = folder / name
    if not path.is_file():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cell(column: str, text: str):
    if column in NUMERIC and text not in ("", None):
        try:
            return Decimal(text)
        except ArithmeticError:
            return text
    return text


def table_sheet(wb: Workbook, name: str, heading: str, pack_name: str, rows: list[dict], columns: list[str], widths: list[float],
                note: str = "") -> None:
    if not rows:
        return
    ws = wb.create_sheet(name[:31])
    ncols = len(columns) + 1
    title(ws, heading, pack_name, ncols)
    header(ws, 2, columns + ["Your check"])
    money = tuple(i for i, c in enumerate(columns, start=1) if c in NUMERIC)
    row = 3
    for r in rows:
        put(ws, row, [cell(c, r.get(c, "")) for c in columns] + ["[   ]"], money)
        row += 1
    if note:
        put(ws, row + 1, [note] + [""] * (ncols - 1))
    page(ws, 2, widths + [10])


def build(pack: Path) -> Path:
    pack_name = f"Phase 6 final accounts pack ({pack.name})"
    wb = Workbook()
    ws = wb.active
    ws.title = "0 Read me"
    title(ws, "How to use this sheet", pack_name, 2)
    lines = [
        "Three dummy clients, each with the same sheets (the number in front of the sheet name is the client: 1 proprietor, 2 partnership, 3 company).",
        "Re-work each statement from the inputs (openings, vouchers, adjustments, assets) and tick the 'Your check' column. WORKING.md shows every step.",
        "Nothing in the law tables is verified: depreciation rates, useful lives, the half-rate rule and the Schedule III lines carry the status 'pending' (SIGNOFF.md).",
        "Amounts are in Indian format; GST is not part of these clients.",
    ]
    for i, text in enumerate(lines, start=2):
        put(ws, i, [text, ""])
    page(ws, 1, [150, 10])

    for key, client_title, n in CLIENTS:
        folder = pack / key
        p = f"{n} {key[:5]}"
        table_sheet(wb, f"{p} Opening", f"{client_title}: ledgers and opening balances (first year)", pack_name, read(folder, "ledgers.csv"),
                    ["ledger_name", "group_name", "opening_dr", "opening_cr"], [34, 24, 16, 16])
        table_sheet(wb, f"{p} Vouchers", f"{client_title}: vouchers posted in date order", pack_name, read(folder, "vouchers.csv"),
                    ["ref_id", "date", "voucher_type", "ledger_name", "debit", "credit", "narration", "reference_no"],
                    [8, 11, 11, 26, 14, 14, 50, 14])
        table_sheet(wb, f"{p} Inputs", f"{client_title}: accountant's inputs (closing stock)", pack_name, read(folder, "closing_stock.csv"),
                    ["fy", "source", "as_on_date", "cost_value", "write_down", "basis_note"], [9, 10, 12, 14, 14, 70])
        table_sheet(wb, f"{p} Partners", f"{client_title}: deed terms of the partners", pack_name, read(folder, "partner_terms.csv"),
                    ["fy", "partner", "profit_share_percent", "interest_on_capital_rate", "interest_on_drawings_rate", "remuneration_annual",
                     "deed_reference"], [9, 16, 12, 12, 12, 14, 44])
        table_sheet(wb, f"{p} Adjust", f"{client_title}: adjustments to be made (amounts computed by the tool are blank here)", pack_name,
                    read(folder, "adjustments.csv"),
                    ["ref_id", "adj_type", "as_on_date", "amount", "debit_ledger", "credit_ledger", "party_ledger", "rate_percent", "partner",
                     "months", "basis_note"], [6, 22, 11, 12, 22, 22, 18, 9, 14, 7, 50])
        table_sheet(wb, f"{p} Adj lines", f"{client_title}: the journal each adjustment must create (hand-worked)", pack_name,
                    read(folder, "expected_adjustments.csv"), ["ref_id", "ledger_name", "debit", "credit"], [8, 38, 16, 16])
        table_sheet(wb, f"{p} Assets", f"{client_title}: fixed assets and events", pack_name, read(folder, "assets.csv"),
                    ["asset_no", "name", "asset_ledger", "it_block", "sched2_class", "residual", "method"], [8, 22, 22, 24, 24, 12, 8])
        table_sheet(wb, f"{p} Asset events", f"{client_title}: asset events", pack_name, read(folder, "asset_events.csv"),
                    ["asset_no", "kind", "event_date", "put_to_use_date", "amount", "accumulated_dep_bf"], [8, 10, 12, 14, 14, 14])
        table_sheet(wb, f"{p} Book dep", f"{client_title}: Companies Act depreciation per asset (straight line, Schedule II, status pending)",
                    pack_name, read(folder, "expected_depreciation.csv"),
                    ["fy", "asset_no", "method", "days_used", "days_in_year", "opening_accumulated", "depreciation", "closing_accumulated",
                     "rule_status"], [9, 8, 8, 8, 8, 16, 14, 16, 10],
                    "Depreciation = (cost - residual) x days / (life x days in the year), rounded half up; both days counted.")
        table_sheet(wb, f"{p} Register", f"{client_title}: fixed-asset register", pack_name, read(folder, "expected_register.csv"),
                    ["fy", "asset_no", "opening_cost", "additions", "disposals", "closing_cost", "opening_accumulated", "depreciation_for_year",
                     "closing_accumulated", "net_block"], [9, 8, 14, 14, 10, 14, 14, 14, 14, 14])
        table_sheet(wb, f"{p} IT blocks", f"{client_title}: income-tax block working (a working only, no voucher)", pack_name,
                    read(folder, "it_openings.csv"), ["fy", "block_key", "opening_wdv"], [9, 30, 16])
        table_sheet(wb, f"{p} IT result", f"{client_title}: income-tax depreciation by block (half rate for additions under 180 days)",
                    pack_name, read(folder, "expected_it_blocks.csv"),
                    ["fy", "block_key", "rate", "opening_wdv", "additions_full", "additions_half", "disposals", "depreciation", "closing_wdv",
                     "rate_verification"], [9, 26, 9, 14, 14, 14, 10, 14, 14, 18],
                    "Addition put to use for fewer than 180 days (31 March counted) gets half the rate; 180 or more gets the full rate.")
        table_sheet(wb, f"{p} Trial Bal", f"{client_title}: Trial Balance after adjustments, before closing", pack_name,
                    read(folder, "expected_trial_balance.csv"), ["fy", "ledger_name", "debit", "credit"], [9, 38, 16, 16])
        table_sheet(wb, f"{p} Statements", f"{client_title}: Trading, Profit and Loss, Appropriation and Balance Sheet", pack_name,
                    read(folder, "expected_statements.csv"), ["fy", "statement", "side", "label", "amount"], [9, 26, 8, 54, 16])
        table_sheet(wb, f"{p} Sch III", f"{client_title}: Schedule III with previous-year column", pack_name, read(folder, "expected_sch3.csv"),
                    ["fy", "statement", "label", "amount", "previous_amount"], [9, 20, 64, 16, 16],
                    "A blank previous-year column means the first year (shown as '-' with a warning).")
        table_sheet(wb, f"{p} Notes", f"{client_title}: Schedule III notes", pack_name, read(folder, "expected_notes.csv"),
                    ["fy", "note_no", "title", "label", "amount"], [9, 7, 30, 56, 16])
        table_sheet(wb, f"{p} Cash flow", f"{client_title}: Cash Flow Statement (AS 3, indirect)", pack_name, read(folder, "expected_cash_flow.csv"),
                    ["fy", "label", "amount"], [9, 70, 16])
        table_sheet(wb, f"{p} Closing", f"{client_title}: year-end closing vouchers", pack_name, read(folder, "expected_closing.csv"),
                    ["fy", "step", "ledger_name", "debit", "credit"], [9, 14, 38, 16, 16])
        table_sheet(wb, f"{p} Carried", f"{client_title}: opening balances carried to the next year", pack_name,
                    read(folder, "expected_carried.csv"), ["fy", "ledger_name", "debit", "credit"], [9, 38, 16, 16])
        table_sheet(wb, f"{p} Carried IT", f"{client_title}: income-tax block values carried to the next year", pack_name,
                    read(folder, "expected_carried_it.csv"), ["fy", "block_key", "opening_wdv"], [9, 30, 16])

    ws = wb.create_sheet("9 Sign-off")
    title(ws, "Sign-off", pack_name, 2)
    items = [
        ("Verified by (name, role)", ""), ("Date verified (YYYY-MM-DD)", ""), ("Method (Tally / Excel / paper)", ""), ("", ""),
        ("[   ] Adjustments of every client give the journals of the 'Adj lines' sheets (provision on debtors after bad debt; interest day-weighted)", ""),
        ("[   ] Companies Act depreciation per asset and the fixed-asset register (Book dep, Register)", ""),
        ("[   ] Income-tax blocks with the half rate for the addition put to use for fewer than 180 days (IT result)", ""),
        ("[   ] Trial Balance, Trading, Profit and Loss, Balance Sheet (horizontal and vertical), appropriation of the partnership", ""),
        ("[   ] Schedule III Balance Sheet, Profit and Loss, 15 notes and the previous-year column of the company", ""),
        ("[   ] Cash Flow Statements tie to cash and bank", ""),
        ("[   ] Year-end closing vouchers, carried openings and income-tax blocks carried (Closing, Carried, Carried IT)", ""),
        ("[   ] Questions in SIGNOFF.md answered (readings of the tool) and the pending legal values confirmed", ""),
        ("[   ] Data is dummy / synthetic", ""), ("", ""),
        ("Result:  [   ] Approved    [   ] Approved with changes    [   ] Rejected", ""),
        ("Notes / disagreements with the tool", ""), ("", ""), ("", ""), ("", ""),
        ("Signature", ""),
    ]
    for i, (a, b) in enumerate(items, start=2):
        put(ws, i, [a, b], fill=TOTAL_FILL if a.startswith("Result") else None)
        ws.row_dimensions[i].height = 22
    page(ws, 1, [120, 40])

    out = pack / "VERIFICATION_SHEET.xlsx"
    wb.save(out)
    return out


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PACK
    print("written:", build(folder))
