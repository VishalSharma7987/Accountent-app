"""Builds the printable verification sheet (Excel) for the Phase 3 (GST) test pack.

    python scripts/build_verification_sheet_p3.py [docs/test-packs/phase3-sunrise-traders-apr-2026]

Writes VERIFICATION_SHEET.xlsx into the pack folder. Everything shown is READ from the pack files (the inputs and the
hand-typed expected answers); the only arithmetic here is column totals for display. The accountants re-work each
section, tick it and sign. Same look as scripts/build_verification_sheet.py (Phase 1) and the Phase 2 sheet.
"""

import csv
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_verification_sheet import TOTAL_FILL, header, page, put, title

DEFAULT_PACK = ROOT / "docs" / "test-packs" / "phase3-sunrise-traders-apr-2026"
NUMERIC = {  # columns shown as Indian-format numbers
    "taxable_value", "cgst", "sgst", "igst", "cess", "invoice_value", "total_value", "party_amount", "books", "gstr1", "gstr3b",
    "register_eligible", "register_pending", "outstanding", "amount", "unit_rate", "discount", "taxable_diff", "igst_diff",
    "cgst_diff", "sgst_diff", "d_books_gstr1", "d_gstr1_gstr3b", "d_register_gstr3b", "input_ledger", "itc_register",
    "journal_dr_itc_reversal", "journal_cr_input_cgst", "journal_cr_input_sgst",
}
LEGAL_NOTE = ("Rates and rules used here are PENDING in the rule tables (docs/PHASE3_LEGAL_VALUES.md): example HSN rate rows, "
              "default services 18%, GTA reverse charge, Section 17(5), the 180-day rule, the B2C-large limit, composition rate "
              "and limit, return table numbers. The GSTR-2B file shape is not verified against a portal file.")


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
    name = f"Sunrise Traders - Phase 3 GST pack ({pack.name})"
    wb = Workbook()

    ws = wb.active
    ws.title = "1 Setup"
    title(ws, "Client, registration, parties and ledger roles (inputs)", name, 5)
    header(ws, 2, ["Item", "Detail 1", "Detail 2", "Detail 3", "Your check"])
    row = 3
    for r in read(pack, "gst_registrations.csv"):
        put(ws, row, ["GST registration", r["gstin"], r["registration_type"], f"{r['return_frequency']} from {r['effective_from']}", "[   ]"])
        row += 1
    for r in read(pack, "parties.csv"):
        put(ws, row, ["Party " + r["ledger_name"], r["gstin"] or "(no GSTIN)", f"state {r['state_code']}", r["gst_registration_type"], "[   ]"])
        row += 1
    for r in read(pack, "ledger_roles.csv"):
        put(ws, row, ["Ledger role " + r["role"], r["ledger_name"], "", "", "[   ]"])
        row += 1
    for r in read(pack, "items.csv"):
        put(ws, row, ["Item " + r["name"], r["hsn_sac"], r["item_kind"], r["uqc"], "[   ]"])
        row += 1
    put(ws, row + 1, ["Check: every GSTIN is synthetic and passes the check-digit method of docs/PHASE3_LEGAL_VALUES.md section 2   [   ]", "", "", "", ""])
    page(ws, 2, [44, 24, 18, 30, 10])

    # 2 invoices: the input item lines with the hand-worked tax next to them
    exp_items = {(r["ref_id"], r["item_no"]): r for r in read(pack, "expected_invoice_items.csv")}
    exp_inv = {r["ref_id"]: r for r in read(pack, "expected_invoices.csv")}
    rows, seen, counter = [], {}, {}
    for r in read(pack, "vouchers.csv"):
        counter[r["ref_id"]] = counter.get(r["ref_id"], 0) + 1
        item = exp_items[(r["ref_id"], str(counter[r["ref_id"]]))]
        first = r["ref_id"] not in seen
        seen[r["ref_id"]] = True
        rows.append({
            "ref": r["ref_id"] if first else "", "date": r["date"] if first else "", "type": r["voucher_type"] if first else "",
            "party": r["party_ledger"] if first else "", "place_of_supply": r["place_of_supply"] if first else "",
            "item": f"{r['item_name']} ({r['hsn_sac']})", "qty_x_rate": f"{r['quantity']} x {r['unit_rate']} less {r['discount']}",
            "rate": item["gst_rate"], "taxable_value": item["taxable_value"], "cgst": item["cgst"], "sgst": item["sgst"],
            "igst": item["igst"], "number": exp_inv[r["ref_id"]]["voucher_number"] if first else "",
            "party_amount": exp_inv[r["ref_id"]]["party_amount"] if first else "",
        })
    table_sheet(wb, "2 Invoices", "Invoice-mode vouchers with hand-worked tax (posting order)", name, rows,
                ["ref", "date", "type", "party", "place_of_supply", "item", "qty_x_rate", "rate", "taxable_value", "cgst", "sgst",
                 "igst", "number", "party_amount"], [7, 11, 11, 20, 8, 28, 22, 8, 14, 12, 12, 12, 18, 14], LEGAL_NOTE)

    table_sheet(wb, "3 Payments", "Payments made (not GST documents)", name, read(pack, "payments.csv"),
                ["ref_id", "date", "party_ledger", "bill_ref", "amount"], [8, 12, 26, 14, 14])
    table_sheet(wb, "4 ITC", "ITC register: expected status after evidence, GSTR-2B apply and claim", name, read(pack, "expected_itc.csv"),
                ["ref_id", "source", "status", "pending_reason", "blocked_category_key", "supplier_tax_paid", "claimed_in_period",
                 "claim_deadline", "cgst", "sgst", "igst", "cess"], [7, 9, 10, 12, 30, 14, 12, 12, 11, 11, 11, 8])
    table_sheet(wb, "5 GSTR-2B", "GSTR-2B April 2026 against the books", name, read(pack, "expected_reconciliation.csv"),
                ["class", "supplier_gstin", "doc_no", "books_ref", "taxable_diff", "igst_diff", "cgst_diff", "sgst_diff"],
                [16, 18, 10, 9, 13, 11, 11, 11],
                "2B file: gstr2b_042026.json (and gstr2b_052026.json for the other-period document). Shape not verified against the portal.")
    table_sheet(wb, "5b 2B totals", "Reconciliation totals (period-mismatch document left out of the 2B side)", name,
                read(pack, "expected_reconciliation_totals.csv"), ["side", "taxable_value", "igst", "cgst", "sgst", "cess"],
                [14, 16, 14, 14, 14, 10])
    table_sheet(wb, "6 GSTR-1", "GSTR-1 working (row key = party / document / date / place / rate)", name, read(pack, "expected_gstr1.csv"),
                ["table", "row_key", "quantity", "invoice_value", "taxable_value", "igst", "cgst", "sgst", "total_value"],
                [10, 62, 10, 14, 14, 12, 12, 12, 14], "GSTR-1 table numbering is to be confirmed against the portal.")
    table_sheet(wb, "7 GSTR-3B", "GSTR-3B working", name, read(pack, "expected_gstr3b.csv"),
                ["table", "row_key", "taxable_value", "igst", "cgst", "sgst", "cess"], [8, 28, 16, 12, 12, 12, 8],
                "The order of utilising ITC (Section 49) is not worked: the CA confirms it.")
    table_sheet(wb, "8 Tie-out", "Books against GSTR-1 against GSTR-3B; Input ledgers against the ITC register", name,
                read(pack, "expected_tieout.csv"),
                ["section", "head", "books", "gstr1", "gstr3b", "register_eligible", "register_pending", "d_books_gstr1",
                 "d_gstr1_gstr3b", "d_register_gstr3b"], [9, 14, 14, 14, 14, 14, 14, 11, 11, 11])
    table_sheet(wb, "9 180 days", "180-day check as on 01-10-2026, draft reversal and register tie", name, read(pack, "expected_exposure.csv"),
                ["list", "ref_id", "days", "due_on_day", "outstanding", "fraction", "igst", "cgst", "sgst", "cess"],
                [12, 8, 8, 12, 14, 10, 10, 11, 11, 8])
    ws = wb["9 180 days"]
    base = 4 + len(read(pack, "expected_exposure.csv"))
    header(ws, base, ["Reversal draft", "ref", "Dr ITC Reversal", "Cr Input CGST", "Cr Input SGST", "", "", "", "", "", "Your check"])
    for i, r in enumerate(read(pack, "expected_reversals.csv"), start=1):
        put(ws, base + i, ["Journal", r["ref_id"], Decimal(r["journal_dr_itc_reversal"]), Decimal(r["journal_cr_input_cgst"]),
                           Decimal(r["journal_cr_input_sgst"]), "", "", "", "", "", "[   ]"], (3, 4, 5))
    tie_row = base + 3
    header(ws, tie_row, ["Register tie", "head", "Input ledger", "ITC register", "", "", "", "", "", "", "Your check"])
    for i, r in enumerate(read(pack, "expected_register_tie.csv"), start=1):
        put(ws, tie_row + i, ["Input ledgers v register", r["head"], Decimal(r["input_ledger"]), Decimal(r["itc_register"]),
                              "", "", "", "", "", "", "[   ]"], (3, 4))
    table_sheet(wb, "10 Composition", "Composition client (Sai Bakers), quarter April-June 2026", name, read(pack, "expected_composition.csv"),
                ["field", "value"], [24, 22], "Rate 1% (trader) and the limit of 1.5 crore are PENDING in the rule table.")
    table_sheet(wb, "11 Wrong items", "Deliberately wrong items: the tool must refuse each with the rule named", name,
                read(pack, "wrong_cases.csv"), ["case_id", "kind", "description", "expected_rule_id"], [8, 22, 70, 24])
    table_sheet(wb, "12 Ledgers", "Ledger balances after posting (as on 30-04-2026)", name, read(pack, "expected_ledger_balances.csv"),
                ["ledger_name", "side", "amount"], [26, 8, 16])

    ws = wb.create_sheet("13 Sign-off")
    title(ws, "Sign-off", name, 2)
    items = [
        ("Verified by (name, role)", ""), ("Date verified (YYYY-MM-DD)", ""),
        ("Method (T-accounts on paper / Tally / Excel)", ""), ("", ""),
        ("[   ] Invoice tax re-worked per item; party amounts agree (sheet 2)", ""),
        ("[   ] ITC statuses agree with the rules (sheet 4); blocked and reverse-charge entries judged right", ""),
        ("[   ] GSTR-2B classes right: matched, value, GSTIN, other period, only in books, only in 2B (sheet 5)", ""),
        ("[   ] GSTR-1 tables re-worked, totals agree (sheet 6)", ""),
        ("[   ] GSTR-3B figures re-worked (sheet 7)", ""),
        ("[   ] Tie-out: no difference between books and the two returns (sheet 8)", ""),
        ("[   ] 180-day days counted, unpaid share and draft reversal checked (sheet 9)", ""),
        ("[   ] Composition quarter checked (sheet 10)", ""),
        ("[   ] Every wrong item really is wrong, with the right rule (sheet 11)", ""),
        ("[   ] Pending legal values (see the note on sheet 2) are listed for the CA", ""),
        ("[   ] Data is dummy / synthetic (no real GSTIN, PAN, names)", ""), ("", ""),
        ("Result:  [   ] Approved    [   ] Approved with changes    [   ] Rejected", ""),
        ("Notes / disagreements with the tool", ""), ("", ""), ("", ""), ("", ""),
        ("Signature", ""),
    ]
    for i, (a, b) in enumerate(items, start=2):
        put(ws, i, [a, b], fill=TOTAL_FILL if a.startswith("Result") else None)
        ws.row_dimensions[i].height = 22
    page(ws, 1, [96, 40])

    out = pack / "VERIFICATION_SHEET.xlsx"
    wb.save(out)
    return out


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PACK
    print("written:", build(folder))
