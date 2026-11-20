"""Builds the printable verification sheet (Excel) for the Phase 7 (documents and AI) test pack.

    python scripts/build_verification_sheet_p7.py [docs/test-packs/phase7-documents-and-ai-2026-27]

Writes VERIFICATION_SHEET.xlsx into the pack folder. Everything shown is READ from the pack files (the documents' text, what the fake model
answered, the hand-typed expected answers); no figure is computed here. The accountants compare each document with the expected findings, tick
the section and sign. Same look as the Phase 1-6 sheets (scripts/build_verification_sheet.py).
"""

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_verification_sheet import TOTAL_FILL, header, page, put, title

DEFAULT_PACK = ROOT / "docs" / "test-packs" / "phase7-documents-and-ai-2026-27"
NUMERIC = {"debit", "credit"}


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


def text_sheet(wb: Workbook, name: str, heading: str, pack_name: str, body: str) -> None:
    ws = wb.create_sheet(name[:31])
    title(ws, heading, pack_name, 1)
    for i, line in enumerate(body.splitlines(), start=2):
        put(ws, i, [line])
    page(ws, 1, [120])


def build(pack: Path) -> Path:
    pack_name = f"Phase 7 documents and AI pack ({pack.name})"
    wb = Workbook()
    ws = wb.active
    ws.title = "0 Read me"
    title(ws, "How to use this sheet", pack_name, 2)
    lines = [
        "Twelve sample invoices / notes, one bank statement text, one bank CSV and two Tally files, all dummy data. A (fake) language model 'read' each text;",
        "the tool checks what it read with the engine. Compare each document's text with the expected findings: the tool must catch every deliberate error",
        "and must never post anything wrong. Tick the 'Your check' column and sign on the last sheet.",
        "Taxes: re-work each invoice from the sheets 'Postings' and WORKING.md. The GST rates used are the seeded EXAMPLE rules (status pending): confirm them.",
        "The model answers are scripted; nothing here proves how a real model behaves. SIGNOFF.md lists what real files are still needed.",
    ]
    for i, text_line in enumerate(lines, start=2):
        put(ws, i, [text_line, ""])
    page(ws, 1, [150, 10])

    table_sheet(wb, "1 Documents", "Documents of the pack (what each one tests)", pack_name, read(pack, "documents.csv"),
                ["doc_id", "doc_type", "arrives", "what_it_tests"], [8, 18, 8, 110])
    for doc in read(pack, "documents.csv"):
        text_sheet(wb, f"T {doc['doc_id']}", f"{doc['doc_id']}: the text of the document (one page)", pack_name,
                   (pack / doc["file"]).read_text(encoding="utf-8"))
    answers = json.loads((pack / "fixtures" / "llm_answers.json").read_text(encoding="utf-8"))
    rows = []
    for doc_id, attempts in answers.items():
        for n, ans in enumerate(attempts, start=1):
            lines_ = ans.get("lines", [])
            rows.append({"doc_id": doc_id, "attempt": str(n), "invoice_no": (ans.get("invoice_no") or {}).get("value") or "",
                         "date": (ans.get("invoice_date") or {}).get("value") or "", "lines": str(len(lines_)),
                         "grand_total": ((ans.get("totals") or {}).get("grand_total") or {}).get("value") or "",
                         "extra_key": ", ".join(k for k in ans if k == "amount_in_words")})
    table_sheet(wb, "2 Model answers", "What the fake model answered (headline values only; the full JSON is fixtures/llm_answers.json)", pack_name,
                rows, ["doc_id", "attempt", "invoice_no", "date", "lines", "grand_total", "extra_key"], [8, 8, 16, 12, 8, 14, 18])
    table_sheet(wb, "3 Findings", "Expected findings per document (rule id, severity, field)", pack_name, read(pack, "expected_findings.csv"),
                ["doc_id", "stage", "rule_id", "severity", "field_path"], [8, 10, 9, 10, 28])
    table_sheet(wb, "4 Script", "What the accountant does with each item (scripted)", pack_name, read(pack, "accountant_script.csv"),
                ["doc_id", "step", "action", "arg1", "arg2", "arg3"], [8, 6, 16, 60, 24, 24])
    table_sheet(wb, "5 Decisions", "Expected outcome per queue item", pack_name, read(pack, "expected_decisions.csv"),
                ["item", "draft_initially", "first_accept", "final_queue_status", "final_voucher_status", "voucher_number", "blocking_initial",
                 "warnings_initial", "blocking_final", "warnings_final"], [8, 10, 10, 12, 12, 18, 9, 9, 9, 9])
    table_sheet(wb, "6 Postings", "Expected lines of every posted voucher (hand-worked)", pack_name, read(pack, "expected_postings.csv"),
                ["item", "ledger", "debit", "credit"], [8, 28, 16, 16])
    table_sheet(wb, "7 Balances", "Expected ledger balances after everything is posted (client A and client B)", pack_name,
                read(pack, "expected_ledger_balances.csv"), ["client", "ledger", "debit", "credit"], [8, 28, 16, 16])
    table_sheet(wb, "8 Masking", "Expected masking counts per model call (PAN, Aadhaar, account number, GSTIN)", pack_name,
                read(pack, "expected_masking.csv"), ["doc_id", "calls", "gstin", "pan", "aadhaar", "account"], [8, 8, 8, 8, 8, 8])
    table_sheet(wb, "9 Narration", "Bank narration suggestions (rule first, model fallback, ambiguity, dropped answer, switch off)", pack_name,
                read(pack, "expected_narration.csv"),
                ["step", "line_no", "status", "source", "ledger", "model_called", "decision", "rule_count_after", "detail"],
                [6, 8, 12, 8, 16, 8, 10, 8, 70])
    table_sheet(wb, "10 Bank CSV", "The bank statement CSV of June 2026", pack_name, read(pack / "bank", "statement_june_2026.csv"),
                ["Date", "Narration", "Ref", "Withdrawal", "Deposit", "Balance"], [12, 60, 8, 12, 12, 12])
    table_sheet(wb, "11 Tally", "Expected Tally import / queue / export results", pack_name, read(pack, "expected_tally.csv"),
                ["section", "key", "value"], [14, 34, 90])

    ws = wb.create_sheet("12 Sign-off")
    title(ws, "Sign-off", pack_name, 2)
    items = [
        ("Verified by (name, role)", ""), ("Date verified (YYYY-MM-DD)", ""), ("Method (Tally / Excel / paper)", ""), ("", ""),
        ("[   ] Every deliberate error of the 12 documents is caught with the finding of the 'Findings' sheet, and nothing else is flagged", ""),
        ("[   ] The tax of every posted invoice and the credit note agrees with 'Postings' (recomputed by the tool, not copied from the paper)", ""),
        ("[   ] The two documents that stay unposted for a reason (P7-05 pending HSN rate, P7-06 wrong tax type) and the three rejected ones are right", ""),
        ("[   ] The ledger balances of 'Balances' agree (client A and client B)", ""),
        ("[   ] Masked values: no PAN / Aadhaar / account number / GSTIN would have left the system (Masking)", ""),
        ("[   ] Bank narrations and Tally results are as expected (Narration, Tally)", ""),
        ("[   ] Questions in SIGNOFF.md answered (1.00 tolerance, 0.85 confidence, credit-note fields, D-35 gap, real files needed)", ""),
        ("[   ] Data is dummy / synthetic", ""), ("", ""),
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
