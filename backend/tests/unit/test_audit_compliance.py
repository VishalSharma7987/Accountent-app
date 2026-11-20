"""Phase 8 package C: compliance checks A-07..A-11, A-16, A-17 (thin adapters over the Phase 2 to 5 engines). No database.
Expected values are hand-calculated and typed literally; rule rows below are test fixtures, not law."""

import ast
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from app.engine import audit_checks_compliance as c
from app.engine.audit_types import AuditParams
from app.engine.cash_rules import CashMovement
from app.engine.gst_tieout import Cause
from app.engine.inventory_types import (
    InventoryPolicy,
    Movement,
    MovementKind,
    NegativeStockMode,
    OpeningStock,
    ValuationMethod,
)
from app.engine.models import OpenBill, OpeningBalance
from app.engine.msme import MsmeRule, PartyFacts
from app.engine.tds_calc import TdsContext
from app.engine.tds_types import Deductee, DueDateRule, Nature, RateRule, SectionRef

PARAMS = AuditParams(date(2026, 4, 1), date(2027, 3, 31))


def d(y, m, dd):
    return date(y, m, dd)


# ---------------------------------------------------------------------------------------------------------------- A-07


MSME_RULE = MsmeRule("msme_43bh", "micro", True, 45, 15, d(2020, 1, 1), None, "test source", "pending", ("manufacturing", "services"))


def bill(ref, bill_date, outstanding, party="p1", name="Gupta Fabricators"):
    return OpenBill(party, name, ref, "bill", bill_date, None, D(outstanding), D(outstanding))


def msme_facts(bills, parties=None, as_on=date(2026, 9, 1)):
    parties = parties or {"p1": PartyFacts("p1", "micro", False, None, "manufacturing", d(2020, 1, 1))}
    return c.ComplianceFacts(msme=c.MsmeFacts(tuple(bills), parties, (MSME_RULE,), as_on))


def test_A07_micro_bill_past_15_days_is_flagged_with_evidence():
    # bill 01-08-2026, no agreement: 15 days -> due 16-08-2026; as on 01-09-2026 it is 16 days overdue
    r = c.check_msme(msme_facts([bill("INV-9", d(2026, 8, 1), "-120000.00")]), PARAMS)
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.check_id == "A-07" and f.severity.value == "error" and f.rule_status == "pending"
    assert f.amount == D("120000.00") and f.finding_date == d(2026, 8, 16)
    assert "1,20,000.00" in f.message and "16 days overdue" in f.message and "16-08-2026" in f.message and "rule pending verification" in f.message
    assert f.evidence["days_overdue"] == "16" and f.evidence["legal_days"] == "15" and f.evidence["bill_ref"] == "INV-9"
    assert f.evidence["rule"]["status"] == "pending" and f.subject_id == "p1" and f.subject_kind == "bill"
    assert r.population == ("p1:INV-9",) and r.population_amount == D("120000.00")


def test_A07_bill_inside_the_legal_days_and_other_parties_are_not_flagged():
    parties = {"p1": PartyFacts("p1", "micro", False, None, "manufacturing", d(2020, 1, 1)),
               "p2": PartyFacts("p2", "medium", False, None, "manufacturing", d(2020, 1, 1))}
    bills = [bill("INV-10", d(2026, 8, 25), "-50000.00"),               # due 09-09-2026: not yet
             bill("M-1", d(2026, 7, 1), "-70000.00", party="p2")]       # medium supplier: out of scope
    r = c.check_msme(msme_facts(bills, parties), PARAMS)
    assert r.findings == () and r.population == ("p1:INV-10",)


def test_A07_not_loaded_gives_a_note_not_a_guess():
    r = c.check_msme(c.ComplianceFacts(), PARAMS)
    assert r.findings == () and "not run" in r.notes[0]


# ---------------------------------------------------------------------------------------------------------------- A-08


def row(head, books, g1, g3, f1=None, f3=None):
    dd = lambda a, b: None if a is None or b is None else a - b
    return {"head": head, "books_output": D(books), "gstr1_working": D(g1), "gstr3b_working": D(g3),
            "filed_gstr1": None if f1 is None else D(f1), "filed_gstr3b": None if f3 is None else D(f3),
            "d_books_gstr1": D(books) - D(g1), "d_gstr1_gstr3b": D(g1) - D(g3),
            "d_books_filed": dd(D(books), None if f1 is None else D(f1)), "d_filed_gstr1_gstr3b": None}


ZERO_ITC = {"books_input": D(0), "itc_register_eligible": D(0), "gstr3b_4a": D(0), "itc_register_pending": D(0),
            "d_register_gstr3b": D(0), "d_books_register_pending": D(0)}


def test_A08_a_period_with_a_difference_becomes_one_finding_with_causes():
    bad = c.GstPeriodFact("r1", "27AAAAA0000A1Z5", d(2026, 4, 1), d(2026, 4, 30),
                          (row("igst", "18000.00", "18000.00", "17000.00"),), {"igst": ZERO_ITC}, (Cause("draft_voucher", "D-1", D("1000.00")),), False)
    good = c.GstPeriodFact("r1", "27AAAAA0000A1Z5", d(2026, 5, 1), d(2026, 5, 31),
                           (row("igst", "5000.00", "5000.00", "5000.00"),), {"igst": ZERO_ITC}, (), True)
    r = c.check_gst(c.ComplianceFacts(gst=(bad, good)), PARAMS)
    assert len(r.findings) == 1 and len(r.population) == 2
    f = r.findings[0]
    assert f.check_id == "A-08" and f.amount == D("1000.00") and f.finding_date == d(2026, 4, 30)
    assert "IGST: GSTR-1 working 18,000.00 against GSTR-3B working 17,000.00 (difference 1,000.00)" in f.message
    assert f.evidence["differences"] == [{"head": "IGST", "left": "GSTR-1 working", "left_amount": "18000.00", "right": "GSTR-3B working",
                                          "right_amount": "17000.00", "difference": "1000.00"}]
    assert f.evidence["causes"] == [{"kind": "draft_voucher", "reference": "D-1", "amount": "1000.00", "head": None}]


def test_A08_itc_register_difference_is_reported():
    itc = {"igst": {**ZERO_ITC, "itc_register_eligible": D("900.00"), "gstr3b_4a": D("800.00"), "d_register_gstr3b": D("100.00")}}
    p = c.GstPeriodFact("r1", "G", d(2026, 4, 1), d(2026, 4, 30), (row("igst", "0.00", "0.00", "0.00"),), itc, (), False)
    f = c.check_gst(c.ComplianceFacts(gst=(p,)), PARAMS).findings[0]
    assert f.evidence["differences"][0]["head"] == "ITC IGST" and f.evidence["differences"][0]["difference"] == "100.00"


# ---------------------------------------------------------------------------------------------------------------- A-09 / A-10


NATURE = Nature("contractor", "tds", "Contractor", "flat", "pending")
SECTION = SectionRef("contractor", "it_act_2025", "S-TEST", None, None, d(2026, 4, 1), None, "test", "pending")


def rate_rule(**over):
    base = {"id": "r1", "nature_key": "contractor", "act": "it_act_2025", "deductee_group": "any", "rate": D(2), "no_pan_rate": D(20),
                "single_payment_threshold": None, "monthly_threshold": None, "annual_threshold": None, "threshold_mode": "whole_amount",
                "effective_from": d(2026, 4, 1), "effective_to": None, "source_reference": "test", "verification_status": "pending"}
    base.update(over)
    return RateRule(**base)


def tds_ctx(rule):
    return TdsContext("tds", {"contractor": NATURE}, {"D1": Deductee("D1", "ABCDE1234F", "valid", "company", "contractor")}, [rule], [SECTION], {}, {},
                      lambda on: "FY27" if d(2026, 4, 1) <= on <= d(2027, 3, 31) else None)


def cand(vid, on, base, deducted, ref=None):
    return c.TdsCandidate(vid, ref or vid, "payment", on, "D1", "Sharma Contractors", "contractor", D(base), "party_line", None, on, D(deducted))


def tds_facts(cands, rule=None):
    return c.ComplianceFacts(tds=c.TdsFacts(tuple(cands), tds_ctx(rule or rate_rule())))


def test_A09_no_deduction_where_tax_is_computed_is_flagged():
    # 1,00,000.00 at 2% = 2,000.00, nothing deducted
    r = c.check_tds_not_deducted(tds_facts([cand("v1", d(2026, 8, 10), "100000.00", "0.00", "PAY/1")]), PARAMS)
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.check_id == "A-09" and f.amount == D("2000.00") and f.rule_status == "pending" and f.subject_id == "v1"
    assert "TDS not deducted" in f.message and "2,000.00" in f.message and "1,00,000.00" in f.message and "S-TEST" in f.message
    assert f.evidence["computed_tax"] == "2000.00" and f.evidence["deducted_tax"] == "0.00" and f.evidence["voucher_number"] == "PAY/1"
    assert c.check_tds_short_deducted(tds_facts([cand("v1", d(2026, 8, 10), "100000.00", "0.00")]), PARAMS).findings == ()


def test_A10_short_deduction_is_flagged_and_exact_or_excess_is_not():
    # 50,000.00 at 2% = 1,000.00: deducted 500.00 -> short by 500.00; deducted 1,000.00 and 1,200.00 -> fine
    facts = tds_facts([cand("v2", d(2026, 8, 10), "50000.00", "500.00"), cand("v3", d(2026, 8, 11), "50000.00", "1000.00"),
                       cand("v4", d(2026, 8, 12), "50000.00", "1200.00")])
    r = c.check_tds_short_deducted(facts, PARAMS)
    assert [f.subject_id for f in r.findings] == ["v2"]
    f = r.findings[0]
    assert f.check_id == "A-10" and f.amount == D("500.00") and "short by 500.00" in f.message
    assert f.evidence["shortfall"] == "500.00" and f.evidence["computed_tax"] == "1000.00"
    assert c.check_tds_not_deducted(facts, PARAMS).findings == ()
    assert len(r.population) == 3 and r.population_amount == D("150000.00")


def test_A09_the_year_is_worked_in_date_order_with_the_threshold_running():
    # annual threshold 1,00,000.00 on the excess only: 60,000.00 (nil) then 60,000.00 -> base 20,000.00 at 2% = 400.00
    rule = rate_rule(annual_threshold=D("100000.00"), threshold_mode="excess_only")
    facts = tds_facts([cand("late", d(2026, 8, 6), "60000.00", "0.00"), cand("early", d(2026, 8, 5), "60000.00", "0.00")], rule)
    r = c.check_tds_not_deducted(facts, PARAMS)
    assert [(f.subject_id, f.amount) for f in r.findings] == [("late", D("400.00"))]


def test_A09_only_events_inside_the_run_window_are_reported():
    facts = tds_facts([cand("v1", d(2026, 8, 10), "100000.00", "0.00")])
    narrow = AuditParams(d(2026, 9, 1), d(2026, 9, 30))
    r = c.check_tds_not_deducted(facts, narrow)
    assert r.findings == () and r.population == ()


def test_A09_an_item_the_engine_cannot_work_is_noted_not_guessed():
    # no rate row for 2026-03-10 (the rule starts 01-04-2026): the voucher is listed in the notes, nothing is invented
    facts = c.ComplianceFacts(tds=c.TdsFacts((cand("old", d(2026, 3, 10), "100000.00", "0.00", "PAY/0"),), tds_ctx(rate_rule())))
    r = c.check_tds_not_deducted(facts, AuditParams(d(2026, 3, 1), d(2026, 3, 31)))
    assert r.findings == () and r.notes[0].startswith("PAY/0 (Sharma Contractors): not tested") and "10-03-2026" in r.notes[0]


# ---------------------------------------------------------------------------------------------------------------- A-11


DUE = DueDateRule("tds_challan_regular", "challan", "tds", None, None, 7, 1, None, d(2026, 4, 1), None, "secondary_verified")


def dep_item(iid, on, deposits, amount="2000.00"):
    return c.DepositItem(iid, "v-" + iid, "PAY/" + iid, "Sharma Contractors", "S-TEST", "tds", on, D(amount), tuple(deposits))


def test_A11_late_and_undeposited_items_are_flagged_on_time_and_not_yet_due_are_not():
    items = (
        dep_item("1", d(2026, 8, 10), [(d(2026, 9, 10), D("2000.00"))]),   # due 07-09-2026, deposited 10-09 -> 3 days late
        dep_item("2", d(2026, 8, 12), [(d(2026, 9, 7), D("2000.00"))]),    # on the due date: on time
        dep_item("3", d(2026, 8, 15), []),                                 # due 07-09, nothing deposited, as on 01-10-2026 -> 24 days late
        dep_item("4", d(2026, 9, 20), []),                                 # due 07-10-2026: not yet due
    )
    r = c.check_tds_late_deposit(c.ComplianceFacts(deposits=c.DepositFacts(items, (DUE,), d(2026, 10, 1))), PARAMS)
    assert [f.finding_key for f in r.findings] == ["A-11:1", "A-11:3"]
    late, never = r.findings
    assert "deposited on 10-09-2026, 3 days late" in late.message and "due on 07-09-2026" in late.message
    assert late.evidence["days_late"] == "3" and late.evidence["deposited_on"] == "2026-09-10" and late.rule_status == "secondary_verified"
    assert "still undeposited as on 01-10-2026" in never.message and "24 days late" in never.message
    assert never.evidence["undeposited"] == "2000.00" and never.evidence["deposits"] == []
    assert len(r.population) == 4 and r.population_amount == D("8000.00")


def test_A11_no_due_date_rule_for_the_date_is_noted_and_skipped():
    items = (dep_item("9", d(2026, 2, 10), []),)    # the only rule starts 01-04-2026
    r = c.check_tds_late_deposit(c.ComplianceFacts(deposits=c.DepositFacts(items, (DUE,), d(2026, 10, 1))), AuditParams(d(2026, 1, 1), d(2026, 3, 31)))
    assert r.findings == () and r.population == () and "due date not worked" in r.notes[0]


# ---------------------------------------------------------------------------------------------------------------- A-16


def mv(day, debit="0", credit="0"):
    return CashMovement(d(2026, 8, day), D(debit), D(credit))


def test_A16_cash_below_zero_at_day_end_is_flagged_with_first_and_lowest_day():
    # opening Dr 5,000: 10th Cr 3,000 -> 2,000; 12th Cr 4,000 -> -2,000; 13th Dr 1,000 -> -1,000; 14th Dr 2,000 -> 1,000
    led = c.CashLedgerFact("L1", "Cash", OpeningBalance(D("5000.00"), D("0.00")),
                           (mv(10, credit="3000.00"), mv(12, credit="4000.00"), mv(13, debit="1000.00"), mv(14, debit="2000.00")),
                           {d(2026, 8, 12): ("v-12",)})
    ok = c.CashLedgerFact("L2", "Petty cash", OpeningBalance(D("100.00"), D("0.00")), (mv(10, credit="100.00"),))
    r = c.check_negative_cash(c.ComplianceFacts(cash=(led, ok)), PARAMS)
    assert len(r.findings) == 1 and r.population == ("L1", "L2")
    f = r.findings[0]
    assert f.check_id == "A-16" and f.subject_id == "L1" and f.finding_date == d(2026, 8, 12) and f.amount == D("2000.00")
    assert "2 day(s)" in f.message and "12-08-2026" in f.message and "Cr 2,000.00" in f.message
    assert f.evidence["first_balance"] == "-2000.00" and f.evidence["negative_day_count"] == "2"
    assert f.evidence["days"] == [{"date": "2026-08-12", "balance": "-2000.00", "voucher_ids": ["v-12"]},
                                  {"date": "2026-08-13", "balance": "-1000.00", "voucher_ids": []}]
    assert f.evidence["rule"].startswith("C-01") and "negative" in f.evidence["engine_message"].lower()


def test_A16_receipt_and_payment_of_the_same_day_net_off():
    # opening 0: 15th Dr 500 and Cr 500 the same day -> day-end 0, not negative
    led = c.CashLedgerFact("L1", "Cash", OpeningBalance(D("0.00"), D("0.00")), (mv(15, credit="500.00"), mv(15, debit="500.00")))
    assert c.check_negative_cash(c.ComplianceFacts(cash=(led,)), PARAMS).findings == ()


def test_A16_negative_days_outside_the_run_window_are_not_reported():
    led = c.CashLedgerFact("L1", "Cash", OpeningBalance(D("0.00"), D("0.00")), (mv(12, credit="100.00"),))
    assert c.check_negative_cash(c.ComplianceFacts(cash=(led,)), AuditParams(d(2026, 9, 1), d(2026, 9, 30))).findings == ()


# ---------------------------------------------------------------------------------------------------------------- A-17


def stock_facts(mode):
    opening = (OpeningStock("i1", "g1", D("10.000"), D("1000.00")),)
    moves = (
        Movement("m1", 1, d(2026, 8, 1), "i1", "g1", MovementKind.PURCHASE, D("5.000"), D("500.00")),
        Movement("m2", 2, d(2026, 8, 10), "i1", "g1", MovementKind.SALE, D("20.000")),   # 10 + 5 - 20 = -5
    )
    return c.StockFacts(InventoryPolicy(ValuationMethod.FIFO, mode), opening, moves, {"m2": "SAL/2026-27/0007"}, {"i1": "Steel rod"}, {"g1": "Main"},
                        d(2026, 4, 1), d(2027, 3, 31))


def test_A17_stock_that_goes_below_zero_is_flagged_with_the_movement_and_voucher():
    for mode in (NegativeStockMode.BLOCK, NegativeStockMode.WARN):
        r = c.check_negative_stock(c.ComplianceFacts(stock=stock_facts(mode)), PARAMS)
        assert len(r.findings) == 1, mode
        f = r.findings[0]
        assert f.check_id == "A-17" and f.subject_id == "i1" and f.finding_date == d(2026, 8, 10) and f.severity.value == "error"
        assert f.subject_ref == "Steel rod / Main" and "Steel rod" in f.message and "SAL/2026-27/0007" in f.message
        assert f.evidence["movement_id"] == "m2" and f.evidence["movement_quantity"] == "20.000" and f.evidence["movement_kind"] == "sale"
        assert f.evidence["negative_stock_mode"] == mode.value
    assert r.population == ("i1",)


def test_A17_stock_that_never_goes_negative_has_no_finding():
    s = stock_facts(NegativeStockMode.BLOCK)
    ok = c.StockFacts(s.policy, s.opening, (s.movements[0],), {}, s.item_names, s.godown_names, s.fy_start, s.fy_end)
    assert c.check_negative_stock(c.ComplianceFacts(stock=ok), PARAMS).findings == ()


# ---------------------------------------------------------------------------------------------------------------- shape


def test_the_registry_holds_exactly_the_seven_compliance_checks_and_every_finding_has_evidence():
    assert sorted(c.CHECKS) == ["A-07", "A-08", "A-09", "A-10", "A-11", "A-16", "A-17"]
    r = c.check_negative_stock(c.ComplianceFacts(stock=stock_facts(NegativeStockMode.BLOCK)), PARAMS)
    assert all(f.evidence and f.message for f in r.findings)


def test_the_package_C_engine_file_is_pure():
    tree = ast.parse(Path(c.__file__).read_text(encoding="utf-8"))
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [a.name for n in ast.walk(tree)
                                                                                           if isinstance(n, ast.Import) for a in n.names]
    forbidden = ("fastapi", "sqlalchemy", "app.db", "app.services", "app.api", "app.ai", "httpx", "openai")
    assert [m for m in modules if m.startswith(forbidden)] == []


def test_the_registry_wrapper_reads_facts_extra_compliance():
    from app.engine.audit_registry import AuditFacts

    r = c.CHECKS["A-07"](AuditFacts({}, (), {"compliance": msme_facts([bill("INV-9", d(2026, 8, 1), "-120000.00")])}), PARAMS, [])
    assert len(r.findings) == 1
