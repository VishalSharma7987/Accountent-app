"""Writes the INPUT files of the Phase 8 test pack docs/test-packs/phase8-audit-checks-2026-27 (synthetic data only):

    python scripts/build_pack_p8_inputs.py

The pack is a small trading business ("Sunrise Audit Traders", proprietorship, GST registered from 01-09-2026, TDS deductees, MSME suppliers,
a cash book, a bank, two stock items). Its books (FY 2026-27 up to 31-10-2026 plus a little of FY 2025-26) are built from these files by the
acceptance runner. Exactly ONE error is injected per audit check A-01 .. A-18; every other voucher is a clean control that the audit must not
flag. This script only writes INPUT (what the books contain). It never computes an expected result: the expected_*.csv files are typed by hand
(see WORKING.md) and the runner compares the audit report with them.

Voucher refs (V-xx = FY 2026-27, P-xx = FY 2025-26) are stable names used by the expected files. Voucher numbers are given by this script
(sequential per type and year in date order) except the sales series, where 0003 is deliberately skipped (A-04). Every purchase / payment has
a linked supporting document except V-08 (A-03). posted_at is the voucher date at 12:00 Indian time unless a row says otherwise (A-14).
"""

import csv
import datetime as dt
from pathlib import Path

PACK = Path(__file__).resolve().parents[1] / "docs" / "test-packs" / "phase8-audit-checks-2026-27"
PREFIX = {"payment": "PAY", "receipt": "REC", "sales": "SAL", "purchase": "PUR", "journal": "JRN", "contra": "CON"}

# (name, group code, gst role)
LEDGERS = [
    ("HDFC Bank", "bank_accounts", ""), ("Petty Cash", "cash_in_hand", ""),
    ("Kumar Steel", "sundry_creditors", ""), ("Sharma Traders", "sundry_creditors", ""), ("Verma Cooling Solutions", "sundry_creditors", ""),
    ("Reliable Repairs", "sundry_creditors", ""), ("Gupta Enterprises", "sundry_creditors", ""), ("Patel Plastics", "sundry_creditors", ""),
    ("Raj Contractors", "sundry_creditors", ""), ("Mehta Builders", "sundry_creditors", ""), ("Dutta Associates", "sundry_creditors", ""),
    ("Bose Contractors", "sundry_creditors", ""), ("Desai Services", "sundry_creditors", ""), ("Singh Brothers", "sundry_creditors", ""),
    ("Mehta & Co", "sundry_debtors", ""), ("Gamma Retail", "sundry_debtors", ""),
    ("TDS Payable", "duties_taxes", ""),
    ("Output CGST", "duties_taxes", "output_cgst"), ("Output SGST", "duties_taxes", "output_sgst"), ("Output IGST", "duties_taxes", "output_igst"),
    ("Input CGST", "duties_taxes", "input_cgst"), ("Input SGST", "duties_taxes", "input_sgst"), ("Input IGST", "duties_taxes", "input_igst"),
]
# party masters: only the two bill-wise MSME suppliers carry bills; every other party is not bill-wise
PARTIES = [
    # ledger, bill_wise, msme_category, udyam_no, udyam_registration_date, msme_activity
    ("Gupta Enterprises", "yes", "micro", "UDYAM-MH-12-1234567", "2021-04-01", "manufacturing"),
    ("Patel Plastics", "yes", "small", "UDYAM-MH-12-7654321", "2022-06-15", "manufacturing"),
]
OPENINGS = [("Cash", "300000.00", "0.00"), ("HDFC Bank", "400000.00", "0.00"), ("Anil Verma Capital A/c", "0.00", "700000.00")]

V: list = []


def v(ref, fy, vtype, date, party, reference, doc, posted, narration, *lines):
    V.append((ref, fy, vtype, date, party, reference, doc, posted, narration, lines))


def dr(ledger, amount, *alloc):
    return (ledger, amount, "0.00", *alloc)


def cr(ledger, amount, *alloc):
    return (ledger, "0.00", amount, *alloc)


Y, N = "yes", "no"
v("V-01", "F26", "receipt", "2026-04-06", "Gamma Retail", "", N, "", "Cash received from Gamma Retail", dr("Cash", "42350.00"), cr("Gamma Retail", "42350.00"))
v("V-02", "F26", "sales", "2026-04-08", "Gamma Retail", "S-2601", N, "", "Goods sold to Gamma Retail", dr("Gamma Retail", "61850.00"), cr("Sales", "61850.00"))
v("V-03", "F26", "purchase", "2026-04-10", "Kumar Steel", "KS-1001", Y, "", "Steel purchased from Kumar Steel", dr("Purchases", "48720.00"), cr("Kumar Steel", "48720.00"))
v("V-04", "F26", "purchase", "2026-05-12", "Kumar Steel", "INV-17", Y, "", "Steel purchased from Kumar Steel", dr("Purchases", "23450.00"), cr("Kumar Steel", "23450.00"))
v("V-05", "F26", "purchase", "2026-05-14", "Kumar Steel", "inv 17 ", Y, "", "Steel purchased from Kumar Steel", dr("Purchases", "23450.00"), cr("Kumar Steel", "23450.00"))
v("V-06", "F26", "purchase", "2026-05-18", "Sharma Traders", "INV-17", Y, "", "Goods purchased from Sharma Traders", dr("Purchases", "17300.00"), cr("Sharma Traders", "17300.00"))
v("V-07", "F26", "purchase", "2026-05-20", "Kumar Steel", "INV-18", Y, "", "Steel purchased from Kumar Steel", dr("Purchases", "19880.00"), cr("Kumar Steel", "19880.00"))
v("V-08", "F26", "purchase", "2026-05-26", "Kumar Steel", "INV-21", N, "", "Steel purchased from Kumar Steel", dr("Purchases", "9640.00"), cr("Kumar Steel", "9640.00"))
v("V-09", "F26", "sales", "2026-06-02", "Gamma Retail", "S-2602", N, "", "Goods sold to Gamma Retail", dr("Gamma Retail", "74400.00"), cr("Sales", "74400.00"))
v("V-10", "F26", "sales", "2026-06-09", "Gamma Retail", "S-2603", N, "", "Goods sold to Gamma Retail", dr("Gamma Retail", "58125.00"), cr("Sales", "58125.00"))
v("V-11", "F26", "payment", "2026-06-10", "Raj Contractors", "", Y, "", "Paid to Raj Contractors for site work", dr("Raj Contractors", "101500.00"), cr("HDFC Bank", "101500.00"))
v("V-12", "F26", "payment", "2026-06-12", "Dutta Associates", "", Y, "", "Paid to Dutta Associates for site work, tax deducted",
  dr("Dutta Associates", "105750.00"), cr("HDFC Bank", "104692.00"), cr("TDS Payable", "1058.00"))
v("V-13", "F26", "payment", "2026-06-15", "Mehta Builders", "", Y, "", "Paid to Mehta Builders for site work, tax deducted",
  dr("Mehta Builders", "108250.00"), cr("HDFC Bank", "107850.00"), cr("TDS Payable", "400.00"))
v("V-14", "F26", "payment", "2026-06-17", "Bose Contractors", "", Y, "", "Paid to Bose Contractors for site work, tax deducted",
  dr("Bose Contractors", "103200.00"), cr("HDFC Bank", "102168.00"), cr("TDS Payable", "1032.00"))
v("V-15", "F26", "payment", "2026-06-18", "Desai Services", "", Y, "", "Paid to Desai Services for minor work", dr("Desai Services", "22750.00"), cr("HDFC Bank", "22750.00"))
v("V-16", "F26", "payment", "2026-07-03", "Verma Cooling Solutions", "", Y, "", "Paid to Verma Cooling Solutions", dr("Verma Cooling Solutions", "18750.50"), cr("HDFC Bank", "18750.50"))
v("V-17", "F26", "payment", "2026-07-06", "Verma Cooling Solutions", "", Y, "", "Paid to Verma Cooling Solutions", dr("Verma Cooling Solutions", "18750.50"), cr("HDFC Bank", "18750.50"))
v("V-18", "F26", "sales", "2026-07-07", "Gamma Retail", "S-2604", N, "", "Goods sold to Gamma Retail", dr("Gamma Retail", "66990.00"), cr("Sales", "66990.00"))
v("V-19", "F26", "purchase", "2026-07-15", "Gupta Enterprises", "GE/771", Y, "", "Goods purchased from Gupta Enterprises",
  dr("Purchases", "31180.00"), cr("Gupta Enterprises", "31180.00", "new_ref", "GE/771", "2026-08-14"))
v("V-20", "F26", "purchase", "2026-07-20", "Kumar Steel", "KS-1010", Y, "2026-08-12T12:00:00+05:30", "Steel purchased from Kumar Steel",
  dr("Purchases", "12430.00"), cr("Kumar Steel", "12430.00"))
v("V-21", "F26", "payment", "2026-07-27", "Verma Cooling Solutions", "", Y, "", "Paid to Verma Cooling Solutions", dr("Verma Cooling Solutions", "18750.50"), cr("HDFC Bank", "18750.50"))
v("V-22", "F26", "payment", "2026-07-28", "Gupta Enterprises", "", Y, "", "Paid to Gupta Enterprises against GE/771",
  dr("Gupta Enterprises", "31180.00", "against_ref", "GE/771", ""), cr("HDFC Bank", "31180.00"))
v("V-23", "F26", "receipt", "2026-08-03", "Gamma Retail", "", N, "", "Received from Gamma Retail by bank transfer", dr("HDFC Bank", "150000.40"), cr("Gamma Retail", "150000.40"))
v("V-24", "F26", "payment", "2026-08-14", "Sharma Traders", "", Y, "", "Cash paid to Sharma Traders", dr("Sharma Traders", "6000.00"), cr("Cash", "6000.00"))
v("V-25", "F26", "payment", "2026-08-14", "Sharma Traders", "", Y, "", "Cash paid to Sharma Traders", dr("Sharma Traders", "5000.00"), cr("Cash", "5000.00"))
v("V-26", "F26", "payment", "2026-08-14", "Sharma Traders", "", Y, "", "Paid to Sharma Traders by bank", dr("Sharma Traders", "20150.00"), cr("HDFC Bank", "20150.00"))
v("V-27", "F26", "payment", "2026-08-17", "Sharma Traders", "", Y, "", "Cash paid to Sharma Traders", dr("Sharma Traders", "10000.00"), cr("Cash", "10000.00"))
v("V-28", "F26", "purchase", "2026-08-25", "Reliable Repairs", "RR-2026-08", Y, "", "Repair work billed by Reliable Repairs",
  dr("Repairs & Maintenance", "840250.00"), cr("Reliable Repairs", "840250.00"))
v("V-29", "F26", "purchase", "2026-09-01", "Gupta Enterprises", "GE/884", Y, "", "Goods purchased from Gupta Enterprises",
  dr("Purchases", "38260.00"), cr("Gupta Enterprises", "38260.00", "new_ref", "GE/884", "2026-10-01"))
v("V-30", "F26", "receipt", "2026-09-03", "Mehta & Co", "", N, "", "Cash received from Mehta & Co", dr("Cash", "150000.50"), cr("Mehta & Co", "150000.50"))
v("V-31", "F26", "receipt", "2026-09-03", "Mehta & Co", "", N, "", "Cash received from Mehta & Co", dr("Cash", "49999.50"), cr("Mehta & Co", "49999.50"))
v("V-32", "F26", "receipt", "2026-09-04", "Gamma Retail", "", N, "", "Cash received from Gamma Retail", dr("Cash", "199999.99"), cr("Gamma Retail", "199999.99"))
v("V-33", "F26", "journal", "2026-09-06", "", "", N, "", "Mobile bill of August accrued", dr("Telephone & Internet", "3450.00"), cr("Verma Cooling Solutions", "3450.00"))
v("V-34", "F26", "payment", "2026-09-08", "", "", Y, "", "Tea, stationery and courier paid from petty cash", dr("Office Expenses", "4200.00"), cr("Petty Cash", "4200.00"))
v("V-35", "F26", "contra", "2026-09-10", "", "", N, "", "Petty cash refilled from cash", dr("Petty Cash", "5000.00"), cr("Cash", "5000.00"))
v("V-36", "F26", "journal", "2026-09-15", "", "", N, "", "Rent for September payable to Singh Brothers", dr("Rent", "50000.00"), cr("Singh Brothers", "50000.00"))
v("V-37", "F26", "journal", "2026-10-05", "", "", N, "", "Electricity bill of September accrued", dr("Electricity", "25000.50"), cr("Verma Cooling Solutions", "25000.50"))
v("V-38", "F26", "journal", "2026-10-07", "", "", N, "", "Stationery accrued", dr("Printing & Stationery", "9000.00"), cr("Verma Cooling Solutions", "9000.00"))
v("V-39", "F26", "payment", "2026-10-12", "Singh Brothers", "", Y, "", "Paid to Singh Brothers", dr("Singh Brothers", "30150.00"), cr("HDFC Bank", "30150.00"))
v("V-40", "F26", "journal", "2026-10-20", "", "", N, "", "Stationery accrued", dr("Printing & Stationery", "2760.00"), cr("Verma Cooling Solutions", "2760.00"))
v("V-41", "F26", "purchase", "2026-10-21", "Patel Plastics", "PP/310", Y, "", "Goods purchased from Patel Plastics",
  dr("Purchases", "27540.00"), cr("Patel Plastics", "27540.00", "new_ref", "PP/310", "2026-11-20"))
# the previous financial year (only what A-15 and the Form 3CD derivation need)
v("P-01", "F25", "purchase", "2025-08-12", "Reliable Repairs", "RR-2025-08", Y, "", "Repair work billed by Reliable Repairs",
  dr("Repairs & Maintenance", "260150.00"), cr("Reliable Repairs", "260150.00"))
v("P-02", "F25", "payment", "2025-09-15", "Sharma Traders", "", Y, "", "Cash paid to Sharma Traders", dr("Sharma Traders", "12500.00"), cr("Cash", "12500.00"))
v("P-03", "F25", "payment", "2025-10-10", "Reliable Repairs", "", Y, "", "Paid to Reliable Repairs", dr("Reliable Repairs", "196350.00"), cr("HDFC Bank", "196350.00"))

# the A-04 gap: the third sales voucher of the year carries number 0004 (0003 was never issued)
NUMBER_OVERRIDE = {"V-10": 4, "V-18": 5}


def numbers():
    seq: dict[tuple, int] = {}
    out = {}
    for ref, fy, vtype, date, *_ in sorted(V, key=lambda x: (x[1], x[2], x[3], x[0])):
        key = (fy, vtype)
        seq[key] = seq.get(key, 0) + 1
        n = NUMBER_OVERRIDE.get(ref, seq[key])
        year = "2026-27" if fy == "F26" else "2025-26"
        out[ref] = f"{PREFIX[vtype]}/{year}/{n:04d}"
    return out


def write(name, header, rows):
    with (PACK / name).open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    PACK.mkdir(parents=True, exist_ok=True)
    nums = numbers()
    write("ledgers.csv", ["name", "group", "gst_role"], LEDGERS)
    write("parties.csv", ["ledger", "bill_wise", "msme_category", "udyam_no", "udyam_registration_date", "msme_activity"], PARTIES)
    write("openings.csv", ["ledger", "debit", "credit"], OPENINGS)
    write("vouchers.csv", ["ref", "fy", "type", "date", "number", "party", "reference_no", "document", "posted_at", "narration"],
          [(ref, fy, vt, d, nums[ref], party, reference, doc, posted, narr) for ref, fy, vt, d, party, reference, doc, posted, narr, _ in V])
    write("lines.csv", ["ref", "line_no", "ledger", "debit", "credit", "alloc_kind", "alloc_ref", "alloc_due"],
          [(ref, i, ln[0], ln[1], ln[2], *(ln[3:] if len(ln) > 3 else ("", "", ""))) for ref, *_, lines in V for i, ln in enumerate(lines, start=1)])
    write("tds_deductees.csv", ["ledger", "pan", "deductee_type", "default_nature"],
          [("Raj Contractors", "ABCPR1234K", "individual", "contractor"), ("Mehta Builders", "ABCPM2345L", "individual", "contractor"),
           ("Dutta Associates", "ABCPD3456M", "individual", "contractor"), ("Bose Contractors", "ABCPB4567N", "individual", "contractor"),
           ("Desai Services", "ABCPD5678P", "individual", "contractor")])
    # deduction items typed by the accountant: voucher, line of the tax, deductee, nature, base, tax deducted
    write("tds_items.csv", ["voucher", "tds_line_no", "deductee", "nature", "base", "rate_applied", "tax_deducted"],
          [("V-12", 3, "Dutta Associates", "contractor", "105750.00", "1", "1058.00"), ("V-13", 3, "Mehta Builders", "contractor", "108250.00", "1", "400.00"),
           ("V-14", 3, "Bose Contractors", "contractor", "103200.00", "1", "1032.00")])
    # challans: the first pays two items on time (due 07-07-2026), the second pays one item 13 days late
    write("tds_challans.csv", ["challan", "quarter", "bsr_code", "deposit_date", "serial_no", "tax_amount", "item_voucher", "allocated"],
          [("CH-1", 1, "0510308", "2026-07-06", "101", "1432.00", "V-13", "400.00"), ("CH-1", 1, "0510308", "2026-07-06", "101", "1432.00", "V-14", "1032.00"),
           ("CH-2", 1, "0510308", "2026-07-20", "102", "1058.00", "V-12", "1058.00")])
    cols = ["return_period", "gstr1_taxable_value", "gstr1_igst", "gstr1_cgst", "gstr1_sgst", "gstr1_cess"]
    write("gst_filed.csv", cols, [("2026-09-01", "0.00", "0.00", "0.00", "0.00", "0.00"), ("2026-10-01", "50000.00", "0.00", "4500.00", "4500.00", "0.00")])
    write("stock_items.csv", ["item", "hsn", "godown", "opening_qty", "opening_value"],
          [("Steel Rod 12mm", "7214", "Main Godown", "10.000", "5000.00"), ("Copper Wire 2.5mm", "7408", "Main Godown", "20.000", "9000.00")])
    write("stock_journals.csv", ["journal", "number", "date", "item", "godown", "quantity", "reason_code", "reason_note"],
          [("SJ-1", "SJ/2026-27/0001", "2026-08-20", "Copper Wire 2.5mm", "Main Godown", "5.000", "damage", "Damaged in transit"),
           ("SJ-2", "SJ/2026-27/0002", "2026-09-15", "Steel Rod 12mm", "Main Godown", "12.000", "loss", "Rods written off after stock count")])
    write("holidays.csv", ["date", "name", "kind"], [("2026-10-20", "Dussehra (client calendar)", "client")])
    write("related_parties.csv", ["ledger", "relationship"], [("Singh Brothers", "Landlord - brother of the proprietor")])
    # what the books' own log shows about the lock of July 2026 (audit_log rows with their original time stamps)
    write("lock_events.csv", ["period_start", "action", "at", "actor", "reason"],
          [("2026-07-01", "lock", "2026-08-05T10:00:00+05:30", "ca", ""),
           ("2026-07-01", "unlock", "2026-08-10T11:00:00+05:30", "ca", "Late bill received from supplier")])
    print("written", PACK)
    for ref, fy, vt, d, party, reference, doc, posted, narr, lines in sorted(V, key=lambda x: (x[1], x[3], x[0])):
        total = sum(float(ln[1]) for ln in lines)
        print(ref, d, dt.date.fromisoformat(d).strftime("%a"), vt, nums[ref], f"{total:,.2f}", party)


if __name__ == "__main__":
    main()
