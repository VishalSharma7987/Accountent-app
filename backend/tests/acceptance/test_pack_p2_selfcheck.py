"""Internal consistency of the Phase 2 pack docs/test-packs/abc-traders-phase2-jun-2026.

Plain csv / yaml / json and Decimal addition only: no project service, engine or loader is used. Expected values are
typed literally (hand-calculated, see the pack's WORKING.md).
"""

import csv
import json
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

import yaml

PACK = Path(__file__).resolve().parents[3] / "docs" / "test-packs" / "abc-traders-phase2-jun-2026"


def rows(name: str) -> list[dict]:
    with open(PACK / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def vouchers() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows("vouchers.csv"):
        out[r["ref_id"]].append(r)
    return out


def test_client_yaml():
    c = yaml.safe_load((PACK / "client.yaml").read_text(encoding="utf-8"))
    assert str(c["fy_start"]) == "2026-04-01" and str(c["pack_end_date"]) == "2026-06-30"
    assert c["entity_type"] == "proprietorship" and c["proprietor_name"] == "Amit Verma"


def test_opening_dr_equals_cr_and_both_files_agree():
    led = rows("ledgers.csv")
    assert sum(D(r["opening_dr"]) for r in led) == D("1107500.00")
    assert sum(D(r["opening_cr"]) for r in led) == D("1107500.00")
    compact = {r["ledger_name"]: (D(r["opening_dr"]), D(r["opening_cr"])) for r in rows("opening_balances.csv")}
    full = {r["ledger_name"]: (D(r["opening_dr"]), D(r["opening_cr"])) for r in led
            if D(r["opening_dr"]) or D(r["opening_cr"])}
    assert compact == full


def test_opening_bills_add_up_to_each_party_opening():
    led = {r["ledger_name"]: D(r["opening_dr"]) - D(r["opening_cr"]) for r in rows("ledgers.csv")}
    by_party: dict[str, D] = defaultdict(D)
    for b in rows("opening_bills.csv"):
        assert b["due_date"] >= b["bill_date"]
        by_party[b["ledger_name"]] += D(b["amount"]) * (1 if b["side"] == "Dr" else -1)
    parties = {r["ledger_name"] for r in rows("parties.csv")}
    assert set(by_party) == parties
    for name, total in by_party.items():
        assert total == led[name], name
    assert sum(t for t in by_party.values() if t > 0) == D("330000.00")
    assert -sum(t for t in by_party.values() if t < 0) == D("335000.00")


def test_every_voucher_balances_and_has_one_sided_lines():
    for ref, lines in vouchers().items():
        assert len({(ln["date"], ln["voucher_type"], ln["narration"], ln["reference_no"]) for ln in lines}) == 1, ref
        assert len(lines) >= 2 and lines[0]["narration"], ref
        for ln in lines:
            assert (D(ln["debit"]) > 0) != (D(ln["credit"]) > 0), ref
        assert sum(D(ln["debit"]) for ln in lines) == sum(D(ln["credit"]) for ln in lines), ref
    assert len(vouchers()) == 49


def test_allocations_sum_to_party_line_amount():
    parties = {r["ledger_name"] for r in rows("parties.csv")}
    vs = vouchers()
    alloc: dict[tuple[str, int], D] = defaultdict(D)
    for a in rows("allocations.csv"):
        assert a["kind"] in ("new_ref", "against_ref", "advance", "on_account")
        assert (a["kind"] == "on_account") == (a["bill_ref"] == "")
        alloc[(a["ref_id"], int(a["line_no"]))] += D(a["amount"])
    for ref, lines in vs.items():
        for no, ln in enumerate(lines, start=1):
            amount = D(ln["debit"]) + D(ln["credit"])
            if ln["ledger_name"] in parties:
                assert alloc.pop((ref, no)) == amount, (ref, no)
            else:
                assert (ref, no) not in alloc, (ref, no)  # no allocation on non-party lines
    assert alloc == {}


def test_allocation_sides_follow_rules_B02():
    """new_ref only on the natural side (debtor Dr, creditor Cr); advance only on the opposite side."""
    led = {r["ledger_name"]: r["group_name"] for r in rows("ledgers.csv")}
    vs = vouchers()
    for a in rows("allocations.csv"):
        ln = vs[a["ref_id"]][int(a["line_no"]) - 1]
        debtor, dr = led[ln["ledger_name"]] == "Sundry Debtors", D(ln["debit"]) > 0
        natural = dr == debtor
        if a["kind"] == "new_ref":
            assert natural, a
        if a["kind"] == "advance":
            assert not natural, a


def test_expected_trial_balance_ties_and_matches_ledgers():
    tb = rows("expected_trial_balance.csv")
    total = tb.pop()
    assert total["group_name"] == "TOTAL"
    assert sum(D(r["dr"]) for r in tb) == D(total["dr"]) == D("1646800.00")
    assert sum(D(r["cr"]) for r in tb) == D(total["cr"]) == D("1646800.00")
    assert {r["ledger_name"]: r["group_name"] for r in tb} == {r["ledger_name"]: r["group_name"] for r in rows("ledgers.csv")}


def test_expected_trial_balance_equals_plain_addition_of_the_files():
    bal = {r["ledger_name"]: D(r["opening_dr"]) - D(r["opening_cr"]) for r in rows("ledgers.csv")}
    rev = {r["ref_id"] for r in rows("reversals.csv")}
    assert rev == {"V38"}
    for ref, lines in vouchers().items():
        for ln in lines:
            net = D(ln["debit"]) - D(ln["credit"])
            bal[ln["ledger_name"]] += net
            if ref in rev:
                bal[ln["ledger_name"]] -= net  # the mirror voucher cancels it
    for r in rows("expected_trial_balance.csv"):
        if r["group_name"] != "TOTAL":
            assert bal[r["ledger_name"]] == D(r["dr"]) - D(r["cr"]), r["ledger_name"]


def test_outstanding_ageing_tie():
    def load(name):
        return rows(name)

    for name, grand, side in (("expected_outstanding_receivable.csv", D("446400.00"), "Dr"),
                              ("expected_outstanding_payable.csv", D("342800.00"), "Cr")):
        rs = load(name)
        per_party: dict[str, D] = defaultdict(D)
        buckets: dict[str, D] = defaultdict(D)
        for r in rs:
            if r["row_type"] in ("bill", "on_account"):
                signed = D(r["outstanding"]) * (1 if r["side"] == side else -1)
                per_party[r["party"]] += signed
                buckets[r["bucket"]] += signed
        for r in rs:
            if r["row_type"] == "party_total":
                assert per_party[r["party"]] == D(r["outstanding"]), r["party"]
        assert sum(per_party.values()) == grand
        assert sum(D(r["outstanding"]) for r in rs if r["row_type"] == "grand_total") == grand
        ageing = {(r["kind"], r["party"]): r for r in rows("expected_ageing.csv")}
        kind = "receivable" if side == "Dr" else "payable"
        for p, tot in per_party.items():
            row = ageing[(kind, p)]
            assert sum(D(row[b]) for b in ("not_due", "0-30", "31-60", "61-90", "90+")) == D(row["total"]) == tot
        total_row = ageing[(kind, "")]
        for b in ("not_due", "0-30", "31-60", "61-90", "90+"):
            assert D(total_row[b]) == buckets[b], b
        assert D(total_row["total"]) == grand


def test_ageing_bucket_totals_literal():
    t = {(r["kind"], r["row_type"]): r for r in rows("expected_ageing.csv") if r["row_type"] == "total"}
    rec, pay = t[("receivable", "total")], t[("payable", "total")]
    assert [rec[b] for b in ("not_due", "0-30", "31-60", "61-90", "90+")] == ["147000.00", "103400.00", "109500.00", "11500.00", "75000.00"]
    assert [pay[b] for b in ("not_due", "0-30", "31-60", "61-90", "90+")] == ["129800.00", "32600.00", "35400.00", "105000.00", "40000.00"]


def test_cash_book_arithmetic_and_never_negative():
    cb = rows("expected_cash_book.csv")
    opening = next(r for r in cb if r["row_type"] == "opening")
    run = D(opening["closing_dr"])
    assert run == D("40000.00")
    receipts = payments = D(0)
    for r in cb:
        if r["row_type"] == "day":
            run += D(r["receipts"]) - D(r["payments"])
            assert run == D(r["closing_dr"]), r["date"]
            assert run > 0
            receipts += D(r["receipts"])
            payments += D(r["payments"])
    total = next(r for r in cb if r["row_type"] == "total")
    assert (receipts, payments, run) == (D("108100.00"), D("112500.00"), D("35600.00"))
    assert (D(total["receipts"]), D(total["payments"]), D(total["closing_dr"])) == (receipts, payments, run)
    # the Cash ledger of vouchers.csv gives the same day totals
    days: dict[str, list[D]] = defaultdict(lambda: [D(0), D(0)])
    for lines in vouchers().values():
        for ln in lines:
            if ln["ledger_name"] == "Cash":
                days[ln["date"]][0] += D(ln["debit"])
                days[ln["date"]][1] += D(ln["credit"])
    assert {d: (v[0], v[1]) for d, v in days.items()} == {
        r["date"]: (D(r["receipts"]), D(r["payments"])) for r in cb if r["row_type"] == "day"}


def test_bank_format_and_statement_running_balance():
    fmt = json.loads((PACK / "bank_format.json").read_text(encoding="utf-8"))
    m = fmt["mapping"]
    with open(PACK / "bank_statement.csv", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == [m["date_col"], m["description_col"], m["reference_col"], m["debit_col"], m["credit_col"], m["balance_col"]]
        lines = list(reader)
    assert len(lines) == 21
    run = D(m["opening_balance"])
    assert run == D("500000.00")
    for i, r in enumerate(lines, start=1):
        assert not (r[m["debit_col"]] and r[m["credit_col"]]), i
        run += D(r[m["credit_col"]] or "0") - D(r[m["debit_col"]] or "0")
        assert run == D(r[m["balance_col"]]), f"statement row {i}"
    assert run == D("465549.00")
    brs = {r["line_type"]: r for r in rows("expected_brs.csv")}
    assert D(brs["balance_per_bank"]["amount"]) == run


def test_opening_item_explains_opening_difference():
    items = rows("bank_opening_items.csv")
    assert [(i["kind"], i["reference"], i["amount"]) for i in items] == [("issued_not_presented", "000451", "12500.00")]
    books_open = next(D(r["opening_dr"]) for r in rows("ledgers.csv") if r["ledger_name"] == "HDFC Bank")
    # issued, not presented at 31-03: the statement is HIGHER than the books by that cheque
    assert D("500000.00") - books_open == D("12500.00")


def test_brs_arithmetic_ties():
    brs = rows("expected_brs.csv")
    sums: dict[str, D] = defaultdict(D)
    for r in brs:
        sums[r["line_type"]] += D(r["amount"])
    assert sums["issued_not_presented"] == sums["total_issued_not_presented"] == D("66500.00")
    assert sums["deposited_not_cleared"] == sums["total_deposited_not_cleared"] == D("50000.00")
    assert sums["bank_only_credit"] == sums["total_bank_only_credits"] == D("1875.00")
    assert sums["bank_only_debit"] == sums["total_bank_only_debits"] == D("826.00")
    computed = (sums["balance_per_books"] + sums["issued_not_presented"] - sums["deposited_not_cleared"]
                + sums["bank_only_credit"] - sums["bank_only_debit"])
    assert computed == sums["computed_bank_balance"] == sums["balance_per_bank"] == D("465549.00")
    assert sums["difference"] == D("0.00")


def test_books_bank_balance_matches_brs_and_reconciling_items_come_from_vouchers():
    bank = D(next(r["opening_dr"] for r in rows("ledgers.csv") if r["ledger_name"] == "HDFC Bank"))
    by_ref = {}
    for ref, lines in vouchers().items():
        for ln in lines:
            if ln["ledger_name"] == "HDFC Bank":
                bank += D(ln["debit"]) - D(ln["credit"])
                by_ref[ref] = (ln["date"], ln["reference_no"], D(ln["debit"]) - D(ln["credit"]))
    assert bank == D("448000.00")
    matches = {m["bank_line_no"]: m for m in rows("expected_matches.csv")}
    assert len(matches) == 21
    matched = set()
    for m in matches.values():
        matched |= {x for x in m["book_refs"].split("+") if x.startswith("V")}
    unmatched = {ref for ref in by_ref if ref not in matched}
    assert unmatched == {"V45", "V46", "V47", "V48"}
    assert sum(-by_ref[r][2] for r in ("V45", "V46")) == D("66500.00")
    assert sum(by_ref[r][2] for r in ("V47", "V48")) == D("50000.00")
    # each matched statement line equals its book items
    with open(PACK / "bank_statement.csv", encoding="utf-8", newline="") as f:
        lines = list(csv.DictReader(f))
    for no, line in enumerate(lines, start=1):
        m = matches[str(no)]
        stmt = D(line["Deposit Amt"] or "0") - D(line["Withdrawal Amt"] or "0")
        refs = [x for x in m["book_refs"].split("+") if x.startswith("V")]
        if m["book_refs"] == "":
            continue
        if m["book_refs"].startswith("OPENING"):
            assert stmt == D("-12500.00")
        else:
            assert stmt == sum(by_ref[r][2] for r in refs), no
    bank_only = [no for no, m in matches.items() if m["book_refs"] == ""]
    assert sorted(bank_only, key=int) == ["8", "18", "21"]


def test_bank_only_drafts_equal_bank_only_lines():
    with open(PACK / "bank_statement.csv", encoding="utf-8", newline="") as f:
        lines = list(csv.DictReader(f))
    for d in rows("expected_bank_only_drafts.csv"):
        line = lines[int(d["bank_line_no"]) - 1]
        amount = D(line["Deposit Amt"] or line["Withdrawal Amt"])
        assert amount == D(d["amount"])
        assert (d["voucher_type"] == "receipt") == bool(line["Deposit Amt"])


def test_msme_expected_total_and_party_master_formats():
    items = [r for r in rows("expected_msme_due.csv") if r["row_type"] == "item"]
    assert sum(D(r["outstanding"]) for r in items) == D("59000.00")
    assert [(r["party"], r["legal_due_date"], r["days_overdue"]) for r in items] == [
        ("Patel Packaging Works", "2026-04-30", "61"), ("Gupta Wholesale", "2026-06-04", "26")]
    ps = {r["ledger_name"]: r for r in rows("parties.csv")}
    assert len(ps) == 8
    assert {r["credit_days"] for r in ps.values()} == {"30", "45", "60"}
    assert [ps[n]["msme_category"] for n in ("Gupta Wholesale", "Patel Packaging Works", "Sharma Suppliers")] == ["micro", "small", "medium"]
    assert (ps["Gupta Wholesale"]["msme_written_agreement"], ps["Gupta Wholesale"]["credit_days"]) == ("true", "30")
    assert ps["Patel Packaging Works"]["msme_written_agreement"] == "false"
    r = ps["Rahul Enterprises"]
    assert r["gstin"][2:12] == r["pan"] and r["gstin"][:2] == r["state_code"] == "27" and len(r["gstin"]) == 15


def test_wrong_files_have_expected_rule_ids():
    assert {(r["ref_id"], r["expected_rule_id"]) for r in rows("wrong_vouchers.csv")} == {
        ("X01", "B-01"), ("X02", "B-02"), ("X03", "B-03"), ("X04", "B-04"), ("X05", "C-01"), ("X06", "D-01")}
    assert {(r["ref_id"], r["expected_rule_id"]) for r in rows("wrong_parties.csv")} == {
        ("WP1", "P-01"), ("WP2", "P-03"), ("WP3", "P-05")}
    wrong = defaultdict(list)
    for r in rows("wrong_vouchers.csv"):
        wrong[r["ref_id"]].append(r)
    for ref, lines in wrong.items():
        assert sum(D(ln["debit"]) for ln in lines) == sum(D(ln["credit"]) for ln in lines), ref
    assert {a["ref_id"] for a in rows("wrong_allocations.csv")} <= set(wrong)
    wp2 = next(r for r in rows("wrong_parties.csv") if r["ref_id"] == "WP2")
    assert wp2["gstin"][2:12] != wp2["pan"] and len(wp2["gstin"]) == 15
    wp1 = next(r for r in rows("wrong_parties.csv") if r["ref_id"] == "WP1")
    assert len(wp1["gstin"]) == 14
    wp3 = next(r for r in rows("wrong_parties.csv") if r["ref_id"] == "WP3")
    assert wp3["msme_category"] == "small" and wp3["udyam_no"] == ""
