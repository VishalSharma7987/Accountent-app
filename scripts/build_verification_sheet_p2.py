"""Builds the printable verification sheet (Excel) for the Phase 2 test pack.

    python scripts/build_verification_sheet_p2.py [docs/test-packs/abc-traders-phase2-jun-2026]

Writes VERIFICATION_SHEET.xlsx into the pack folder. Everything shown is READ from the pack files (the accountant's
inputs and hand-typed expected answers); the only arithmetic here is column totals for display. The accountants tick
and sign every sheet. Same look as scripts/build_verification_sheet.py (Phase 1).
"""

import csv
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_verification_sheet import HEADER_FILL, TOTAL_FILL, header, page, put, title

DEFAULT_PACK = ROOT / "docs" / "test-packs" / "abc-traders-phase2-jun-2026"
BUCKETS = ("not_due", "0-30", "31-60", "61-90", "90+")


def read(pack: Path, name: str) -> list[dict]:
    with open(pack / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def amt(text: str) -> Decimal | None:
    """CSV amount -> Decimal for the sheet (blank / zero -> None so the cell stays empty)."""
    value = Decimal(text) if text not in ("", None) else Decimal(0)
    return value if value else None


def day(text: str) -> date | None:
    return date.fromisoformat(text) if text else None


def inr(value: Decimal) -> str:
    """Indian grouping for text cells: 1,18,000.00."""
    sign, digits = ("-" if value < 0 else ""), f"{abs(value):.2f}"
    whole, frac = digits.split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}{','.join(groups + [tail])}.{frac}"


def dated(ws, row: int, col: int) -> None:
    ws.cell(row=row, column=col).number_format = "DD-MM-YYYY"


def build(pack: Path) -> Path:
    name = f"ABC Traders - Phase 2 pack ({pack.name})"
    wb = Workbook()

    # ---------------------------------------------------------------- 1. opening bills
    ws = wb.active
    ws.title = "1 Opening bills"
    title(ws, "Opening bills on 01-04-2026 (must add up to each party's opening balance)", name, 7)
    header(ws, 2, ["Party", "Bill ref", "Bill date", "Due date", "Debit (Rs)", "Credit (Rs)", "Your check"])
    ledgers = {r["ledger_name"]: r for r in read(pack, "ledgers.csv")}
    bills = read(pack, "opening_bills.csv")
    row = 3
    for party in dict.fromkeys(b["ledger_name"] for b in bills):
        tot_d = tot_c = Decimal(0)
        for b in (x for x in bills if x["ledger_name"] == party):
            a = Decimal(b["amount"])
            tot_d += a if b["side"] == "Dr" else 0
            tot_c += a if b["side"] == "Cr" else 0
            put(ws, row, [party, b["bill_ref"], day(b["bill_date"]), day(b["due_date"]),
                          a if b["side"] == "Dr" else None, a if b["side"] == "Cr" else None, ""], (5, 6))
            dated(ws, row, 3), dated(ws, row, 4)
            row += 1
        led = ledgers[party]
        put(ws, row, [f"Total {party}", "", "", "", tot_d or None, tot_c or None,
                      f"Ledger opening: Dr {led['opening_dr']} Cr {led['opening_cr']}  [   ]"], (5, 6), True, TOTAL_FILL)
        row += 1
    put(ws, row + 1, ["Bank: statement opening balance 5,00,000.00 less books opening 4,87,500.00 = 12,500.00 = opening cheque 000451", "", "", "", "", "", ""])
    for oi in read(pack, "bank_opening_items.csv"):
        put(ws, row + 2, ["Bank opening item", oi["kind"], day(oi["item_date"]), "", Decimal(oi["amount"]) if oi["kind"] == "deposited_not_cleared" else None,
                          Decimal(oi["amount"]) if oi["kind"] == "issued_not_presented" else None, f"cheque no {oi['reference']}"], (5, 6))
        dated(ws, row + 2, 3)
    page(ws, 2, [30, 18, 12, 12, 16, 16, 44])

    # ---------------------------------------------------------------- 2. vouchers with allocations
    ws = wb.create_sheet("2 Vouchers")
    title(ws, "Correct vouchers with bill-wise allocations (in posting order)", name, 9)
    header(ws, 2, ["Ref", "Date", "Type", "Ledger", "Debit (Rs)", "Credit (Rs)", "Bill-wise allocation of this line", "Narration", "Reference no"])
    allocs: dict[tuple[str, int], list[str]] = defaultdict(list)
    for a in read(pack, "allocations.csv"):
        text = f"{a['kind']} {a['bill_ref']} {inr(Decimal(a['amount']))}".replace("  ", " ")
        if a["due_date"]:
            text += f" (due {day(a['due_date']):%d-%m-%Y})"
        allocs[(a["ref_id"], int(a["line_no"]))].append(text)
    vs: dict[str, list[dict]] = defaultdict(list)
    for r in read(pack, "vouchers.csv"):
        vs[r["ref_id"]].append(r)
    reversals = {r["ref_id"]: r for r in read(pack, "reversals.csv")}
    row = 3
    for ref, lines in vs.items():
        for i, v in enumerate(lines, start=1):
            put(ws, row, [ref if i == 1 else "", day(v["date"]) if i == 1 else None, v["voucher_type"] if i == 1 else "", v["ledger_name"],
                          amt(v["debit"]), amt(v["credit"]), "\n".join(allocs.get((ref, i), [])),
                          v["narration"] if i == 1 else "", v["reference_no"] if i == 1 else ""], (5, 6))
            if i == 1:
                dated(ws, row, 2)
            row += 1
        put(ws, row, ["", "", "", f"Total {ref} (debit = credit)", sum(Decimal(x["debit"]) for x in lines),
                      sum(Decimal(x["credit"]) for x in lines), "", "", ""], (5, 6), True, TOTAL_FILL)
        row += 1
        if ref in reversals:
            r = reversals[ref]
            put(ws, row, [f"REV {ref}", day(r["reversal_date"]), "reversal", f"Reversal of {ref}: every Dr/Cr swapped; bill allocations mirrored",
                          None, None, "", r["reason"], ""], bold=True)
            dated(ws, row, 2)
            row += 1
    page(ws, 2, [9, 12, 12, 28, 15, 15, 44, 46, 15])

    # ---------------------------------------------------------------- 3. outstanding
    ws = wb.create_sheet("3 Outstanding")
    title(ws, "Expected outstanding bills as on 30-06-2026 (receivable and payable)", name, 10)
    header(ws, 2, ["Party", "Bill ref", "Kind", "Side", "Bill date", "Due date", "Original (Rs)", "Outstanding (Rs)", "Days past due", "Bucket"])
    row = 3
    for fname, heading in (("expected_outstanding_receivable.csv", "RECEIVABLE (debtors)"), ("expected_outstanding_payable.csv", "PAYABLE (creditors)")):
        put(ws, row, [heading] + [""] * 9, bold=True, fill=HEADER_FILL)
        row += 1
        for r in read(pack, fname):
            total = r["row_type"] in ("party_total", "grand_total")
            label = {"party_total": f"Total {r['party']}", "grand_total": "GRAND TOTAL"}.get(r["row_type"], r["party"])
            put(ws, row, [label, r["bill_ref"], r["kind"], r["side"], day(r["bill_date"]), day(r["due_date"]), amt(r["original"]),
                          amt(r["outstanding"]), int(r["days_past_due"]) if r["days_past_due"] else None, r["bucket"]],
                (7, 8), total, TOTAL_FILL if total else None)
            dated(ws, row, 5), dated(ws, row, 6)
            row += 1
        row += 1
    put(ws, row, ["Negative days = days still to run. On-account items are shown with the side opposite to the bills and reduce the party total.",
                  "", "", "", "", "", "", "", "", ""])
    page(ws, 2, [30, 16, 11, 7, 12, 12, 16, 16, 10, 10])

    # ---------------------------------------------------------------- 4. ageing
    ws = wb.create_sheet("4 Ageing")
    title(ws, "Expected ageing as on 30-06-2026 (days past due date)", name, 7)
    header(ws, 2, ["Party", "Not due (Rs)", "0-30 (Rs)", "31-60 (Rs)", "61-90 (Rs)", "90+ (Rs)", "Total (Rs)"])
    row = 3
    ageing = read(pack, "expected_ageing.csv")
    for kind in ("receivable", "payable"):
        put(ws, row, [kind.upper()] + [""] * 6, bold=True, fill=HEADER_FILL)
        row += 1
        for r in (x for x in ageing if x["kind"] == kind):
            total = r["row_type"] == "total"
            put(ws, row, ["TOTAL" if total else r["party"]] + [amt(r[b]) for b in BUCKETS] + [amt(r["total"])], (2, 3, 4, 5, 6, 7), total,
                TOTAL_FILL if total else None)
            row += 1
        row += 1
    page(ws, 2, [32, 16, 16, 16, 16, 16, 16])

    # ---------------------------------------------------------------- 5. cash book
    ws = wb.create_sheet("5 Cash Book")
    title(ws, "Expected Cash Book (Cash ledger) 01-04-2026 to 30-06-2026", name, 5)
    header(ws, 2, ["Date", "Receipts (Rs)", "Payments (Rs)", "Closing balance Dr (Rs)", "Your check"])
    row = 3
    for r in read(pack, "expected_cash_book.csv"):
        kind = r["row_type"]
        put(ws, row, ["Opening balance" if kind == "opening" else ("TOTAL" if kind == "total" else day(r["date"])), amt(r["receipts"]),
                      amt(r["payments"]), Decimal(r["closing_dr"]), "[   ]" if kind == "day" else ""], (2, 3, 4), kind != "day",
            TOTAL_FILL if kind == "total" else None)
        if kind == "day":
            dated(ws, row, 1)
        row += 1
    page(ws, 2, [18, 18, 18, 22, 12])

    # ---------------------------------------------------------------- 6. bank statement
    ws = wb.create_sheet("6 Bank statement")
    title(ws, "Bank statement 01-04-2026 to 30-06-2026 with the expected book match", name, 8)
    header(ws, 2, ["#", "Txn date", "Narration", "Chq / Ref no", "Withdrawal (Rs)", "Deposit (Rs)", "Closing balance (Rs)", "Matched book item"])
    matches = {int(m["bank_line_no"]): m for m in read(pack, "expected_matches.csv")}
    row = 3
    put(ws, row, ["", "", "Opening balance", "", None, None, Decimal("500000.00"), ""], (7,), True, TOTAL_FILL)
    row += 1
    wd = dep = Decimal(0)
    for no, r in enumerate(read(pack, "bank_statement.csv"), start=1):
        d_, c_ = Decimal(r["Withdrawal Amt"] or 0), Decimal(r["Deposit Amt"] or 0)
        wd += d_
        dep += c_
        m = matches[no]
        put(ws, row, [no, date(*(int(x) for x in reversed(r["Txn Date"].split("/")))), r["Narration"], r["Chq/Ref No"], d_ or None, c_ or None,
                      Decimal(r["Closing Balance"]), m["book_refs"] or "BANK ONLY (not in books)"], (5, 6, 7))
        dated(ws, row, 2)
        row += 1
    put(ws, row, ["", "", "TOTAL", "", wd, dep, "", ""], (5, 6), True, TOTAL_FILL)
    page(ws, 2, [5, 12, 40, 16, 16, 16, 18, 26])

    # ---------------------------------------------------------------- 7. BRS
    ws = wb.create_sheet("7 BRS")
    title(ws, "Expected Bank Reconciliation Statement as on 30-06-2026 (HDFC Bank)", name, 5)
    header(ws, 2, ["Item", "Date", "Reference", "Particulars", "Amount (Rs)"])
    row = 3
    for r in read(pack, "expected_brs.csv"):
        kind = r["line_type"]
        subtotal = kind.startswith("total_") or kind in ("balance_per_books", "computed_bank_balance", "balance_per_bank", "difference")
        put(ws, row, [kind.replace("_", " "), day(r["item_date"]), r["reference"], r["description"], Decimal(r["amount"])], (5,), subtotal,
            TOTAL_FILL if subtotal else None)
        dated(ws, row, 2)
        row += 1
    put(ws, row + 1, ["The bank-only items are explained here; they are NOT in the books until their draft vouchers are approved and posted.", "", "", "", ""])
    row += 3
    header(ws, row, ["Bank-only line", "Date", "Voucher type (draft)", "Counter ledger", "Amount (Rs)"])
    for r in read(pack, "expected_bank_only_drafts.csv"):
        row += 1
        put(ws, row, [f"statement line {r['bank_line_no']}", day(r["txn_date"]), r["voucher_type"], r["counter_ledger"], Decimal(r["amount"])], (5,))
        dated(ws, row, 2)
    page(ws, 2, [30, 12, 18, 62, 18])

    # ---------------------------------------------------------------- 8. MSME
    ws = wb.create_sheet("8 MSME")
    title(ws, "Expected MSME payment-time flags as on 30-06-2026 (rule values are PENDING verification)", name, 9)
    header(ws, 2, ["Supplier", "Bill ref", "Bill date", "Category", "Written agreement", "Legal days", "Legal due date", "Days overdue", "Outstanding (Rs)"])
    row = 3
    for r in read(pack, "expected_msme_due.csv"):
        total = r["row_type"] == "total"
        put(ws, row, ["TOTAL" if total else r["party"], r["bill_ref"], day(r["bill_date"]), r["msme_category"], r["written_agreement"],
                      int(r["legal_days"]) if r["legal_days"] else None, day(r["legal_due_date"]), int(r["days_overdue"]) if r["days_overdue"] else None,
                      Decimal(r["outstanding"])], (9,), total, TOTAL_FILL if total else None)
        dated(ws, row, 3), dated(ws, row, 7)
        row += 1
    put(ws, row + 1, ["Medium and non-MSME suppliers are never flagged. Legal days: written agreement = agreed days (max 45); none = 15.", "", "", "", "", "", "", "", ""])
    page(ws, 2, [26, 14, 12, 11, 12, 10, 14, 11, 18])

    # ---------------------------------------------------------------- 9. wrong vouchers and parties
    ws = wb.create_sheet("9 Wrong vouchers")
    title(ws, "Deliberately wrong vouchers and parties - each must be refused with the rule shown", name, 8)
    header(ws, 2, ["Ref", "Date", "Type", "Ledger", "Debit (Rs)", "Credit (Rs)", "Rule that must refuse it", "Why / allocation / word in the message"])
    walloc: dict[tuple[str, int], list[str]] = defaultdict(list)
    for a in read(pack, "wrong_allocations.csv"):
        walloc[(a["ref_id"], int(a["line_no"]))].append(f"{a['kind']} {a['bill_ref']} {inr(Decimal(a['amount']))}")
    wv: dict[str, list[dict]] = defaultdict(list)
    for r in read(pack, "wrong_vouchers.csv"):
        wv[r["ref_id"]].append(r)
    row = 3
    for ref, lines in wv.items():
        for i, v in enumerate(lines, start=1):
            extra = "; ".join(walloc.get((ref, i), []))
            why = (f"{v['narration']} [word: {v['expected_message_contains']}]" if i == 1 else "") + (f"  ALLOCATION: {extra}" if extra else "")
            put(ws, row, [ref if i == 1 else "", day(v["date"]) if i == 1 else None, v["voucher_type"] if i == 1 else "", v["ledger_name"],
                          amt(v["debit"]), amt(v["credit"]), v["expected_rule_id"] if i == 1 else "", why.strip()], (5, 6))
            if i == 1:
                dated(ws, row, 2)
            row += 1
    row += 1
    header(ws, row, ["Ref", "Party", "GSTIN", "PAN", "State", "MSME category", "Rule that must refuse it", "Udyam no / word in the message"])
    for r in read(pack, "wrong_parties.csv"):
        row += 1
        put(ws, row, [r["ref_id"], r["ledger_name"], r["gstin"], r["pan"], r["state_code"], r["msme_category"], r["expected_rule_id"],
                      f"Udyam: {r['udyam_no'] or '(none)'} [word: {r['expected_message_contains']}]"])
    page(ws, 2, [8, 20, 18, 14, 14, 14, 16, 70])

    # ---------------------------------------------------------------- 10. sign-off
    ws = wb.create_sheet("10 Sign-off")
    title(ws, "Sign-off", name, 2)
    items = [
        ("Verified by (name, role)", ""), ("Date verified (YYYY-MM-DD)", ""),
        ("Method (T-accounts on paper / Tally / Excel)", ""), ("", ""),
        ("[   ] Opening bills add up to each party's opening balance (sheet 1); total opening Dr = Cr", ""),
        ("[   ] Every voucher balanced and every party line fully allocated (sheet 2)", ""),
        ("[   ] Outstanding bills and party totals checked by hand (sheet 3)", ""),
        ("[   ] Ageing buckets checked by hand; bucket totals = outstanding totals (sheet 4)", ""),
        ("[   ] Cash Book: each day's closing checked, never negative (sheet 5)", ""),
        ("[   ] Bank statement running balance re-added (sheet 6)", ""),
        ("[   ] BRS ties to the rupee (sheet 7)", ""),
        ("[   ] MSME legal due dates checked; legal values confirmed from the official text (sheet 8)", ""),
        ("[   ] Every wrong voucher / party really is wrong, with the right rule (sheet 9)", ""),
        ("[   ] Data is dummy / anonymised", ""), ("", ""),
        ("Result:  [   ] Approved    [   ] Approved with changes    [   ] Rejected", ""),
        ("Notes / disagreements with the tool", ""), ("", ""), ("", ""), ("", ""),
        ("Signature", ""),
    ]
    for i, (a, b) in enumerate(items, start=2):
        put(ws, i, [a, b])
        ws.row_dimensions[i].height = 22
    page(ws, 1, [80, 50])

    out = pack / "VERIFICATION_SHEET.xlsx"
    wb.save(out)
    return out


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PACK
    print("written:", build(folder))
