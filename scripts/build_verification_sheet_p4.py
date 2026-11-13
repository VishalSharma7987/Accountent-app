"""Builds the printable verification sheet (Excel) for the Phase 4 (TDS / TCS) test pack.

    python scripts/build_verification_sheet_p4.py [docs/test-packs/phase4-greenfield-contractors-2026]

Writes VERIFICATION_SHEET.xlsx into the pack folder. Everything shown is READ from the pack files (the inputs and the
hand-typed expected answers); the only arithmetic here is none: no total is computed. The accountants re-work each section,
tick it and sign. Same look as scripts/build_verification_sheet.py (Phase 1) and the Phase 2 / 3 sheets.
"""

import csv
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_verification_sheet import TOTAL_FILL, header, page, put, title

DEFAULT_PACK = ROOT / "docs" / "test-packs" / "phase4-greenfield-contractors-2026"
NUMERIC = {  # columns shown as Indian-format numbers
    "amount", "payment_amount", "cumulative_before", "cumulative_after", "taxable_base", "tax_already_on_base", "tds_amount",
    "deposited", "balance", "cumulative_amount", "tax_deducted", "threshold", "single_threshold", "monthly_threshold",
    "annual_threshold", "headroom", "total_amount", "allocated", "unallocated", "interest_late_deduction", "interest_late_deposit",
    "amount_paid", "tax_deposited", "difference", "tax", "interest", "fee", "max_amount", "total_deducted", "total_deposited",
    "total_amount_paid", "short_deposit", "challan_tax", "challan_interest", "challan_total",
}
LEGAL_NOTE = ("Rates, thresholds, sections, due dates and interest rates come from the seeded rule tables. Every 1961-Act row, every TCS "
              "row and the interest and 288B rounding provisions are PENDING; the 2025-Act rows are secondary_verified (not read from "
              "the official text). See SIGNOFF.md for the list the CA must confirm.")


def read(pack: Path, name: str) -> list[dict]:
    with open(pack / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cell(column: str, text: str):
    if column in NUMERIC and text not in ("", None):
        try:
            return Decimal(text)
        except ArithmeticError:
            return text
    return text


def table_sheet(wb: Workbook, name: str, heading: str, pack_name: str, rows: list[dict], columns: list[str],
                widths: list[float], note: str = "") -> None:
    ws = wb.create_sheet(name)
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
    name = f"Greenfield Contractors - Phase 4 TDS / TCS pack ({pack.name})"
    wb = Workbook()

    ws = wb.active
    ws.title = "1 Setup"
    title(ws, "Client, deductees, certificates and ledger roles (inputs)", name, 6)
    header(ws, 2, ["Item", "Detail 1", "Detail 2", "Detail 3", "Detail 4", "Your check"])
    row = 3
    for r in read(pack, "deductees.csv"):
        put(ws, row, ["Deductee " + r["ledger_name"], r["pan"] or "(no PAN)", r["pan_status"], r["deductee_type"], "", "[   ]"])
        row += 1
    for r in read(pack, "certificates.csv"):
        put(ws, row, ["Certificate " + r["certificate_no"], r["ledger_name"], f"{r['nature_key']} at {r['rate']}%",
                      f"limit {r['max_amount']}", f"{r['valid_from']} to {r['valid_to']}", "[   ]"])
        row += 1
    for r in read(pack, "ledger_roles.csv"):
        put(ws, row, ["Ledger role " + r["role"], r["ledger_name"], "", "", "", "[   ]"])
        row += 1
    put(ws, row + 1, ["Check: every PAN and the TAN MUMG12345A are synthetic; the buyer-turnover flag for 2026-27 is 'Yes' (limit pending)   [   ]", "", "", "", "", ""])
    page(ws, 2, [44, 24, 30, 16, 26, 10])

    # 2 vouchers with the hand-worked result next to them
    exp = {r["ref_id"]: r for r in read(pack, "expected_items.csv")}
    num = {r["ref_id"]: r["voucher_number"] for r in read(pack, "expected_vouchers.csv")}
    rows = []
    for r in read(pack, "vouchers.csv"):
        e = exp[r["ref_id"]]
        rows.append({
            "ref": r["ref_id"], "number": num[r["ref_id"]], "date": r["date"], "party": r["party_ledger"], "nature": r["nature_key"],
            "credit_date": r["credit_date"], "payment_date": r["payment_date"], "certificate": r["cert_ref"],
            "payment_amount": e["payment_amount"], "act": e["act"], "section_ref": e["section_ref"], "cumulative_before": e["cumulative_before"],
            "cumulative_after": e["cumulative_after"], "threshold_crossed": e["threshold_crossed"], "taxable_base": e["taxable_base"],
            "rate_applied": e["rate_applied"], "rate_reason": e["rate_reason"], "tax_already_on_base": e["tax_already_on_base"],
            "tds_amount": e["tds_amount"], "verification_status": e["verification_status"],
        })
    table_sheet(wb, "2 Deductions", "Vouchers with the hand-worked tax of each item (posting order)", name, rows,
                ["ref", "number", "date", "party", "nature", "credit_date", "payment_date", "certificate", "payment_amount", "act",
                 "section_ref", "cumulative_before", "cumulative_after", "threshold_crossed", "taxable_base", "rate_applied",
                 "rate_reason", "tax_already_on_base", "tds_amount", "verification_status"],
                [6, 18, 11, 26, 20, 11, 11, 11, 14, 12, 9, 14, 14, 9, 14, 8, 17, 12, 12, 17], LEGAL_NOTE)
    table_sheet(wb, "3 Register", "Register: tax, deposit and balance of every item", name, read(pack, "expected_register.csv"),
                ["ref_id", "tds_amount", "deposited", "balance", "deposited_on"], [8, 14, 14, 14, 14])
    table_sheet(wb, "4 By deductee", "Position by deductee and nature, 2026-27", name, read(pack, "expected_by_deductee.csv"),
                ["deductee_name", "nature_key", "cumulative_amount", "tax_deducted", "threshold_crossed_on", "threshold"],
                [28, 22, 16, 14, 16, 14])
    table_sheet(wb, "4b Headroom", "Threshold position shown at entry", name, read(pack, "expected_position.csv"),
                ["deductee_name", "nature_key", "on", "cumulative_amount", "tax_deducted", "single_threshold", "monthly_threshold",
                 "annual_threshold", "headroom"], [28, 20, 12, 16, 14, 14, 14, 14, 12])
    table_sheet(wb, "5 Challans", "Challans entered and the allocation to items", name, read(pack, "challans.csv"),
                ["ref_id", "kind", "quarter", "bsr_code", "deposit_date", "serial_no", "tax", "interest", "fee", "allocations"],
                [8, 6, 8, 10, 12, 10, 12, 12, 8, 46])
    table_sheet(wb, "5b Challan totals", "Challan totals as the tool must show them", name, read(pack, "expected_challans.csv"),
                ["ref_id", "total_amount", "allocated", "unallocated", "status"], [8, 14, 14, 14, 10])
    table_sheet(wb, "6 Interest", "Interest working as on 31-10-2026 (shown, not posted)", name, read(pack, "expected_interest.csv"),
                ["ref_id", "deducted_on", "due_date", "months_late_deduction", "interest_late_deduction", "deposited_on",
                 "months_late_deposit", "interest_late_deposit"], [8, 12, 12, 12, 14, 12, 12, 14],
                "Rates 1% per month (late deduction) and 1.5% per month (late deposit), month or part of a month, are PENDING in the rule table.")
    table_sheet(wb, "7 Return rows", "Quarterly statement rows (non-salary Forms 26Q / 140, TCS 27EQ / 143)", name,
                read(pack, "expected_return_rows.csv"),
                ["working", "row_no", "deductee_name", "event_date", "section_ref", "amount_paid", "taxable_base", "tax_deducted",
                 "tax_deposited", "rate", "rate_reason", "error_row"], [24, 6, 26, 12, 9, 14, 14, 12, 12, 7, 16, 9])
    table_sheet(wb, "7b Return totals", "Quarterly statement totals and form chosen by the quarter-end date", name,
                read(pack, "expected_return_totals.csv"),
                ["working", "form_no", "form_status", "tan", "row_count", "amount_paid", "tax_deducted", "tax_deposited",
                 "short_deposit", "challan_count", "challan_tax", "challan_interest", "challan_total", "error_rule_ids",
                 "warning_rule_ids"], [24, 10, 18, 12, 6, 14, 12, 12, 10, 7, 12, 11, 12, 10, 10],
                "T-50 warning: payment codes of the statement are not verified. The official statement file format is not produced.")
    table_sheet(wb, "8 Certificates", "Certificate data (Form 131 / 16A), only for fully deposited tax", name,
                read(pack, "expected_certificates.csv"),
                ["case", "ledger_name", "quarter", "form_no", "period", "total_amount_paid", "total_deducted", "total_deposited",
                 "item_count", "challan_count", "refusal_rule"], [6, 28, 8, 10, 16, 14, 12, 12, 7, 8, 10])
    table_sheet(wb, "9 26AS", "26AS statement (hand-made file) against the books", name, read(pack, "expected_recon.csv"),
                ["key", "class", "difference", "reason", "link_kind"], [12, 18, 12, 18, 10],
                "Statement file: statement_26as_fy2026-27.csv (layout not verified against a real TRACES file). Row 7 is linked by hand (manual link).")
    table_sheet(wb, "10 Wrong items", "Deliberately wrong items: the tool must refuse each with the rule named", name,
                read(pack, "wrong_cases.csv"), ["case_id", "kind", "description", "expected_rule_id"], [8, 12, 70, 22])
    table_sheet(wb, "11 Ledgers", "Ledger balances (as on 31-03-2026 and 30-11-2026; each year on its own)", name,
                read(pack, "expected_ledger_balances.csv"), ["as_on", "ledger_name", "side", "amount"], [12, 30, 8, 16])
    table_sheet(wb, "12 Rule status", "Worst verification status shown with each working", name, read(pack, "expected_rule_status.csv"),
                ["working", "worst"], [30, 20])

    ws = wb.create_sheet("13 Sign-off")
    title(ws, "Sign-off", name, 2)
    items = [
        ("Verified by (name, role)", ""), ("Date verified (YYYY-MM-DD)", ""),
        ("Method (T-accounts on paper / Tally / Excel)", ""), ("", ""),
        ("[   ] Act chosen by the earlier of payment and credit date, incl. credit 28-03-2026 / payment 03-04-2026 (sheet 2)", ""),
        ("[   ] Threshold crossing: catch-up with set-off (Alpha), whole-amount (Ravi, Mehta), monthly rent (Silver), 194Q excess (Steel Mart)", ""),
        ("[   ] Missing PAN at the higher rate (Delta); lower-deduction certificate partial use (Omega) and nil (Kiran)", ""),
        ("[   ] TCS (scrap 1961 vs 2025, motor vehicle above 10 lakh) (sheet 2)", ""),
        ("[   ] Tax rounded to the whole rupee, half up (Ravi 20,050.00 at 1% = 200.50 -> 201)", ""),
        ("[   ] Register, challan totals and deposit status (sheets 3, 5, 5b)", ""),
        ("[   ] Interest months and amounts (sheet 6)", ""),
        ("[   ] Quarterly statement rows, totals and form numbers (sheets 7, 7b)", ""),
        ("[   ] Certificate data and the refusal for undeposited tax (sheet 8)", ""),
        ("[   ] 26AS classes and the manual link (sheet 9)", ""),
        ("[   ] Every wrong item really is wrong, with the right rule (sheet 10)", ""),
        ("[   ] Pending legal values (SIGNOFF.md) are listed for the CA", ""),
        ("[   ] Data is dummy / synthetic (no real PAN, TAN, names)", ""), ("", ""),
        ("Result:  [   ] Approved    [   ] Approved with changes    [   ] Rejected", ""),
        ("Notes / disagreements with the tool", ""), ("", ""), ("", ""), ("", ""),
        ("Signature", ""),
    ]
    for i, (a, b) in enumerate(items, start=2):
        put(ws, i, [a, b], fill=TOTAL_FILL if a.startswith("Result") else None)
        ws.row_dimensions[i].height = 22
    page(ws, 1, [110, 40])

    out = pack / "VERIFICATION_SHEET.xlsx"
    wb.save(out)
    return out


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PACK
    print("written:", build(folder))
