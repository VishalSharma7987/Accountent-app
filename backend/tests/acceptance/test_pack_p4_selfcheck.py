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
