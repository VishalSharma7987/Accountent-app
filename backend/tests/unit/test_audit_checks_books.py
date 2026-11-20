"""Phase 8 package B: books checks A-01..A-06, A-12, A-13, A-14 as pure functions over literal facts. Expected values hand-calculated."""

from datetime import UTC, date, datetime
from decimal import Decimal as D

from app.engine import audit_checks_books as b
from app.engine.audit_types import AuditParams, LedgerFact, LimitRule, LineFact, VoucherFact

CASH, BANK, EXP, SHARMA, MEHTA, KUMAR = "cash", "bank", "exp", "sharma", "mehta", "kumar"
LEDGERS = (
    LedgerFact(CASH, "Cash", "cash_in_hand"), LedgerFact(BANK, "HDFC Bank", "bank_accounts"),
    LedgerFact(EXP, "Repairs", "indirect_expenses"), LedgerFact(SHARMA, "Sharma Traders", "sundry_creditors"),
    LedgerFact(MEHTA, "Mehta & Co", "sundry_debtors"), LedgerFact(KUMAR, "Kumar Steel", "sundry_creditors"),
)
PARAMS = AuditParams(from_date=date(2026, 4, 1), to_date=date(2027, 3, 31))


def pay(vid, on, amount, *, via=CASH, party=SHARMA, status="posted", number=None, **kw):
    a = D(amount)
    return VoucherFact(vid, "payment", number or f"PAY/2026-27/{vid}", on, status, "paid", None, party,
                       (LineFact(party, a, D("0.00")), LineFact(via, D("0.00"), a)), **kw)


def rec(vid, on, amount, *, party=MEHTA, via=CASH):
    a = D(amount)
    return VoucherFact(vid, "receipt", f"REC/2026-27/{vid}", on, "posted", "received", None, party,
                       (LineFact(via, a, D("0.00")), LineFact(party, D("0.00"), a)))


def pur(vid, on, amount, ref, *, party=KUMAR, status="posted", number=None, **kw):
    a = D(amount)
    return VoucherFact(vid, "purchase", number or f"PUR/2026-27/{vid}", on, status, "bought", ref, party,
                       (LineFact(EXP, a, D("0.00")), LineFact(party, D("0.00"), a)), **kw)


def facts(vouchers, **kw):
    return b.BooksFacts(vouchers=tuple(vouchers), ledgers=LEDGERS, **kw)


def rule(key, amount, when, pct, status="pending", frm=date(2026, 4, 1), to=None, law="it_act_2025"):
    return LimitRule(key, law, "s.x", D(amount), when, None if pct is None else D(pct), frm, to, status)


PAY_LIMIT = rule("cash_payment_daily_limit", "10000.00", "above", "100")
REC_LIMIT = rule("cash_receipt_limit", "200000.00", "at_or_above", None)


# ---- A-01 -------------------------------------------------------------------------------------------------------
def test_A01_same_party_same_normalised_reference_is_one_finding_with_both_ids():
    r = b.CHECKS["A-01"](facts([pur("p1", date(2026, 5, 1), "5000.00", "INV-17"), pur("p2", date(2026, 5, 9), "5000.00", "inv 17 ")]),
                         PARAMS, ())
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.check_id == "A-01" and f.finding_key == "A-01:kumar:inv17"
    assert f.evidence["voucher_ids"] == ["p1", "p2"] and f.evidence["amounts"] == ["5000.00", "5000.00"]
    assert r.population == ("p1", "p2")


def test_A01_reversed_original_is_ignored_and_other_party_is_not_a_duplicate():
    reversed_first = pur("p1", date(2026, 5, 1), "5000.00", "INV-17", status="reversed")
    assert b.CHECKS["A-01"](facts([reversed_first, pur("p2", date(2026, 5, 9), "5000.00", "INV-17")]), PARAMS, ()).findings == ()
    other = pur("p3", date(2026, 5, 9), "5000.00", "INV-17", party=SHARMA)
    assert b.CHECKS["A-01"](facts([pur("p1", date(2026, 5, 1), "5000.00", "INV-17"), other]), PARAMS, ()).findings == ()


# ---- A-02 -------------------------------------------------------------------------------------------------------
def test_A02_same_party_same_total_within_window_is_flagged_and_eight_days_is_not():
    two = [pay("a", date(2026, 6, 1), "7500.00", via=BANK), pay("b", date(2026, 6, 8), "7500.00", via=BANK)]  # exactly 7 days
    r = b.CHECKS["A-02"](facts(two), PARAMS, ())
    assert len(r.findings) == 1 and r.findings[0].evidence["voucher_ids"] == ["a", "b"]
    assert r.findings[0].evidence["dates"] == ["2026-06-01", "2026-06-08"]
    far = [pay("a", date(2026, 6, 1), "7500.00"), pay("b", date(2026, 6, 9), "7500.00")]  # 8 days
    assert b.CHECKS["A-02"](facts(far), PARAMS, ()).findings == ()
    diff = [pay("a", date(2026, 6, 1), "7500.00"), pay("b", date(2026, 6, 2), "7500.01")]
    assert b.CHECKS["A-02"](facts(diff), PARAMS, ()).findings == ()


# ---- A-03 -------------------------------------------------------------------------------------------------------
def test_A03_purchase_without_document_is_flagged_and_linked_one_is_not():
    vs = [pur("p1", date(2026, 5, 1), "5000.00", "A1"), pur("p2", date(2026, 5, 2), "6000.00", "A2"),
          VoucherFact("j1", "journal", "JRN/1", date(2026, 5, 3), "posted", "adj", None, None,
                      (LineFact(EXP, D("10.00"), D("0.00")), LineFact(KUMAR, D("0.00"), D("10.00"))))]
    r = b.CHECKS["A-03"](facts(vs, document_voucher_ids=frozenset({"p2"})), PARAMS, ())
    assert [f.subject_id for f in r.findings] == ["p1"]
    assert r.findings[0].amount == D("5000.00") and r.population == ("p1", "p2")


def test_A03_minimum_amount_parameter_skips_small_vouchers():
    p = AuditParams(from_date=date(2026, 4, 1), to_date=date(2027, 3, 31), doc_min_amount=D("5500.00"))
    vs = [pur("p1", date(2026, 5, 1), "5000.00", "A1"), pur("p2", date(2026, 5, 2), "6000.00", "A2")]
    assert [f.subject_id for f in b.CHECKS["A-03"](facts(vs), p, ()).findings] == ["p2"]


# ---- A-04 -------------------------------------------------------------------------------------------------------
def test_A04_missing_number_0003_when_counter_says_4():
    vs = [pur("p1", date(2026, 5, 1), "1.00", "a", number="PUR/2026-27/0001"), pur("p2", date(2026, 5, 2), "1.00", "b", number="PUR/2026-27/0002"),
          pur("p4", date(2026, 5, 3), "1.00", "c", number="PUR/2026-27/0004")]
    r = b.CHECKS["A-04"](facts(vs, number_counters={"purchase": 4}), PARAMS, ())
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.finding_key == "A-04:purchase:gap" and f.evidence["missing_numbers"] == ["PUR/2026-27/0003"]
    assert f.evidence["counter"] == "4" and "0003" in f.message


def test_A04_counter_different_from_highest_posted_number_is_a_finding():
    vs = [pur("p1", date(2026, 5, 1), "1.00", "a", number="PUR/2026-27/0001"), pur("p2", date(2026, 5, 2), "1.00", "b", number="PUR/2026-27/0002")]
    r = b.CHECKS["A-04"](facts(vs, number_counters={"purchase": 3}), PARAMS, ())
    assert [f.finding_key for f in r.findings] == ["A-04:purchase:counter"]
    assert r.findings[0].evidence["highest_posted"] == "2"


def test_A04_clean_sequence_has_no_finding_and_reversed_numbers_count_as_used():
    vs = [pur("p1", date(2026, 5, 1), "1.00", "a", number="PUR/2026-27/0001", status="reversed"),
          pur("p2", date(2026, 5, 2), "1.00", "b", number="PUR/2026-27/0002")]
    assert b.CHECKS["A-04"](facts(vs, number_counters={"purchase": 2}), PARAMS, ()).findings == ()


# ---- A-05 -------------------------------------------------------------------------------------------------------
def test_A05_two_cash_payments_to_one_party_above_limit_one_finding_with_disallowance():
    vs = [pay("c1", date(2026, 8, 14), "6000.00"), pay("c2", date(2026, 8, 14), "5000.00"),
          pay("b1", date(2026, 8, 14), "20000.00", via=BANK), pay("c3", date(2026, 8, 15), "10000.00")]
    r = b.CHECKS["A-05"](facts(vs), PARAMS, (PAY_LIMIT,))
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.finding_key == "A-05:sharma:2026-08-14" and f.amount == D("11000.00") and f.disallowance_amount == D("11000.00")
    assert f.rule_status == "pending" and f.evidence["voucher_ids"] == ["c1", "c2"]
    assert f.evidence["rule"]["status"] == "pending" and f.evidence["limit"] == "10000.00" and f.evidence["day_total"] == "11000.00"
    assert f.message == ("Cash payments to Sharma Traders on 14-08-2026 total 11,000.00, above the daily limit of 10,000.00 "
                         "(limit pending verification); expenditure of 11,000.00 may be disallowed")
    assert r.population == ("c1", "c2", "c3") and r.population_amount == D("21000.00")


def test_A05_disallowance_uses_the_rule_percent_half_up():
    r = b.CHECKS["A-05"](facts([pay("c1", date(2026, 8, 14), "10000.01")]), PARAMS,
                         (rule("cash_payment_daily_limit", "10000.00", "above", "33.33", "verified"),))
    f = r.findings[0]
    assert f.disallowance_amount == D("3333.00") and f.rule_status == "verified"   # 10000.01 x 33.33% = 3333.0033 -> 3333.00
    assert "pending" not in f.message


def test_A05_no_rule_for_the_date_skips_and_says_so():
    old = rule("cash_payment_daily_limit", "10000.00", "above", "100", frm=date(2020, 4, 1), to=date(2026, 3, 31))
    r = b.CHECKS["A-05"](facts([pay("c1", date(2026, 8, 14), "50000.00")]), PARAMS, (old,))
    assert r.findings == () and any("14-08-2026" in n and "skipped" in n for n in r.notes)


def test_A05_rule_is_picked_by_transaction_date():
    old = rule("cash_payment_daily_limit", "10000.00", "above", "100", frm=date(2020, 4, 1), to=date(2026, 3, 31), law="it_act_1961")
    new = rule("cash_payment_daily_limit", "20000.00", "above", "100")
    r = b.CHECKS["A-05"](facts([pay("c1", date(2026, 3, 30), "15000.00"), pay("c2", date(2026, 8, 14), "15000.00")]),
                         AuditParams(from_date=date(2026, 1, 1), to_date=date(2027, 3, 31)), (old, new))
    assert [f.finding_key for f in r.findings] == ["A-05:sharma:2026-03-30"]


# ---- A-06 -------------------------------------------------------------------------------------------------------
def test_A06_cash_receipts_summing_to_exactly_the_limit_are_flagged_and_one_paisa_less_is_not():
    vs = [rec("r1", date(2026, 9, 3), "150000.00"), rec("r2", date(2026, 9, 3), "50000.00")]
    r = b.CHECKS["A-06"](facts(vs), PARAMS, (REC_LIMIT,))
    assert len(r.findings) == 1 and r.findings[0].finding_key == "A-06:mehta:2026-09-03" and r.findings[0].amount == D("200000.00")
    assert r.findings[0].evidence["voucher_ids"] == ["r1", "r2"] and r.findings[0].disallowance_amount is None
    short = [rec("r1", date(2026, 9, 3), "199999.99")]
    assert b.CHECKS["A-06"](facts(short), PARAMS, (REC_LIMIT,)).findings == ()
    bank = [rec("r1", date(2026, 9, 3), "250000.00", via=BANK)]
    assert b.CHECKS["A-06"](facts(bank), PARAMS, (REC_LIMIT,)).findings == ()


# ---- A-12 -------------------------------------------------------------------------------------------------------
def test_A12_round_totals_flagged_only_at_or_above_minimum():
    vs = [pur("p1", date(2026, 5, 1), "50000.00", "a"), pur("p2", date(2026, 5, 2), "50000.50", "b"), pur("p3", date(2026, 5, 3), "9000.00", "c"),
          pur("p4", date(2026, 5, 4), "10000.00", "d")]
    r = b.CHECKS["A-12"](facts(vs), PARAMS, ())
    assert [f.subject_id for f in r.findings] == ["p1", "p4"] and r.findings[0].amount == D("50000.00")
    assert len(r.population) == 4


# ---- A-13 -------------------------------------------------------------------------------------------------------
def test_A13_sunday_and_listed_holiday_are_flagged_ordinary_day_is_not():
    vs = [pur("sun", date(2026, 11, 22), "1.00", "a"), pur("hol", date(2026, 10, 20), "1.00", "b"), pur("ord", date(2026, 10, 21), "1.00", "c")]
    r = b.CHECKS["A-13"](facts(vs, holidays={date(2026, 10, 20): "Dussehra"}), PARAMS, ())
    assert [f.subject_id for f in r.findings] == ["hol", "sun"]
    by = {f.subject_id: f for f in r.findings}
    assert by["sun"].evidence["reason"] == "Sunday" and by["hol"].evidence["holiday_name"] == "Dussehra"
    assert "Dussehra" in by["hol"].message and "22-11-2026" in by["sun"].message


# ---- A-14 -------------------------------------------------------------------------------------------------------
PERIOD = b.PeriodFact("per5", date(2026, 5, 1), date(2026, 5, 31))


def test_A14_posted_after_a_lock_of_its_period_names_the_audit_log_row():
    lock = b.LockEvent(901, "per5", "lock", datetime(2026, 6, 3, 10, 0, tzinfo=UTC), "ca", None)
    unlock = b.LockEvent(902, "per5", "unlock", datetime(2026, 6, 10, 10, 0, tzinfo=UTC), "ca", "late bill")
    v = pur("p1", date(2026, 5, 10), "1.00", "a", posted_at=datetime(2026, 6, 12, 9, 0, tzinfo=UTC))
    early = pur("p2", date(2026, 5, 11), "1.00", "b", posted_at=datetime(2026, 6, 2, 9, 0, tzinfo=UTC))
    r = b.CHECKS["A-14"](facts([v, early], periods=(PERIOD,), lock_events=(lock, unlock)), PARAMS, ())
    assert [f.subject_id for f in r.findings] == ["p1"]
    ev = r.findings[0].evidence
    assert ev["lock_audit_log_id"] == "901" and ev["unlock_audit_log_id"] == "902" and ev["unlock_reason"] == "late bill"


def test_A14_posted_more_than_30_days_after_period_end_is_flagged_30_exactly_is_not():
    late = pur("p1", date(2026, 5, 10), "1.00", "a", posted_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC))    # 31 May + 31 days
    edge = pur("p2", date(2026, 5, 10), "1.00", "b", posted_at=datetime(2026, 6, 30, 9, 0, tzinfo=UTC))   # 31 May + 30 days
    r = b.CHECKS["A-14"](facts([late, edge], periods=(PERIOD,)), PARAMS, ())
    assert [f.subject_id for f in r.findings] == ["p1"] and r.findings[0].evidence["days_after_period_end"] == "31"


def test_A14_voucher_outside_every_period_is_noted_not_guessed():
    v = pur("p1", date(2026, 7, 10), "1.00", "a", posted_at=datetime(2026, 12, 1, 9, 0, tzinfo=UTC))
    r = b.CHECKS["A-14"](facts([v], periods=(PERIOD,)), PARAMS, ())
    assert r.findings == () and any("no period" in n for n in r.notes)
