"""Internal consistency of the Phase 4 pack docs/test-packs/phase4-greenfield-contractors-2026 (no database, no service).

Plain csv / Decimal addition only; the totals asserted here are typed literally (hand-calculated, see WORKING.md).
"""

import csv
from decimal import Decimal as D
from pathlib import Path

from pack_loader_p4 import load_pack_p4

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "phase4-greenfield-contractors-2026"


def rows(name: str) -> list[dict]:
    with open(PACK / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_pack_loads_and_counts():
    pack = load_pack_p4(PACK)
    assert len(pack.vouchers) == 28 and len(pack.challans) == 5 and len(pack.wrong_cases) == 11
    assert len(pack.deductees) == 10 and len(pack.certificates) == 2 and len(pack.links) == 1
    assert [v.date for v in pack.vouchers] == sorted(v.date for v in pack.vouchers)
    assert set(pack.expected) >= {"expected_items", "expected_recon", "expected_interest"}


def test_every_voucher_has_one_expected_item_and_number():
    refs = [r["ref_id"] for r in rows("vouchers.csv")]
    assert [r["ref_id"] for r in rows("expected_items.csv")] == refs
    assert [r["ref_id"] for r in rows("expected_vouchers.csv")] == refs
    assert [r["ref_id"] for r in rows("expected_register.csv")] == refs


def test_expected_item_arithmetic_is_consistent():
    """tax = round half up (base x rate / 100) less tax already deducted on the base; cumulative after = before + payment."""
    for r in rows("expected_items.csv"):
        assert D(r["cumulative_before"]) + D(r["payment_amount"]) == D(r["cumulative_after"]), r["ref_id"]
        if r["rate_reason"] == "below_threshold":
            assert (D(r["taxable_base"]), D(r["tds_amount"])) == (0, 0), r["ref_id"]
        elif r["rate_applied"]:  # V71 (blended certificate rate) states no rate
            gross = (D(r["taxable_base"]) * D(r["rate_applied"]) / 100).quantize(D(1), rounding="ROUND_HALF_UP")
            assert gross - D(r["tax_already_on_base"]) == D(r["tds_amount"]), r["ref_id"]


def test_act_follows_the_earlier_date():
    """01-04-2026 starts the Act of 2025; the commission credited on 28-03-2026 and paid on 03-04-2026 stays under the 1961 Act."""
    for r in rows("expected_items.csv"):
        want = "it_act_1961" if r["event_date"] <= "2026-03-31" else "it_act_2025"
        assert r["act"] == want, r["ref_id"]
    v03 = next(r for r in rows("vouchers.csv") if r["ref_id"] == "V03")
    assert (v03["credit_date"], v03["payment_date"], v03["date"]) == ("2026-03-28", "2026-04-03", "2026-04-03")


def test_challans_tie_to_the_items_and_to_the_interest():
    items = {r["ref_id"]: D(r["tds_amount"]) for r in rows("expected_items.csv")}
    interest = {r["ref_id"]: D(r["interest_late_deposit"]) for r in rows("expected_interest.csv")}
    for ch in rows("challans.csv"):
        parts = [p.split(":") for p in ch["allocations"].split("+")]
        assert sum(D(a) for _, a in parts) == D(ch["tax"]), ch["ref_id"]
        assert all(D(a) == items[ref] for ref, a in parts), ch["ref_id"]  # every challan pays its items in full
    ch2 = next(c for c in rows("challans.csv") if c["ref_id"] == "CH2")
    assert sum(interest[p.split(":")[0]] for p in ch2["allocations"].split("+")) == D(ch2["interest"]) == D("921.00")


def test_register_totals_and_ledgers_agree():
    reg = rows("expected_register.csv")
    assert sum(D(r["tds_amount"]) for r in reg) == D("59231.00")  # 9,000.00 (2025-26) + 50,231.00 (2026-27), TDS and TCS together
    bal = {(r["as_on"], r["ledger_name"]): D(r["amount"]) for r in rows("expected_ledger_balances.csv")}
    assert bal[("2026-03-31", "TDS Payable")] + bal[("2026-03-31", "TCS Payable")] == D("8000.00")  # V03 is booked in April
    assert bal[("2026-11-30", "TDS Payable")] + bal[("2026-11-30", "TCS Payable")] == D("51231.00")  # 50,231.00 + V03's 1,000.00


def test_return_totals_are_the_sum_of_the_rows():
    got: dict[str, list[dict]] = {}
    for r in rows("expected_return_rows.csv"):
        got.setdefault(r["working"], []).append(r)
    for t in rows("expected_return_totals.csv"):
        mine = got[t["working"]]
        assert len(mine) == int(t["row_count"]), t["working"]
        for col in ("amount_paid", "tax_deducted", "tax_deposited"):
            assert sum(D(r[col]) for r in mine) == D(t[col]), (t["working"], col)
        assert D(t["challan_total"]) == D(t["challan_tax"]) + D(t["challan_interest"]), t["working"]


def test_reconciliation_summary_counts_the_rows():
    rec = rows("expected_recon.csv")
    summary = {r["class"]: int(r["count"]) for r in rows("expected_recon_summary.csv")}
    for cls, n in summary.items():
        assert sum(1 for r in rec if r["class"] == cls) == n, cls
    assert sum(summary.values()) == len(rec) == 17
    # 16 posted items carry tax in 2026-27; the 8 statement rows pair 7 of them, one row has no book entry
    assert sum(1 for r in rows("expected_items.csv") if r["event_date"] >= "2026-04-01" and D(r["tds_amount"]) > 0) == 16
    assert summary["only_in_books"] == 16 - 7


# ---- Phase 4.1 addendum (p41 folder): arithmetic typed by hand, checked against the csv files --------------------------------
P41 = PACK / "p41"


def rows41(name: str) -> list[dict]:
    with open(P41 / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def item41(ref: str) -> dict:
    return next(r for r in rows41("expected_items.csv") if r["ref_id"] == ref)


def test_p41_pack_loads_and_every_voucher_has_an_expected_item():
    from pack_loader_p41 import load_pack_p41

    pack = load_pack_p41(P41)
    assert len(pack.vouchers) == 11 and len(pack.wrong_cases) == 3 and len(pack.certificates) == 1
    assert sorted(v.ref_id for v in pack.vouchers) == sorted(r["ref_id"] for r in rows41("expected_items.csv"))
    for r in rows41("expected_items.csv"):
        assert D(r["cumulative_before"]) + D(r["payment_amount"]) == D(r["cumulative_after"]), r["ref_id"]


def test_p41_mixed_rate_crossing_is_worked_per_payment():
    # 20,000 with no PAN then (20% = 4,000) + 25,000 (2% = 500) + 40,000 (2% = 800 less 800 already = 0) + this 30,000 (2% = 600)
    m4 = item41("M4")
    assert (D(m4["cumulative_after"]), D(m4["taxable_base"]), D(m4["tax_already_on_base"]), D(m4["tds_amount"])) == (D("115000.00"), D("115000.00"), D("800.00"), D("5100.00"))
    assert D(20000) * 20 / 100 + D(25000) * 2 / 100 + (D(40000) * 2 / 100 - 800) + D(30000) * 2 / 100 == D(5100)
    assert ((D(5100) + D(800)) * 100 / D(115000)).quantize(D("0.0001"), rounding="ROUND_HALF_UP") == D(m4["effective_rate"]) == D("5.1304")
    assert [item41(r)["tds_amount"] for r in ("M1", "M2", "M3")] == ["0.00", "0.00", "800.00"]


def test_p41_partial_certificate_shows_both_rates():
    # limit 1,50,000: Z1 120,000 at 0.5% = 600; Z2 60,000: 30,000 left at 0.5% = 150 + 30,000 at 2% = 600 = 750 = 1.25% of 60,000
    z1, z2 = item41("Z1"), item41("Z2")
    assert (z1["tds_amount"], z1["certificate_rate"], z1["effective_rate"]) == ("600.00", "0.5", "0.5")
    assert (z2["tds_amount"], z2["certificate_rate"], z2["effective_rate"]) == ("750.00", "0.5", "1.25")
    assert D(30000) * D("0.5") / 100 + D(30000) * 2 / 100 == D(750) == D(60000) * D("1.25") / 100


def test_p41_gst_invoice_tax_is_on_the_value_without_gst_and_the_lines_balance():
    g1 = item41("G1")
    assert (D(g1["taxable_base"]), D(g1["tds_amount"])) == (D("100000.00"), D("2000.00"))  # 2% of 1,00,000.00, not of 1,18,000.00
    lines = [r for r in rows41("expected_lines.csv") if r["ref_id"] == "G1"]
    assert sum(D(r["debit"]) for r in lines) == sum(D(r["credit"]) for r in lines) == D("118000.00")
    assert next(r for r in lines if r["ledger_name"] == "Mumbai Works Pvt Ltd")["credit"] == "116000.00"  # 1,18,000.00 less the tax


def test_p41_rent_by_an_individual_not_tax_audited_is_194_IB_at_2_percent_on_the_month_above_50000():
    rent = {r: item41(r) for r in ("R1", "R2", "R3", "R4")}
    assert {r["nature_key"] for r in rent.values()} == {"rent_194ib"}
    assert (rent["R1"]["taxable_base"], rent["R1"]["tds_amount"]) == ("60000.00", "1200.00")  # 2% of 60,000
    assert (rent["R2"]["tds_amount"], rent["R2"]["rate_reason"]) == ("0.00", "below_threshold")  # exactly 50,000: not above
    assert (rent["R3"]["tds_amount"], rent["R4"]["taxable_base"], rent["R4"]["tds_amount"]) == ("0.00", "60000.00", "1200.00")  # August 30,000 + 30,000
    r1 = [r for r in rows41("expected_lines.csv") if r["ref_id"] == "R1"]
    assert [(r["ledger_name"], r["debit"], r["credit"]) for r in r1] == [
        ("Mrs Sharma", "60000.00", "0.00"), ("HDFC Bank", "0.00", "58800.00"), ("TDS Payable", "0.00", "1200.00")]
