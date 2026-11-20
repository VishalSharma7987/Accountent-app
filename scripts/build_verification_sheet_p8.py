"""Builds the printable verification sheet (Excel) for the Phase 8 (audit assistant) test pack.

    python scripts/build_verification_sheet_p8.py [docs/test-packs/phase8-audit-checks-2026-27]

Writes VERIFICATION_SHEET.xlsx into the pack folder. Everything shown is READ from the pack files (the books' input files and the hand-typed expected
answers); no figure is computed here. The accountants compare each injected error with the expected finding, tick the section and sign. Same look as the
Phase 1-7 sheets (scripts/build_verification_sheet.py).
"""

import csv
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_verification_sheet import TOTAL_FILL, header, page, put, title

DEFAULT_PACK = ROOT / "docs" / "test-packs" / "phase8-audit-checks-2026-27"
NUMERIC = {"debit", "credit", "amount", "disallowance", "base", "tax_deducted", "tax_amount", "allocated"}


def read(folder: Path, name: str) -> list[dict]:
    path = folder / name
    if not path.is_file():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cell(column: str, value: str):
    if column in NUMERIC and value not in ("", None):
        try:
            return Decimal(value)
        except ArithmeticError:
            return value
    return value


def table_sheet(wb: Workbook, name: str, heading: str, pack_name: str, rows: list[dict], columns: list[str], widths: list[float]) -> None:
    if not rows:
        return
    ws = wb.create_sheet(name[:31])
    ncols = len(columns) + 1
    title(ws, heading, pack_name, ncols)
    header(ws, 2, columns + ["Your check"])
    money = tuple(i for i, c in enumerate(columns, start=1) if c in NUMERIC)
    for row, r in enumerate(rows, start=3):
        put(ws, row, [cell(c, r.get(c, "")) for c in columns] + ["[   ]"], money)
    page(ws, 2, widths + [10])


def build(pack: Path) -> Path:
    pack_name = f"Phase 8 audit pack ({pack.name})"
    wb = Workbook()
    ws = wb.active
    ws.title = "0 Read me"
    title(ws, "How to use this sheet", pack_name, 2)
    lines = [
        "A small trading business (all data synthetic) whose books hold ONE injected error per audit check A-01 to A-18, plus clean controls that must not be flagged.",
        "Sheets 1-3 show what the books contain; sheet 4 lists the expected finding of every injected error; sheet 5 the clean controls.",
        "Work an item yourself (Tally / Excel / paper) from WORKING.md and compare with the expected finding; tick 'Your check' and sign on the last sheet.",
        "Limits and rates come from the seeded rule tables: those with status 'pending' are shown on the finding as 'limit pending verification'. SIGNOFF.md lists the questions.",
        "The audit only reports: it never changes a voucher. A person decides every finding on the working paper.",
    ]
    for i, text_line in enumerate(lines, start=2):
        put(ws, i, [text_line, ""])
    page(ws, 1, [150, 10])

    table_sheet(wb, "1 Vouchers", "Vouchers of the books (V = FY 2026-27, P = FY 2025-26)", pack_name, read(pack, "vouchers.csv"),
                ["ref", "date", "type", "number", "party", "reference_no", "document", "narration"], [8, 12, 10, 18, 24, 12, 9, 50])
    table_sheet(wb, "2 Lines", "Voucher lines (debit and credit)", pack_name, read(pack, "lines.csv"),
                ["ref", "line_no", "ledger", "debit", "credit", "alloc_kind", "alloc_ref"], [8, 6, 28, 16, 16, 12, 12])
    table_sheet(wb, "3 TDS stock GST", "TDS items, challans and the filed GSTR-1 figures", pack_name,
                [{"ref": r["voucher"], "what": "TDS item", "detail": f"{r['deductee']} base {r['base']} tax deducted {r['tax_deducted']}"}
                 for r in read(pack, "tds_items.csv")]
                + [{"ref": r["item_voucher"], "what": "Challan " + r["challan"], "detail": f"deposited {r['deposit_date']} allocated {r['allocated']}"}
                   for r in read(pack, "tds_challans.csv")]
                + [{"ref": r["return_period"], "what": "Filed GSTR-1",
                    "detail": f"taxable {r['gstr1_taxable_value']} CGST {r['gstr1_cgst']} SGST {r['gstr1_sgst']} IGST {r['gstr1_igst']}"}
                   for r in read(pack, "gst_filed.csv")]
                + [{"ref": r["journal"], "what": "Stock write-off", "detail": f"{r['item']} {r['quantity']} on {r['date']} ({r['number']})"}
                   for r in read(pack, "stock_journals.csv")],
                ["ref", "what", "detail"], [12, 18, 90])
    table_sheet(wb, "4 Expected findings", "Expected finding of every injected error (and the incidental ones)", pack_name, read(pack, "expected_findings.csv"),
                ["id", "run", "kind", "check_id", "severity", "finding_date", "amount", "disallowance", "rule_status", "subject_ref", "evidence_vouchers"],
                [6, 6, 10, 7, 9, 12, 16, 14, 16, 36, 16])
    table_sheet(wb, "5 Controls", "Clean controls: must NOT be flagged by the check named", pack_name, read(pack, "expected_controls.csv"),
                ["id", "check_id", "kind", "target", "why"], [6, 7, 8, 18, 100])
    table_sheet(wb, "6 Counts", "Items examined and findings per check", pack_name, read(pack, "expected_summary.csv"),
                ["run", "check_id", "findings", "population"], [8, 8, 10, 12])
    table_sheet(wb, "7 Sampling", "Samples (seed given; hand-derived with SplitMix64)", pack_name, read(pack, "expected_sampling.csv"),
                ["id", "method", "seed", "size", "threshold", "rest_size", "start", "expected"], [6, 12, 6, 6, 14, 9, 6, 80])
    table_sheet(wb, "8 Working paper", "Working paper flow and what the tool must answer", pack_name, read(pack, "expected_paper_flow.csv"),
                ["step", "action", "arg", "expect"], [6, 18, 70, 36])
    table_sheet(wb, "9 Form 3CD", "Form 3CD data derived from the FY 2025-26 findings", pack_name, read(pack, "expected_form3cd.csv"),
                ["clause_no", "field_key", "value", "origin"], [8, 36, 40, 10])
    table_sheet(wb, "10 AI summary", "AI summary (fake model): switch off, switch on, masking", pack_name, read(pack, "expected_ai.csv"),
                ["step", "action", "arg", "expect"], [6, 16, 10, 80])

    ws = wb.create_sheet("11 Sign-off")
    title(ws, "Sign-off", pack_name, 2)
    items = [
        ("Verified by (name, role)", ""), ("Date verified (YYYY-MM-DD)", ""), ("Method (Tally / Excel / paper)", ""), ("", ""),
        ("[   ] Every injected error (one per check A-01 to A-18) is a real error and matches its expected finding (sheet 4)", ""),
        ("[   ] None of the clean controls (sheet 5) should be reported", ""),
        ("[   ] The limits, rates and days used (WORKING.md section 1) are right; pending ones are shown as pending", ""),
        ("[   ] The counts of items examined (sheet 6) are right", ""),
        ("[   ] The sample items (sheet 7) are plausible for the stated seed", ""),
        ("[   ] The working paper steps (sheet 8) are what a reviewer expects: decisions need a reason, a signed-off paper cannot be changed", ""),
        ("[   ] The Form 3CD data (sheet 9) agrees; the Form 26 clause list is still to be supplied (SIGNOFF Q8)", ""),
        ("[   ] The AI summary only restates findings and is stored as a suggestion (sheet 10)", ""),
        ("[   ] Questions in SIGNOFF.md answered", ""), ("[   ] Data is dummy / synthetic", ""), ("", ""),
        ("Result:  [   ] Approved    [   ] Approved with changes    [   ] Rejected", ""),
        ("Notes / disagreements with the tool", ""), ("", ""), ("", ""), ("", ""),
        ("Signature", ""),
    ]
    for i, (a, b) in enumerate(items, start=2):
        put(ws, i, [a, b], fill=TOTAL_FILL if a.startswith("Result") else None)
        ws.row_dimensions[i].height = 22
    page(ws, 1, [130, 40])

    out = pack / "VERIFICATION_SHEET.xlsx"
    wb.save(out)
    return out


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PACK
    print("written:", build(folder))
