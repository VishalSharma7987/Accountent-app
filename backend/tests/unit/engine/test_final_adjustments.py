"""Phase 6 package A: adjustment helpers F-01 .. F-11, pure engine. Expected values are typed by hand (see the plan's mini-example)."""

from datetime import date
from decimal import Decimal

from app.engine.final_adjustments import (
    AdjustmentContext,
    LedgerInfo,
    PartnerInfo,
    PartnerTermsIn,
    build_adjustment,
    doubtful_provision,
    interest_on_capital,
    interest_on_drawings,
    remuneration,
    reversal_lines,
)
from app.engine.final_types import AdjustmentInput, AdjustmentType, EntityType, JournalLineDraft

D = Decimal
FY_START, FY_END = date(2026, 4, 1), date(2027, 3, 31)
ON = date(2027, 3, 31)

RENT, ELEC, OUTST, PREPAID, COMM, ACCRUED, ADV, PROVN = "rent", "elec", "outst", "prepaid", "comm", "accrued", "adv", "provn"
MRA, DEBTOR_A, DEBTOR_B, BAD, DOUBT_EXP, DOUBT_PROV = "mra", "debtA", "debtB", "bad", "doubt_exp", "doubt_prov"
INT_CAP, INT_DRAW, REMUN, PA_PROFIT, PA_CAP, DRAWINGS, BANK = "int_cap", "int_draw", "remun", "pa_profit", "pa_cap", "drawings", "bank"


def L(i, name, group, parent, nature):
    return i, LedgerInfo(i, name, group, parent, nature)


LEDGERS = dict([
    L(RENT, "Rent", "indirect_expenses", None, "expense"),
    L(ELEC, "Electricity", "indirect_expenses", None, "expense"),
    L(OUTST, "Outstanding Expenses", "current_liabilities", None, "liability"),
    L(PREPAID, "Prepaid Expenses", "current_assets", None, "asset"),
    L(COMM, "Commission Received", "indirect_incomes", None, "income"),
    L(ACCRUED, "Accrued Income", "current_assets", None, "asset"),
    L(ADV, "Income Received in Advance", "current_liabilities", None, "liability"),
    L(PROVN, "Provision for Audit Fees", "provisions", "current_liabilities", "liability"),
    L(MRA, "Mr A", "sundry_debtors", "current_assets", "asset"),
    L(DEBTOR_B, "Mr B", "sundry_debtors", "current_assets", "asset"),
    L(BAD, "Bad Debts", "indirect_expenses", None, "expense"),
    L(DOUBT_EXP, "Provision for Doubtful Debts Exp", "indirect_expenses", None, "expense"),
    L(DOUBT_PROV, "Provision for Doubtful Debts", "provisions", "current_liabilities", "liability"),
    L(INT_CAP, "Interest on Capital", "indirect_expenses", None, "expense"),
    L(INT_DRAW, "Interest on Drawings", "indirect_incomes", None, "income"),
    L(REMUN, "Partners Remuneration", "indirect_expenses", None, "expense"),
    L(PA_PROFIT, "A Current A/c", "capital_account", None, "liability"),
    L(PA_CAP, "A Capital A/c", "capital_account", None, "liability"),
    L(DRAWINGS, "A Drawings", "capital_account", None, "liability"),
    L(BANK, "Bank", "bank_accounts", "current_assets", "asset"),
])
ROLES = {
    "bad_debts": BAD, "doubtful_debts_expense": DOUBT_EXP, "provision_doubtful_debts": DOUBT_PROV,
    "interest_on_capital": INT_CAP, "interest_on_drawings": INT_DRAW, "partner_remuneration": REMUN,
}
PARTNER = PartnerInfo("pA", "A", PA_CAP, PA_PROFIT)
TERMS = PartnerTermsIn(D("10.0000"), D("12.0000"), D("60000.00"), "Deed dated 01-04-2020 clause 7")


def ctx(entity=EntityType.PROPRIETORSHIP, **kw):
    base = {"entity_type": entity, "fy_start": FY_START, "fy_end": FY_END, "ledgers": LEDGERS, "roles": ROLES,
            "closing_balances": {MRA: D("50000.00"), DEBTOR_B: D("-1000.00")}, "debtors_closing": None,
            "partner": None, "terms": None, "capital_opening": D("0.00"), "capital_movements": (), "drawings": ()}
    base.update(kw)
    return AdjustmentContext(**base)


def pctx(**kw):
    return ctx(EntityType.PARTNERSHIP, partner=PARTNER, terms=TERMS, **kw)


def adj(t, **kw):
    base = {"adj_type": t, "as_on_date": ON, "basis_note": "Year-end working"}
    base.update(kw)
    return AdjustmentInput(**base)


def pairs(result):
    return [(x.ledger_id, x.debit, x.credit) for x in result.lines]


def rules(findings):
    return [f.rule_id for f in findings]


# ------------------------------------------------------------------------------------------------ F-03 simple entries


def test_F03_outstanding_expense_dr_expense_cr_outstanding():
    r = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=D("5000"), debit_ledger_id=RENT, credit_ledger_id=OUTST), ctx())
    assert pairs(r) == [(RENT, D("5000.00"), D("0.00")), (OUTST, D("0.00"), D("5000.00"))]
    assert r.amount == D("5000.00")
    assert "Outstanding" in r.narration and "31-03-2027" in r.narration and "Year-end working" in r.narration


def test_F03_prepaid_expense_dr_prepaid_cr_expense():
    r = build_adjustment(adj(AdjustmentType.PREPAID_EXPENSE, amount=D("2000"), debit_ledger_id=PREPAID, credit_ledger_id=ELEC), ctx())
    assert pairs(r) == [(PREPAID, D("2000.00"), D("0.00")), (ELEC, D("0.00"), D("2000.00"))]


def test_F03_accrued_income_dr_accrued_cr_income():
    r = build_adjustment(adj(AdjustmentType.ACCRUED_INCOME, amount=D("750.50"), debit_ledger_id=ACCRUED, credit_ledger_id=COMM), ctx())
    assert pairs(r) == [(ACCRUED, D("750.50"), D("0.00")), (COMM, D("0.00"), D("750.50"))]


def test_F03_income_in_advance_dr_income_cr_advance():
    r = build_adjustment(adj(AdjustmentType.INCOME_IN_ADVANCE, amount=D("1200"), debit_ledger_id=COMM, credit_ledger_id=ADV), ctx())
    assert pairs(r) == [(COMM, D("1200.00"), D("0.00")), (ADV, D("0.00"), D("1200.00"))]


def test_F03_provision_dr_expense_cr_provision_ledger():
    r = build_adjustment(adj(AdjustmentType.PROVISION, amount=D("8000"), debit_ledger_id=RENT, credit_ledger_id=PROVN), ctx())
    assert pairs(r) == [(RENT, D("8000.00"), D("0.00")), (PROVN, D("0.00"), D("8000.00"))]


def test_F03_params_record_the_ledgers_for_the_duplicate_check():
    r = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=D("5000"), debit_ledger_id=RENT, credit_ledger_id=OUTST), ctx())
    assert r.params["debit_ledger_id"] == RENT and r.params["credit_ledger_id"] == OUTST


# ------------------------------------------------------------------------------------------------ F-01


def test_F01_zero_negative_and_missing_amount_rejected():
    for amount in (D("0"), D("-5"), None):
        f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=amount, debit_ledger_id=RENT, credit_ledger_id=OUTST), ctx())
        assert rules(f) == ["F-01"], amount


def test_F01_three_decimals_rejected_not_rounded():
    f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=D("10.005"), debit_ledger_id=RENT, credit_ledger_id=OUTST), ctx())
    assert rules(f) == ["F-01"] and "decimal" in f[0].message


def test_F01_trailing_zero_decimals_are_fine():
    r = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=D("10.500"), debit_ledger_id=RENT, credit_ledger_id=OUTST), ctx())
    assert r.amount == D("10.50")


def test_F01_basis_note_required():
    f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, basis_note="  ", amount=D("5"), debit_ledger_id=RENT, credit_ledger_id=OUTST), ctx())
    assert rules(f) == ["F-01"]


def test_F01_date_outside_the_financial_year_rejected():
    f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, as_on_date=date(2027, 4, 1), amount=D("5"), debit_ledger_id=RENT,
                             credit_ledger_id=OUTST), ctx())
    assert rules(f) == ["F-01"] and "01-04-2027" in f[0].message


# ------------------------------------------------------------------------------------------------ F-02 ledger fit


def test_F02_outstanding_expense_with_a_debtor_as_expense_rejected():
    f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=D("5"), debit_ledger_id=MRA, credit_ledger_id=OUTST), ctx())
    assert rules(f) == ["F-02"] and "Mr A" in f[0].message and f[0].ledger_id == MRA


def test_F02_outstanding_with_an_asset_as_liability_rejected():
    f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=D("5"), debit_ledger_id=RENT, credit_ledger_id=PREPAID), ctx())
    assert rules(f) == ["F-02"] and f[0].ledger_id == PREPAID


def test_F02_prepaid_with_a_liability_as_prepaid_rejected():
    f = build_adjustment(adj(AdjustmentType.PREPAID_EXPENSE, amount=D("5"), debit_ledger_id=OUTST, credit_ledger_id=ELEC), ctx())
    assert rules(f) == ["F-02"]


def test_F02_provision_credit_must_be_in_the_provisions_group():
    f = build_adjustment(adj(AdjustmentType.PROVISION, amount=D("5"), debit_ledger_id=RENT, credit_ledger_id=OUTST), ctx())
    assert rules(f) == ["F-02"]


def test_F02_ledgers_missing_or_unknown_or_same_rejected():
    f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=D("5")), ctx())
    assert rules(f) == ["F-02", "F-02"]
    f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=D("5"), debit_ledger_id="nope", credit_ledger_id=OUTST), ctx())
    assert rules(f) == ["F-02"]
    f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, amount=D("5"), debit_ledger_id=RENT, credit_ledger_id=RENT), ctx())
    assert "F-02" in rules(f)


# ------------------------------------------------------------------------------------------------ F-06 bad debt


def test_F06_bad_debt_dr_bad_debts_cr_debtor():
    r = build_adjustment(adj(AdjustmentType.BAD_DEBT, amount=D("10000"), party_ledger_id=MRA), ctx())
    assert pairs(r) == [(BAD, D("10000.00"), D("0.00")), (MRA, D("0.00"), D("10000.00"))]


def test_F06_bad_debt_equal_to_the_balance_is_allowed():
    r = build_adjustment(adj(AdjustmentType.BAD_DEBT, amount=D("50000"), party_ledger_id=MRA), ctx())
    assert r.amount == D("50000.00")


def test_F06_bad_debt_above_the_balance_rejected_with_amounts():
    f = build_adjustment(adj(AdjustmentType.BAD_DEBT, amount=D("50000.01"), party_ledger_id=MRA), ctx())
    assert rules(f) == ["F-06"] and "50,000.01" in f[0].message and "50,000.00" in f[0].message


def test_F06_credit_balance_debtor_cannot_be_written_off():
    f = build_adjustment(adj(AdjustmentType.BAD_DEBT, amount=D("100"), party_ledger_id=DEBTOR_B), ctx())
    assert rules(f) == ["F-06"]


def test_F06_party_must_be_a_sundry_debtor():
    f = build_adjustment(adj(AdjustmentType.BAD_DEBT, amount=D("100"), party_ledger_id=RENT), ctx())
    assert rules(f) == ["F-06"]


def test_F02_bad_debt_needs_the_bad_debts_role():
    f = build_adjustment(adj(AdjustmentType.BAD_DEBT, amount=D("100"), party_ledger_id=MRA), ctx(roles={}))
    assert rules(f) == ["F-02"] and "bad_debts" in f[0].message


# ------------------------------------------------------------------------------------------------ F-05 doubtful debts


def test_F05_provision_five_percent_on_2_40_000_is_12_000():
    assert doubtful_provision(D("240000.00"), D("5"), D("0.00")) == D("12000.00")


def test_F05_increase_dr_expense_cr_provision():
    r = build_adjustment(adj(AdjustmentType.PROVISION_DOUBTFUL_DEBTS, rate_percent=D("5")), ctx(debtors_closing=D("240000.00")))
    assert pairs(r) == [(DOUBT_EXP, D("12000.00"), D("0.00")), (DOUBT_PROV, D("0.00"), D("12000.00"))]
    assert r.amount == D("12000.00")
    assert r.params["required"] == "12000.00" and r.params["existing"] == "0.00" and r.params["debtors"] == "240000.00"


def test_F05_decrease_dr_provision_cr_expense():
    r = build_adjustment(adj(AdjustmentType.PROVISION_DOUBTFUL_DEBTS, rate_percent=D("5")),
                         ctx(debtors_closing=D("240000.00"), closing_balances={DOUBT_PROV: D("-15000.00")}))
    assert pairs(r) == [(DOUBT_PROV, D("3000.00"), D("0.00")), (DOUBT_EXP, D("0.00"), D("3000.00"))]


def test_F05_increase_over_existing_provision_posts_only_the_difference():
    r = build_adjustment(adj(AdjustmentType.PROVISION_DOUBTFUL_DEBTS, rate_percent=D("5")),
                         ctx(debtors_closing=D("240000.00"), closing_balances={DOUBT_PROV: D("-5000.00")}))
    assert r.amount == D("7000.00")


def test_F05_no_change_refused():
    f = build_adjustment(adj(AdjustmentType.PROVISION_DOUBTFUL_DEBTS, rate_percent=D("5")),
                         ctx(debtors_closing=D("240000.00"), closing_balances={DOUBT_PROV: D("-12000.00")}))
    assert rules(f) == ["F-05"] and "no change" in f[0].message.lower()


def test_F05_rounds_half_up_once():
    assert doubtful_provision(D("33333.33"), D("5"), D("0.00")) == D("1666.67")  # 1,666.6665
    assert doubtful_provision(D("10.10"), D("5"), D("0.00")) == D("0.51")  # 0.505


def test_F05_typed_amount_rejected():
    f = build_adjustment(adj(AdjustmentType.PROVISION_DOUBTFUL_DEBTS, amount=D("12000"), rate_percent=D("5")), ctx(debtors_closing=D("240000")))
    assert rules(f) == ["F-05"] and "computed" in f[0].message


def test_F05_rate_required_and_within_0_to_100():
    for rate in (None, D("0"), D("-1"), D("100.5"), D("5.12345")):
        f = build_adjustment(adj(AdjustmentType.PROVISION_DOUBTFUL_DEBTS, rate_percent=rate), ctx(debtors_closing=D("240000")))
        assert rules(f) == ["F-05"], rate


def test_F02_doubtful_debts_needs_both_roles():
    f = build_adjustment(adj(AdjustmentType.PROVISION_DOUBTFUL_DEBTS, rate_percent=D("5")),
                         ctx(debtors_closing=D("240000"), roles={}))
    assert rules(f) == ["F-02", "F-02"]


# ------------------------------------------------------------------------------------------------ F-07 interest


def test_F07_interest_on_capital_full_year_300000_at_10_is_30000():
    r = build_adjustment(adj(AdjustmentType.INTEREST_ON_CAPITAL, partner_id="pA"), pctx(capital_opening=D("-300000.00")))
    assert pairs(r) == [(INT_CAP, D("30000.00"), D("0.00")), (PA_PROFIT, D("0.00"), D("30000.00"))]
    assert r.params["rate_percent"] == "10.0000" and r.params["deed_reference"].startswith("Deed dated")


def test_F07_interest_on_capital_day_weighted_with_new_capital_on_1_october():
    # 3,00,000 for 183 days + 4,00,000 for 182 days = 12,77,00,000 rupee-days x 10% / 365 = 34,986.30
    got = interest_on_capital(D("-300000"), ((date(2026, 10, 1), D("-100000")),), D("10"), FY_START, FY_END)
    assert got == D("34986.30")


def test_F07_interest_on_capital_withdrawal_reduces_the_base():
    # 4,00,000 for 183 days, 3,00,000 for 182 days = 73,200,000 + 54,600,000 = 127,800,000 x 10% / 365 = 35,013.6986...
    got = interest_on_capital(D("-400000"), ((date(2026, 10, 1), D("100000")),), D("10"), FY_START, FY_END)
    assert got == D("35013.70")


def test_F07_interest_on_capital_debit_balance_earns_nothing():
    got = interest_on_capital(D("100000"), (), D("10"), FY_START, FY_END)
    assert got == D("0.00")


def test_F07_interest_on_capital_zero_base_refused():
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_CAPITAL, partner_id="pA"), pctx())
    assert rules(f) == ["F-07"] and "no capital" in f[0].message.lower()


def test_F07_interest_on_drawings_one_drawing_of_12000_on_1_october_at_12_is_718_03():
    # 12,000 x 182 days = 21,84,000 x 12% / 365 = 718.0273...
    assert interest_on_drawings(((date(2026, 10, 1), D("12000")),), D("12"), FY_START, FY_END) == D("718.03")


def test_F07_interest_on_drawings_two_drawings():
    # 21,84,000 + 6,000 x 90 days (01-01-2027 .. 31-03-2027) = 5,40,000 -> 27,24,000 x 12% / 365 = 895.56
    got = interest_on_drawings(((date(2026, 10, 1), D("12000")), (date(2027, 1, 1), D("6000"))), D("12"), FY_START, FY_END)
    assert got == D("895.56")


def test_F07_interest_on_drawings_entry_dr_partner_cr_interest_income():
    r = build_adjustment(adj(AdjustmentType.INTEREST_ON_DRAWINGS, partner_id="pA", party_ledger_id=DRAWINGS),
                         pctx(drawings=((date(2026, 10, 1), D("12000")),)))
    assert pairs(r) == [(PA_PROFIT, D("718.03"), D("0.00")), (INT_DRAW, D("0.00"), D("718.03"))]


def test_F07_interest_on_drawings_needs_the_drawings_ledger_and_some_drawings():
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_DRAWINGS, partner_id="pA"), pctx(drawings=((date(2026, 10, 1), D("5")),)))
    assert rules(f) == ["F-02"]
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_DRAWINGS, partner_id="pA", party_ledger_id=DRAWINGS), pctx())
    assert rules(f) == ["F-07"]
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_DRAWINGS, partner_id="pA", party_ledger_id=BANK), pctx())
    assert "F-02" in rules(f)


def test_F07_typed_amount_or_rate_rejected():
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_CAPITAL, partner_id="pA", amount=D("30000")), pctx(capital_opening=D("-300000")))
    assert rules(f) == ["F-07"]
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_CAPITAL, partner_id="pA", rate_percent=D("9")), pctx(capital_opening=D("-300000")))
    assert rules(f) == ["F-07"]


def test_F07_deed_rate_missing_refused():
    terms = PartnerTermsIn(None, None, None, None)
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_CAPITAL, partner_id="pA"),
                         ctx(EntityType.PARTNERSHIP, partner=PARTNER, terms=terms, capital_opening=D("-300000")))
    assert rules(f) == ["F-07"] and "deed" in f[0].message.lower()
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_CAPITAL, partner_id="pA"), ctx(EntityType.PARTNERSHIP, partner=PARTNER, terms=None))
    assert rules(f) == ["F-07"]


def test_F07_partner_required():
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_CAPITAL), ctx(EntityType.PARTNERSHIP))
    assert rules(f) == ["F-07"]


def test_F02_interest_needs_its_role_ledger():
    f = build_adjustment(adj(AdjustmentType.INTEREST_ON_CAPITAL, partner_id="pA"), pctx(capital_opening=D("-300000"), roles={}))
    assert rules(f) == ["F-02"]


# ------------------------------------------------------------------------------------------------ F-08 remuneration


def test_F08_remuneration_5000_x_12_is_60000():
    assert remuneration(D("60000.00"), 12) == D("60000.00")
    r = build_adjustment(adj(AdjustmentType.PARTNER_REMUNERATION, partner_id="pA"), pctx())
    assert pairs(r) == [(REMUN, D("60000.00"), D("0.00")), (PA_PROFIT, D("0.00"), D("60000.00"))]


def test_F08_months_prorate_and_round_half_up():
    assert remuneration(D("60000"), 5) == D("25000.00")
    assert remuneration(D("100000"), 7) == D("58333.33")  # 58,333.333
    assert remuneration(D("100001"), 1) == D("8333.42")  # 8,333.41666


def test_F08_months_outside_1_to_12_rejected():
    for months in (0, 13, -1):
        f = build_adjustment(adj(AdjustmentType.PARTNER_REMUNERATION, partner_id="pA"), pctx(), months=months)
        assert rules(f) == ["F-08"], months


def test_F08_months_five_through_the_builder():
    r = build_adjustment(adj(AdjustmentType.PARTNER_REMUNERATION, partner_id="pA"), pctx(), months=5)
    assert r.amount == D("25000.00") and r.params["months"] == 5


def test_F08_remuneration_not_in_the_deed_refused_and_typed_amount_rejected():
    ctx_none = ctx(EntityType.PARTNERSHIP, partner=PARTNER, terms=PartnerTermsIn(D("10"), None, None, "Deed"))
    assert rules(build_adjustment(adj(AdjustmentType.PARTNER_REMUNERATION, partner_id="pA"), ctx_none)) == ["F-08"]
    assert rules(build_adjustment(adj(AdjustmentType.PARTNER_REMUNERATION, partner_id="pA", amount=D("1")), pctx())) == ["F-08"]


# ------------------------------------------------------------------------------------------------ F-09 entity gate


def test_F09_proprietorship_and_company_refused_for_partner_helpers():
    for entity in (EntityType.PROPRIETORSHIP, EntityType.COMPANY):
        for t in (AdjustmentType.INTEREST_ON_CAPITAL, AdjustmentType.INTEREST_ON_DRAWINGS, AdjustmentType.PARTNER_REMUNERATION):
            f = build_adjustment(adj(t, partner_id="pA"), ctx(entity, partner=PARTNER, terms=TERMS, capital_opening=D("-300000")))
            assert rules(f) == ["F-09"], (entity, t)


def test_F09_llp_is_allowed():
    r = build_adjustment(adj(AdjustmentType.PARTNER_REMUNERATION, partner_id="pA"), ctx(EntityType.LLP, partner=PARTNER, terms=TERMS))
    assert r.amount == D("60000.00")


# ------------------------------------------------------------------------------------------------ F-04 reversal


def test_F04_reversal_lines_swap_every_side():
    lines = (JournalLineDraft(RENT, D("5000.00"), D("0.00")), JournalLineDraft(OUTST, D("0.00"), D("5000.00")))
    assert [(x.ledger_id, x.debit, x.credit) for x in reversal_lines(lines)] == [(RENT, D("0.00"), D("5000.00")), (OUTST, D("5000.00"), D("0.00"))]


def test_F04_auto_reverse_must_be_first_day_of_next_year():
    base = {"amount": D("5000"), "debit_ledger_id": RENT, "credit_ledger_id": OUTST}
    ok = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, auto_reverse_on=date(2027, 4, 1), **base), ctx())
    assert ok.amount == D("5000.00") and ok.params["auto_reverse_on"] == "2027-04-01"
    f = build_adjustment(adj(AdjustmentType.OUTSTANDING_EXPENSE, auto_reverse_on=date(2027, 4, 2), **base), ctx())
    assert rules(f) == ["F-04"] and "01-04-2027" in f[0].message


def test_F04_auto_reverse_refused_for_bad_debt_and_computed_types():
    f = build_adjustment(adj(AdjustmentType.BAD_DEBT, amount=D("100"), party_ledger_id=MRA, auto_reverse_on=date(2027, 4, 1)), ctx())
    assert rules(f) == ["F-04"]
    f = build_adjustment(adj(AdjustmentType.PARTNER_REMUNERATION, partner_id="pA", auto_reverse_on=date(2027, 4, 1)), pctx())
    assert rules(f) == ["F-04"]


def test_F11_every_result_is_balanced():
    r = build_adjustment(adj(AdjustmentType.PROVISION_DOUBTFUL_DEBTS, rate_percent=D("5")), ctx(debtors_closing=D("240000.00")))
    assert sum(x.debit for x in r.lines) == sum(x.credit for x in r.lines)
    assert all((x.debit > 0) != (x.credit > 0) for x in r.lines)
