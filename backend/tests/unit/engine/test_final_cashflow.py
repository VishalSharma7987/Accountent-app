"""Package E: Cash Flow Statement, AS 3 indirect (F-49, F-50). Pure engine, no database.

Every expected value is typed literally; the first case is the Phase 6 plan's worked mini-example (re-derived by hand:
net profit 1,90,000 + depreciation 10,000 - interest income 5,000 = 1,95,000; inventories -50,000; debtors net -78,000; prepaid -2,000;
creditors +80,000; outstanding expenses +5,000 = 1,50,000 from operations; investing +5,000; financing -1,00,000; net 55,000;
cash 1,50,000 -> 2,05,000).
"""

from datetime import date
from decimal import Decimal

from app.engine import final_cashflow as cf
from app.engine.final_types import ClosingStockIn, EntityType, Finding, LedgerBalanceIn

D = Decimal
FY = (date(2026, 4, 1), date(2027, 3, 31))


def L(name, group, nature, opening, closing, *, parent=None, role=None, cf_class=None, line_code=None):
    return LedgerBalanceIn(name, name, group, parent, nature, D(opening), D("0"), D("0"), D(closing),
                           role=role, cf_class=cf_class, line_code=line_code)


def ctx(stock=None, *, required=False, entity=EntityType.PROPRIETORSHIP):
    return cf.CashFlowContext(entity, FY[0], FY[1], stock, {}, required)


def stock_in(carrying):
    return ClosingStockIn(D(carrying), D("0"), D(carrying), "manual", FY[1])


def by_code(statement):
    return {x.code: x for x in statement.left}


def mini_example():
    return [
        L("Opening Stock", "stock_in_hand", "asset", "200000", "200000", parent="current_assets"),
        L("Furniture", "fixed_assets", "asset", "100000", "100000"),
        L("Accumulated Depreciation", "fixed_assets", "asset", "0", "-10000", role="accumulated_depreciation"),
        L("Sundry Debtors", "sundry_debtors", "asset", "150000", "240000", parent="current_assets"),
        L("Provision for Doubtful Debts", "provisions", "liability", "0", "-12000", parent="current_liabilities",
          role="provision_doubtful_debts"),
        L("Prepaid Expenses", "current_assets", "asset", "0", "2000"),
        L("Cash", "cash_in_hand", "asset", "30000", "25000", parent="current_assets"),
        L("Bank", "bank_accounts", "asset", "120000", "180000", parent="current_assets"),
        L("Capital", "capital_account", "liability", "-500000", "-500000"),
        L("Drawings", "capital_account", "liability", "0", "100000"),
        L("Loan", "loans_liability", "liability", "-20000", "-20000"),
        L("Sundry Creditors", "sundry_creditors", "liability", "-80000", "-160000", parent="current_liabilities"),
        L("Outstanding Expenses", "current_liabilities", "liability", "0", "-5000"),
        L("Purchases", "purchase_accounts", "expense", "0", "800000"),
        L("Freight", "direct_expenses", "expense", "0", "30000"),
        L("Salary", "indirect_expenses", "expense", "0", "120000"),
        L("Rent", "indirect_expenses", "expense", "0", "65000"),
        L("Electricity", "indirect_expenses", "expense", "0", "18000"),
        L("Depreciation", "indirect_expenses", "expense", "0", "10000", role="depreciation_expense"),
        L("Bad Debts", "indirect_expenses", "expense", "0", "10000"),
        L("Provision Expense", "indirect_expenses", "expense", "0", "12000"),
        L("Sales", "sales_accounts", "income", "0", "-1200000"),
        L("Interest Income", "indirect_incomes", "income", "0", "-5000", cf_class="investing"),
    ]


def test_F49_plan_mini_example_sections():
    s = cf.build_cash_flow(mini_example(), D("190000"), ctx(stock_in("250000")))
    t = s.totals
    assert t["cash_from_operations"] == D("150000")
    assert t["investing"] == D("5000")
    assert t["financing"] == D("-100000")
    assert t["net_increase"] == D("55000")
    assert t["opening_cash"] == D("150000")
    assert t["closing_cash"] == D("205000")
    assert t["balance_sheet_cash"] == D("205000")
    assert t["difference"] == D("0")
    assert [f for f in s.findings if f.severity == "error"] == []


def test_F49_plan_mini_example_lines():
    s = cf.build_cash_flow(mini_example(), D("190000"), ctx(stock_in("250000")))
    lines = by_code(s)
    assert lines["net_profit"].amount == D("190000")
    assert lines["adj_pl:Interest Income"].amount == D("-5000")      # interest income moved to investing
    assert lines["non_cash"].amount == D("10000")                    # depreciation add-back (accumulated depreciation)
    assert lines["operating_before_wc"].amount == D("195000")
    assert lines["wc:stock_in_hand"].amount == D("-50000")
    assert lines["wc:sundry_debtors"].amount == D("-78000")
    assert lines["wc:current_assets"].amount == D("-2000")
    assert lines["wc:sundry_creditors"].amount == D("80000")
    assert lines["wc:current_liabilities"].amount == D("5000")
    assert lines["inv_pl:Interest Income"].amount == D("5000")
    assert lines["fin:capital_account"].amount == D("-100000")
    assert "fin:loans_liability" not in lines                        # loan unchanged: no line
    assert [d.ledger_name for d in lines["fin:capital_account"].drill] == ["Drawings"]
    assert [d.ledger_name for d in lines["non_cash"].drill] == ["Accumulated Depreciation"]


def test_F50_mismatch_is_error_when_required_and_warning_otherwise():
    broken = [x if x.name != "Bank" else L("Bank", "bank_accounts", "asset", "120000", "170000", parent="current_assets")
              for x in mini_example()]
    required = cf.build_cash_flow(broken, D("190000"), ctx(stock_in("250000"), required=True))
    f50 = [f for f in required.findings if f.rule_id == "F-50"]
    assert [f.severity for f in f50] == ["error"]
    assert "10,000.00" in f50[0].message
    assert required.totals["difference"] == D("10000")
    optional = cf.build_cash_flow(broken, D("190000"), ctx(stock_in("250000"), required=False))
    assert [f.severity for f in optional.findings if f.rule_id == "F-50"] == ["warning"]


def test_F41_closing_stock_missing_with_stock_is_error():
    s = cf.build_cash_flow(mini_example(), D("190000"), ctx(None))
    assert [f.rule_id for f in s.findings if f.severity == "error"].count("F-41") == 1


def test_F49_financing_expense_and_investing_purchase():
    ledgers = [
        L("Cash", "cash_in_hand", "asset", "10000", "47000", parent="current_assets"),
        L("Capital", "capital_account", "liability", "-10000", "-10000"),
        L("Loan", "loans_liability", "liability", "0", "-20000"),
        L("Machinery", "fixed_assets", "asset", "0", "30000"),
        L("Sales", "sales_accounts", "income", "0", "-50000"),
        L("Interest Paid", "indirect_expenses", "expense", "0", "3000", cf_class="financing"),
    ]
    s = cf.build_cash_flow(ledgers, D("47000"), ctx(None))
    lines = by_code(s)
    assert lines["adj_pl:Interest Paid"].amount == D("3000")
    assert s.totals["cash_from_operations"] == D("50000")
    assert lines["inv:fixed_assets"].amount == D("-30000")
    assert lines["fin:loans_liability"].amount == D("20000")
    assert lines["fin_pl:Interest Paid"].amount == D("-3000")
    assert s.totals["investing"] == D("-30000")
    assert s.totals["financing"] == D("17000")
    assert s.totals["net_increase"] == D("37000")
    assert s.totals["closing_cash"] == D("47000")
    assert [f for f in s.findings if f.severity == "error"] == []


def test_F49_tax_expense_shown_after_operations():
    ledgers = [
        L("Cash", "cash_in_hand", "asset", "10000", "55000", parent="current_assets"),
        L("Capital", "capital_account", "liability", "-10000", "-10000"),
        L("Sales", "sales_accounts", "income", "0", "-50000"),
        L("Income Tax", "indirect_expenses", "expense", "0", "5000", line_code="tax_expense"),
    ]
    s = cf.build_cash_flow(ledgers, D("50000"), ctx(None, entity=EntityType.COMPANY))
    lines = by_code(s)
    assert lines["cash_generated"].amount == D("50000")
    assert lines["tax"].amount == D("-5000")
    assert s.totals["cash_from_operations"] == D("45000")
    assert s.totals["net_increase"] == D("45000")
    assert s.totals["closing_cash"] == D("55000")


def test_F49_partnership_appropriation_is_non_cash():
    ledgers = [
        L("Cash", "cash_in_hand", "asset", "50000", "150000", parent="current_assets"),
        L("Partner A Capital", "capital_account", "liability", "-50000", "-50000"),
        L("Partner A Current", "capital_account", "liability", "0", "-10000"),
        L("Sales", "sales_accounts", "income", "0", "-100000"),
        L("Interest on Capital", "indirect_expenses", "expense", "0", "10000", role="interest_on_capital"),
    ]
    s = cf.build_cash_flow(ledgers, D("100000"), ctx(None, entity=EntityType.PARTNERSHIP))
    lines = by_code(s)
    assert lines["adj_appropriation"].amount == D("-10000")
    assert s.totals["cash_from_operations"] == D("90000")
    assert lines["fin:capital_account"].amount == D("10000")
    assert s.totals["net_increase"] == D("100000")
    assert s.totals["closing_cash"] == D("150000")


def test_F49_suspense_and_reserves_movement_warn():
    ledgers = [
        L("Cash", "cash_in_hand", "asset", "0", "300", parent="current_assets"),
        L("Suspense", "suspense", "liability", "0", "-100"),
        L("Reserve", "reserves_surplus", "liability", "0", "-200", parent="capital_account"),
    ]
    s = cf.build_cash_flow(ledgers, D("0"), ctx(None))
    warned = [f.message for f in s.findings if f.rule_id == "F-49" and f.severity == "warning"]
    assert len(warned) == 2
    assert s.totals["net_increase"] == D("300")


def test_F49_group_label_comes_from_context_labels():
    ledgers = [L("Cash", "cash_in_hand", "asset", "0", "10", parent="current_assets"),
               L("Trade", "sundry_creditors", "liability", "0", "-10", parent="current_liabilities", line_code="trade_payables")]
    c = cf.CashFlowContext(EntityType.COMPANY, FY[0], FY[1], None, {"trade_payables": "Trade payables"}, True)
    s = cf.build_cash_flow(ledgers, D("0"), c)
    assert by_code(s)["wc:trade_payables"].label == "Increase / (decrease) in Trade payables"


def test_F49_upstream_error_findings_are_carried():
    up = (Finding("F-44", "Ledger Z is not classified.", "error"), Finding("F-44", "just a warning", "warning"))
    s = cf.build_cash_flow(mini_example(), D("190000"), ctx(stock_in("250000")), up)
    assert [f.message for f in s.findings if f.rule_id == "F-44"] == ["Ledger Z is not classified."]
