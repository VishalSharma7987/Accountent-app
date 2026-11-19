"""Phase 6 package C: Trading A/c, Profit and Loss, Appropriation and Balance Sheet of a non-company client (F-40..F-43, F-44b, F-48).

Every expected figure is hand-calculated from docs/PHASE6_PLAN.md (worked mini-example, re-derived: gross profit 4,20,000; net profit
1,90,000; balance sheet 7,75,000 each side; vertical 6,10,000) and typed literally.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.engine import final_statements as fs
from app.engine.final_types import (
    ClosingStockIn,
    EntityType,
    LedgerBalanceIn,
    PartnerShare,
    StatementFormat,
)

D = Decimal
FROM, TO = date(2026, 4, 1), date(2027, 3, 31)
NAMES = {"sundry_debtors": "Sundry Debtors", "sundry_creditors": "Sundry Creditors", "bank_accounts": "Bank Accounts",
         "cash_in_hand": "Cash-in-hand", "stock_in_hand": "Stock-in-hand", "provisions": "Provisions"}


def L(lid, name, group, nature, closing, *, opening="0", parent=None, role=None, dr="0", cr="0"):
    return LedgerBalanceIn(lid, name, group, parent, nature, D(opening), D(dr), D(cr), D(closing), role=role)


def mini_ledgers():
    """Closing balances of the plan's mini-example after the five adjustments (debit positive)."""
    return [
        L("stock", "Opening Stock", "stock_in_hand", "asset", "200000", opening="200000", parent="current_assets"),
        L("pur", "Purchases", "purchase_accounts", "expense", "800000"),
        L("frt", "Freight", "direct_expenses", "expense", "30000"),
        L("sal", "Salary", "indirect_expenses", "expense", "120000"),
        L("rent", "Rent", "indirect_expenses", "expense", "65000"),
        L("elec", "Electricity", "indirect_expenses", "expense", "18000"),
        L("dep", "Depreciation", "indirect_expenses", "expense", "10000", role="depreciation_expense"),
        L("bad", "Bad Debts", "indirect_expenses", "expense", "10000", role="bad_debts"),
        L("pexp", "Provision for Doubtful Debts Exp", "indirect_expenses", "expense", "12000", role="doubtful_debts_expense"),
        L("draw", "Drawings", "capital_account", "liability", "100000"),
        L("fur", "Furniture", "fixed_assets", "asset", "100000", opening="100000"),
        L("acc", "Accumulated Depreciation", "fixed_assets", "asset", "-10000", role="accumulated_depreciation"),
        L("debt", "Mr A", "sundry_debtors", "asset", "240000", opening="150000", parent="current_assets"),
        L("pre", "Prepaid Expenses", "current_assets", "asset", "2000"),
        L("cash", "Cash", "cash_in_hand", "asset", "25000", opening="30000", parent="current_assets"),
        L("bank", "Bank", "bank_accounts", "asset", "180000", opening="120000", parent="current_assets"),
        L("cap", "Capital", "capital_account", "liability", "-500000", opening="-500000"),
        L("loan", "Loan", "loans_liability", "liability", "-20000", opening="-20000"),
        L("cred", "Creditors", "sundry_creditors", "liability", "-160000", opening="-80000", parent="current_liabilities"),
        L("out", "Outstanding Expenses", "current_liabilities", "liability", "-5000"),
        L("prov", "Provision for Doubtful Debts", "provisions", "liability", "-12000", role="provision_doubtful_debts",
          parent="current_liabilities"),
        L("sales", "Sales", "sales_accounts", "income", "-1200000"),
        L("int", "Interest Income", "indirect_incomes", "income", "-5000"),
    ]


def stock(carrying="250000", source="inventory_report", on=TO):
    return ClosingStockIn(D("260000"), D("10000"), D(carrying), source, on)


NONE_STOCK = ClosingStockIn(D("0"), D("0"), D("0"), "none", TO)


def ctx(entity=EntityType.PROPRIETORSHIP, st="default", partners=()):
    return fs.StatementContext(entity, FROM, TO, stock() if st == "default" else st, tuple(partners), NAMES)


def amounts(lines):
    return {x.code: x.amount for x in lines}


def test_F42_trading_account_mini_example():
    s = fs.build_trading(mini_ledgers(), ctx())
    assert amounts(s.left) == {"opening_stock": D("200000.00"), "ledger:pur": D("800000.00"), "ledger:frt": D("30000.00"),
                               "gross_profit": D("420000.00"), "total": D("1450000.00")}
    assert amounts(s.right) == {"ledger:sales": D("1200000.00"), "closing_stock": D("250000.00"), "total": D("1450000.00")}
    assert s.totals["gross_profit"] == D("420000.00")
    assert s.findings == ()


def test_F42_gross_loss_goes_to_the_credit_side():
    ledgers = [L("pur", "Purchases", "purchase_accounts", "expense", "500000"), L("sales", "Sales", "sales_accounts", "income", "-400000"),
               L("cap", "Capital", "capital_account", "liability", "-100000")]
    s = fs.build_trading(ledgers, ctx(st=NONE_STOCK))
    assert amounts(s.left)["total"] == D("500000.00") and amounts(s.right)["gross_loss"] == D("100000.00")
    assert s.totals["gross_profit"] == D("-100000.00")


def test_F41_missing_closing_stock_is_an_error_and_never_guessed():
    s = fs.build_trading(mini_ledgers(), ctx(st=None))
    assert [f.rule_id for f in s.findings if f.severity == "error"] == ["F-41"]
    assert amounts(s.right)["closing_stock"] == D("0.00")


def test_F41_closing_stock_approved_for_another_date_is_an_error():
    s = fs.build_trading(mini_ledgers(), ctx(st=stock(on=date(2027, 2, 28))))
    assert [f.rule_id for f in s.findings] == ["F-41"]
    assert "28-02-2027" in s.findings[0].message and "31-03-2027" in s.findings[0].message


def test_F43_profit_and_loss_horizontal_mini_example():
    s = fs.build_profit_loss(mini_ledgers(), ctx(), StatementFormat.HORIZONTAL)
    assert amounts(s.left) == {"ledger:sal": D("120000.00"), "ledger:rent": D("65000.00"), "ledger:elec": D("18000.00"),
                               "ledger:dep": D("10000.00"), "ledger:bad": D("10000.00"), "ledger:pexp": D("12000.00"),
                               "net_profit": D("190000.00"), "total": D("425000.00")}
    assert amounts(s.right) == {"gross_profit": D("420000.00"), "ledger:int": D("5000.00"), "total": D("425000.00")}
    assert s.totals["net_profit"] == D("190000.00")


def test_F43_profit_and_loss_vertical_mini_example():
    s = fs.build_profit_loss(mini_ledgers(), ctx(), StatementFormat.VERTICAL)
    assert s.right == ()
    a = amounts(s.left)
    assert a["gross_profit"] == D("420000.00") and a["ledger:int"] == D("5000.00") and a["ledger:rent"] == D("65000.00")
    assert a["net_profit"] == D("190000.00") and s.totals["net_profit"] == D("190000.00")


def test_F43_net_loss_is_shown_as_a_loss_on_the_credit_side():
    ledgers = [L("sal", "Salary", "indirect_expenses", "expense", "50000"), L("cap", "Capital", "capital_account", "liability", "-50000")]
    s = fs.build_profit_loss(ledgers, ctx(st=NONE_STOCK), StatementFormat.HORIZONTAL)
    assert amounts(s.right)["net_loss"] == D("50000.00") and s.totals["net_profit"] == D("-50000.00")


def test_F44b_balance_sheet_horizontal_mini_example():
    s = fs.build_balance_sheet(mini_ledgers(), ctx(), StatementFormat.HORIZONTAL)
    assert amounts(s.left) == {"capital": D("590000.00"), "ledger:loan": D("20000.00"), "sundry_creditors": D("160000.00"),
                               "ledger:out": D("5000.00"), "total": D("775000.00")}
    assert amounts(s.right) == {"fixed_assets": D("90000.00"), "closing_stock": D("250000.00"), "sundry_debtors": D("228000.00"),
                                "ledger:pre": D("2000.00"), "cash_in_hand": D("25000.00"), "bank_accounts": D("180000.00"),
                                "total": D("775000.00")}
    assert s.findings == ()
    assert s.totals["total_assets"] == D("775000.00") and s.totals["total_liabilities"] == D("775000.00")


def test_F48_every_line_has_drill_down_with_the_ledgers_behind_it():
    s = fs.build_balance_sheet(mini_ledgers(), ctx(), StatementFormat.HORIZONTAL)
    cap = next(x for x in s.left if x.code == "capital")
    assert [(d.ledger_name, d.amount) for d in cap.drill] == [("Capital", D("500000.00")), ("Drawings", D("-100000.00")),
                                                              ("Net profit for the year", D("190000.00"))]
    assert cap.drill[2].ledger_id is None
    fixed = next(x for x in s.right if x.code == "fixed_assets")
    assert [(d.ledger_id, d.amount) for d in fixed.drill] == [("fur", D("100000.00")), ("acc", D("-10000.00"))]
    debtors = next(x for x in s.right if x.code == "sundry_debtors")
    assert [(d.ledger_id, d.amount) for d in debtors.drill] == [("debt", D("240000.00")), ("prov", D("-12000.00"))]
    t = fs.build_trading(mini_ledgers(), ctx())
    sales = next(x for x in t.right if x.code == "ledger:sales")
    assert [(d.ledger_id, d.amount) for d in sales.drill] == [("sales", D("1200000.00"))]
    opening = next(x for x in t.left if x.code == "opening_stock")
    assert [(d.ledger_id, d.amount) for d in opening.drill] == [("stock", D("200000.00"))]


def test_F47_balance_sheet_vertical_mini_example():
    s = fs.build_balance_sheet(mini_ledgers(), ctx(), StatementFormat.VERTICAL)
    assert s.right == ()
    a = {x.code: x.amount for x in s.left if x.level == 0}
    assert a["capital"] == D("590000.00") and a["ledger:loan"] == D("20000.00") and a["sources_total"] == D("610000.00")
    assert a["fixed_assets"] == D("90000.00") and a["net_current_assets"] == D("520000.00")
    assert a["application_total"] == D("610000.00")
    nca = {x.code: x.amount for x in s.left if x.level == 1}
    assert nca["sundry_creditors"] == D("160000.00") and nca["ledger:out"] == D("5000.00") and nca["closing_stock"] == D("250000.00")
    assert s.totals["net_current_assets"] == D("520000.00") and s.findings == ()


def test_F44b_an_unbalanced_balance_sheet_shows_the_difference_and_blocks():
    ledgers = [x for x in mini_ledgers() if x.ledger_id != "cash"]
    s = fs.build_balance_sheet(ledgers, ctx(), StatementFormat.HORIZONTAL)
    errors = [f for f in s.findings if f.severity == "error"]
    assert "F-44b" in [f.rule_id for f in errors]
    assert "25,000.00" in next(f for f in errors if f.rule_id == "F-44b").message


def test_F40_trial_balance_and_openings_must_balance():
    ledgers = mini_ledgers() + [L("x", "Stray", "indirect_expenses", "expense", "100.50")]
    s = fs.build_trading(ledgers, ctx())
    f40 = [f for f in s.findings if f.rule_id == "F-40"]
    assert len(f40) == 1 and "100.50" in f40[0].message
    ledgers = mini_ledgers() + [L("y", "Opening only", "indirect_expenses", "expense", "0", opening="7.00")]
    assert any(f.rule_id == "F-40" and "7.00" in f.message for f in fs.build_trading(ledgers, ctx()).findings)


def test_F40_a_stock_ledger_with_entries_in_the_year_is_flagged():
    ledgers = mini_ledgers()
    ledgers[0] = L("stock", "Opening Stock", "stock_in_hand", "asset", "200000", opening="200000", parent="current_assets", dr="500")
    found = fs.build_trading(ledgers, ctx()).findings
    assert any(f.rule_id == "F-40" and f.severity == "warning" and f.ledger_id == "stock" for f in found)


def test_F44b_proprietor_with_a_net_loss_reduces_capital():
    ledgers = [L("cap", "Capital", "capital_account", "liability", "-100000"), L("sal", "Salary", "indirect_expenses", "expense", "30000"),
               L("bank", "Bank", "bank_accounts", "asset", "70000", parent="current_assets")]
    s = fs.build_balance_sheet(ledgers, ctx(st=NONE_STOCK), StatementFormat.HORIZONTAL)
    assert amounts(s.left)["capital"] == D("70000.00") and s.findings == ()


def test_F44b_an_overdrawn_bank_moves_to_the_liability_side():
    ledgers = [L("cap", "Capital", "capital_account", "liability", "-10000"),
               L("bank", "Bank OD", "bank_accounts", "asset", "-5000", parent="current_assets"),
               L("fur", "Furniture", "fixed_assets", "asset", "15000")]
    s = fs.build_balance_sheet(ledgers, ctx(st=NONE_STOCK), StatementFormat.HORIZONTAL)
    assert amounts(s.left)["bank_accounts"] == D("5000.00") and amounts(s.left)["total"] == D("15000.00")
    assert amounts(s.right)["total"] == D("15000.00") and s.findings == ()


# ---------------------------------------------------------------------------------------------- partnership appropriation (F-43, F-62)


def firm_ledgers(drawings_interest=False):
    """Net profit before appropriation 2,50,000: sales 5,00,000 less indirect expenses 2,50,000; interest on capital 30,000 + 20,000 and
    A's remuneration 60,000 are posted to their own ledgers and credited to the partners; bank 7,50,000 balances the books."""
    rows = [
        L("sales", "Sales", "sales_accounts", "income", "-500000"),
        L("exp", "Office Expenses", "indirect_expenses", "expense", "250000"),
        L("ioc", "Interest on Capital", "indirect_expenses", "expense", "50000", role="interest_on_capital"),
        L("rem", "Partners Remuneration", "indirect_expenses", "expense", "60000", role="partner_remuneration"),
        L("capA", "A Capital", "capital_account", "liability", "-390000"),
        L("capB", "B Capital", "capital_account", "liability", "-220000"),
        L("bank", "Bank", "bank_accounts", "asset", "760000" if drawings_interest else "750000", parent="current_assets"),
    ]
    if drawings_interest:  # 10,000 interest on drawings: income, debited to the partners (capital ledgers 10,000 lower)
        rows += [L("iod", "Interest on Drawings", "indirect_incomes", "income", "-10000", role="interest_on_drawings")]
    return rows


PARTNERS = (PartnerShare("A", "A", "capA", D("60.0000")), PartnerShare("B", "B", "capB", D("40.0000")))


def test_F43_partnership_profit_and_loss_stops_at_net_profit_before_appropriation():
    s = fs.build_profit_loss(firm_ledgers(), ctx(EntityType.PARTNERSHIP, NONE_STOCK, PARTNERS), StatementFormat.HORIZONTAL)
    assert amounts(s.left) == {"ledger:exp": D("250000.00"), "net_profit": D("250000.00"), "total": D("500000.00")}
    assert s.totals["net_profit"] == D("250000.00")
    assert "before appropriation" in next(x for x in s.left if x.code == "net_profit").label.lower()


def test_F43_F62_appropriation_account_shares_the_balance_in_the_profit_ratio():
    s = fs.build_appropriation(firm_ledgers(), ctx(EntityType.PARTNERSHIP, NONE_STOCK, PARTNERS))
    assert amounts(s.left) == {"ledger:ioc": D("50000.00"), "ledger:rem": D("60000.00"), "share:A": D("84000.00"),
                               "share:B": D("56000.00"), "total": D("250000.00")}
    assert amounts(s.right) == {"net_profit_before_appropriation": D("250000.00"), "total": D("250000.00")}
    assert s.totals["balance_to_share"] == D("140000.00") and s.findings == ()


def test_F43_interest_on_drawings_is_income_of_the_appropriation_account():
    s = fs.build_appropriation(firm_ledgers(True), ctx(EntityType.LLP, NONE_STOCK, PARTNERS))
    assert amounts(s.right)["ledger:iod"] == D("10000.00") and s.totals["balance_to_share"] == D("150000.00")
    assert amounts(s.left)["share:A"] == D("90000.00") and amounts(s.left)["share:B"] == D("60000.00")
    assert amounts(s.left)["total"] == D("260000.00") and amounts(s.right)["total"] == D("260000.00")


def test_F62_last_partner_takes_the_rounding_remainder():
    # 50:50 on 1,00,000.01: each half is 50,000.005 -> A rounds half up to 50,000.01, B takes the remainder 50,000.00 (sum 1,00,000.01).
    # (The plan's 3:2 example of 1,00,001.00 is not a remainder case: 60,000.60 + 40,000.40 = 1,00,001.00 exactly.)
    ledgers = [L("sales", "Sales", "sales_accounts", "income", "-100000.01"),
               L("bank", "Bank", "bank_accounts", "asset", "100000.01", parent="current_assets")]
    half = (PartnerShare("A", "A", "capA", D("50.0000")), PartnerShare("B", "B", "capB", D("50.0000")))
    s = fs.build_appropriation(ledgers, ctx(EntityType.PARTNERSHIP, NONE_STOCK, half))
    assert amounts(s.left)["share:A"] == D("50000.01") and amounts(s.left)["share:B"] == D("50000.00")
    three = (PartnerShare("A", "A", "capA", D("60.0000")), PartnerShare("B", "B", "capB", D("40.0000")))
    s = fs.build_appropriation(ledgers[:1] + ledgers[1:], ctx(EntityType.PARTNERSHIP, NONE_STOCK, three))
    assert amounts(s.left)["share:A"] == D("60000.01") and amounts(s.left)["share:B"] == D("40000.00")


def test_F62_shares_not_adding_to_100_block_and_the_profit_stays_unallocated():
    bad = (PartnerShare("A", "A", "capA", D("60.0000")), PartnerShare("B", "B", "capB", D("30.0000")))
    s = fs.build_appropriation(firm_ledgers(), ctx(EntityType.PARTNERSHIP, NONE_STOCK, bad))
    assert [f.rule_id for f in s.findings if f.severity == "error"] == ["F-62"]
    assert "share:A" not in amounts(s.left)
    bs = fs.build_balance_sheet(firm_ledgers(), ctx(EntityType.PARTNERSHIP, NONE_STOCK, bad), StatementFormat.HORIZONTAL)
    assert "F-62" in [f.rule_id for f in bs.findings] and bs.totals["total_assets"] == bs.totals["total_liabilities"]


def test_F61_a_partnership_without_partners_is_blocked():
    s = fs.build_appropriation(firm_ledgers(), ctx(EntityType.PARTNERSHIP, NONE_STOCK, ()))
    assert [f.rule_id for f in s.findings if f.severity == "error"] == ["F-61"]


def test_F44b_partnership_balance_sheet_adds_each_partners_share_of_profit():
    s = fs.build_balance_sheet(firm_ledgers(), ctx(EntityType.PARTNERSHIP, NONE_STOCK, PARTNERS), StatementFormat.HORIZONTAL)
    a = amounts(s.left)
    assert a["ledger:capA"] == D("390000.00") and a["ledger:capB"] == D("220000.00")
    assert a["share:A"] == D("84000.00") and a["share:B"] == D("56000.00") and a["total"] == D("750000.00")
    assert amounts(s.right) == {"bank_accounts": D("750000.00"), "total": D("750000.00")} and s.findings == ()


def test_F47_company_is_refused_by_the_non_company_statements():
    with pytest.raises(ValueError):
        fs.build_trading(mini_ledgers(), ctx(EntityType.COMPANY))


def test_F43_appropriation_is_only_for_partnership_and_llp():
    with pytest.raises(ValueError):
        fs.build_appropriation(mini_ledgers(), ctx())


def test_F40_ledger_positions_read_the_trial_balance_and_ignore_drafts_and_later_dates():
    from app.engine.models import Group, Ledger, OpeningBalance, PostedLine

    groups = {"capital_account": Group("capital_account", "Capital Account", "liability", "balance_sheet"),
              "current_assets": Group("current_assets", "Current Assets", "asset", "balance_sheet"),
              "bank_accounts": Group("bank_accounts", "Bank Accounts", "asset", "balance_sheet", "current_assets")}
    ledgers = [Ledger("cap", "Capital", "capital_account", True, "c"), Ledger("bank", "Bank", "bank_accounts", True, "c")]
    openings = {"cap": OpeningBalance(D("0.00"), D("1000.00")), "bank": OpeningBalance(D("1000.00"), D("0.00"))}

    def line(vid, status, ledger, dr, cr, on=date(2026, 5, 1)):
        return PostedLine(vid, "N", "journal", on, "n", status, 1, ledger, ledger, D(dr), D(cr))

    lines = [line("v1", "posted", "bank", "500.00", "0.00"), line("v1", "posted", "cap", "0.00", "500.00"),
             line("v2", "draft", "bank", "999.00", "0.00"), line("v3", "posted", "bank", "0.00", "200.00", date(2027, 2, 1)),
             line("v3", "posted", "cap", "200.00", "0.00", date(2027, 2, 1))]
    out = fs.ledger_positions(ledgers, groups, openings, lines, date(2026, 12, 31), {"cap": "x"})
    bank = next(x for x in out if x.ledger_id == "bank")
    assert (bank.opening, bank.debit_total, bank.credit_total, bank.closing) == (D("1000.00"), D("500.00"), D("0.00"), D("1500.00"))
    assert bank.parent_group_code == "current_assets" and bank.nature == "asset"
    cap = next(x for x in out if x.ledger_id == "cap")
    assert (cap.closing, cap.role, cap.parent_group_code) == (D("-1500.00"), "x", None)
