"""Phase 6 package F: year-end closing vouchers, partners' shares, carry-forward, open bills and stock carry (F-60..F-66).

Every expected figure is hand-calculated from the plan's worked mini-example (re-derived here):
  Trading closing voucher: Dr Sales 12,00,000 + Dr Stock 50,000 (closing 2,50,000 less opening 2,00,000) = 12,50,000;
                           Cr Purchases 8,00,000 + Freight 30,000 + Trading A/c 4,20,000 = 12,50,000.
  P&L voucher: Dr Trading A/c 4,20,000 + Interest Income 5,000 = 4,25,000; Cr Salary 1,20,000 + Rent 65,000 + Electricity 18,000 +
               Depreciation 10,000 + Bad Debts 10,000 + Provision Expense 12,000 = 2,35,000, P&L A/c 1,90,000: total 4,25,000.
  Appropriation (proprietor): Dr P&L 1,90,000; Cr Drawings 1,00,000; Cr Capital 90,000.
  Carry: Dr Furniture 1,00,000 + Stock 2,50,000 + Debtors 2,40,000 + Prepaid 2,000 + Cash 25,000 + Bank 1,80,000 = 7,97,000;
         Cr Capital 5,90,000 + Loan 20,000 + Creditors 1,60,000 + Outstanding 5,000 + Provision 12,000 + Acc. Depreciation 10,000 = 7,97,000.
"""

from datetime import date
from decimal import Decimal

from app.engine import final_close as fc
from app.engine.final_types import ClosingStockIn, EntityType, LedgerBalanceIn, PartnerShare

D = Decimal
FROM, TO = date(2026, 4, 1), date(2027, 3, 31)


def L(lid, name, group, nature, closing, *, opening="0", parent=None, role=None, dr="0", cr="0"):
    return LedgerBalanceIn(lid, name, group, parent, nature, D(opening), D(dr), D(cr), D(closing), role=role)


def mini():
    return [
        L("stock", "Opening Stock", "stock_in_hand", "asset", "200000", opening="200000", parent="current_assets", role="stock_ledger"),
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
        L("prov", "Provision for Doubtful Debts", "provisions", "liability", "-12000", role="provision_doubtful_debts", parent="current_liabilities"),
        L("sales", "Sales", "sales_accounts", "income", "-1200000"),
        L("int", "Interest Income", "indirect_incomes", "income", "-5000"),
        L("tr", "Trading A/c", "reserves_and_surplus", "liability", "0", role="trading_account", parent="capital_account"),
        L("pl", "Profit and Loss A/c", "reserves_and_surplus", "liability", "0", role="profit_and_loss", parent="capital_account"),
    ]


STOCK = ClosingStockIn(D("260000"), D("10000"), D("250000"), "inventory_report", TO)


def ctx(entity=EntityType.PROPRIETORSHIP, stock=STOCK, partners=()):
    return fc.CloseContext(entity, FROM, TO, "2026-27", stock, tuple(partners))


def n(value):
    """2-decimal Decimal as a plain literal: 1200000.00 -> '1200000'."""
    return format(value.normalize(), "f")


def lines_of(draft):
    return [(x.ledger_id, n(x.debit), n(x.credit)) for x in draft.lines]


def test_F63_trading_voucher_of_the_mini_example():
    plan = fc.build_closing_plan(mini(), ctx())
    assert plan.errors == ()
    v = plan.vouchers[0]
    assert (v.step, v.voucher_date, v.reference_no) == ("trading", TO, "YEC/2026-27/trading")
    assert lines_of(v) == [("sales", "1200000", "0"), ("stock", "50000", "0"),
                           ("pur", "0", "800000"), ("frt", "0", "30000"), ("tr", "0", "420000")]
    assert plan.gross_profit == D("420000")


def test_F63_profit_and_loss_voucher_of_the_mini_example():
    plan = fc.build_closing_plan(mini(), ctx())
    v = plan.vouchers[1]
    assert (v.step, v.reference_no) == ("profit_loss", "YEC/2026-27/profit_loss")
    assert lines_of(v) == [("tr", "420000", "0"), ("int", "5000", "0"),
                           ("bad", "0", "10000"), ("dep", "0", "10000"), ("elec", "0", "18000"), ("pexp", "0", "12000"),
                           ("rent", "0", "65000"), ("sal", "0", "120000"), ("pl", "0", "190000")]
    assert plan.net_profit == D("190000") and plan.balance_to_transfer == D("190000")


def test_F63_proprietor_appropriation_closes_drawings_to_capital():
    plan = fc.build_closing_plan(mini(), ctx())
    v = plan.vouchers[2]
    assert v.step == "appropriation"
    assert lines_of(v) == [("pl", "190000", "0"), ("draw", "0", "100000"), ("cap", "0", "90000")]
    assert [(name, n(a)) for _, name, a in plan.appropriation] == [("Drawings", "100000"), ("Capital", "90000")]


def test_F63_every_closing_voucher_balances_and_is_dated_the_year_end():
    for v in fc.build_closing_plan(mini(), ctx()).vouchers:
        assert sum(x.debit for x in v.lines) == sum(x.credit for x in v.lines)
        assert v.voucher_date == TO and v.narration.startswith("Year-end closing entry")


def test_F65_carry_forward_of_the_mini_example_dr_equals_cr():
    plan = fc.build_closing_plan(mini(), ctx())
    rows = {lid: (n(d), n(c)) for lid, d, c in plan.carry.ledger_openings}
    assert rows == {"fur": ("100000", "0"), "stock": ("250000", "0"), "debt": ("240000", "0"), "pre": ("2000", "0"),
                    "cash": ("25000", "0"), "bank": ("180000", "0"), "cap": ("0", "590000"), "loan": ("0", "20000"),
                    "cred": ("0", "160000"), "out": ("0", "5000"), "prov": ("0", "12000"), "acc": ("0", "10000")}
    assert plan.carry.total_debit == D("797000") and plan.carry.total_credit == D("797000")


def test_F65_unbalanced_books_carry_nothing_and_show_the_difference():
    books = mini()
    books[16] = L("cap", "Capital", "capital_account", "liability", "-499000", opening="-500000")   # a 1,000 difference
    plan = fc.build_closing_plan(books, ctx())
    assert plan.carry is None
    messages = [f.message for f in plan.errors if f.rule_id == "F-65"]
    assert len(messages) == 1 and "1,000.00" in messages[0] and "Nothing is carried" in messages[0]


def test_F41_missing_closing_stock_blocks_and_creates_no_voucher():
    plan = fc.build_closing_plan(mini(), ctx(stock=None))
    assert plan.vouchers == () and [f.rule_id for f in plan.errors] == ["F-41"]


def test_F02_missing_clearing_roles_block():
    books = [x for x in mini() if x.role not in ("trading_account", "profit_and_loss")]
    plan = fc.build_closing_plan(books, ctx())
    assert plan.vouchers == () and [f.rule_id for f in plan.errors] == ["F-02", "F-02"]


def test_F60_clearing_ledger_must_be_nil_before_the_close():
    books = mini()
    books[23] = L("tr", "Trading A/c", "reserves_and_surplus", "liability", "-1000", role="trading_account", parent="capital_account")
    plan = fc.build_closing_plan(books, ctx())
    assert [f.rule_id for f in plan.errors] == ["F-60"] and "1,000.00 Cr" in plan.errors[0].message


def test_F60_a_stock_ledger_with_entries_blocks():
    books = mini()
    books[0] = L("stock", "Opening Stock", "stock_in_hand", "asset", "210000", opening="200000", parent="current_assets", role="stock_ledger", dr="10000")
    plan = fc.build_closing_plan(books, ctx())
    assert plan.errors[0].rule_id == "F-60"


def test_F63_proprietor_loss_year_debits_capital_with_loss_and_drawings():
    books = mini()
    books[21] = L("sales", "Sales", "sales_accounts", "income", "-300000")     # sales 3,00,000
    plan = fc.build_closing_plan(books, ctx())
    # gross: Cr 3,00,000 + 2,50,000 = 5,50,000; Dr 2,00,000 + 8,00,000 + 30,000 = 10,30,000: gross loss 4,80,000
    assert plan.gross_profit == D("-480000")
    # net: -4,80,000 + 5,000 - 2,35,000 = -7,10,000
    assert plan.net_profit == D("-710000")
    assert lines_of(plan.vouchers[2]) == [("draw", "0", "100000"), ("cap", "810000", "0"), ("pl", "0", "710000")] or \
        lines_of(plan.vouchers[2]) == [("cap", "810000", "0"), ("pl", "0", "710000"), ("draw", "0", "100000")]


def test_F63_proprietor_needs_exactly_one_capital_ledger():
    books = mini() + [L("cap2", "Capital 2", "capital_account", "liability", "0")]
    plan = fc.build_closing_plan(books, ctx())
    assert [f.rule_id for f in plan.errors] == ["F-60"] and "exactly one" in plan.errors[0].message


# ---------------------------------------------------------------------------------------------- partnership (F-61, F-62)


def firm_books():
    """Net profit before appropriation 2,50,000; interest on capital 50,000 (A 30,000 + B 20,000, already credited to the partners),
    remuneration 60,000 (A): balance 1,40,000 shared 3:2 -> A 84,000, B 56,000."""
    return [
        L("sales", "Sales", "sales_accounts", "income", "-1000000"),
        L("pur", "Purchases", "purchase_accounts", "expense", "400000"),
        L("exp", "Expenses", "indirect_expenses", "expense", "350000"),
        L("ioc", "Interest on Capital", "indirect_expenses", "expense", "50000", role="interest_on_capital"),
        L("rem", "Partner Remuneration", "indirect_expenses", "expense", "60000", role="partner_remuneration"),
        L("a", "Capital A", "capital_account", "liability", "-390000", opening="-300000"),
        L("b", "Capital B", "capital_account", "liability", "-220000", opening="-200000"),
        L("bank", "Bank", "bank_accounts", "asset", "750000", opening="500000", parent="current_assets"),
        L("tr", "Trading A/c", "reserves_and_surplus", "liability", "0", role="trading_account", parent="capital_account"),
        L("pl", "Profit and Loss A/c", "reserves_and_surplus", "liability", "0", role="profit_and_loss", parent="capital_account"),
    ]


PARTNERS = (PartnerShare("pa", "A", "a", D("60.0000")), PartnerShare("pb", "B", "b", D("40.0000")))
NO_STOCK = ClosingStockIn(D("0"), D("0"), D("0"), "none", TO)


def test_F62_partnership_balance_is_shared_in_the_ratio():
    books = firm_books()
    plan = fc.build_closing_plan(books, ctx(EntityType.PARTNERSHIP, NO_STOCK, PARTNERS))
    assert plan.net_profit == D("250000") and plan.balance_to_transfer == D("140000")
    assert lines_of(plan.vouchers[2]) == [("pl", "140000", "0"), ("a", "0", "84000"), ("b", "0", "56000")]
    assert [(name, str(a)) for _, name, a in plan.appropriation] == [("A", "84000.00"), ("B", "56000.00")]


def test_F62_last_partner_takes_the_rounding_remainder():
    shares, findings = fc.share_profit(D("100000.01"), (PartnerShare("pa", "A", "a", D("50.0000")), PartnerShare("pb", "B", "b", D("50.0000"))))
    assert findings == [] and [(p.name, str(s)) for p, s in shares] == [("A", "50000.01"), ("B", "50000.00")]
    shares, _ = fc.share_profit(D("100001.00"), PARTNERS)
    assert [str(s) for _, s in shares] == ["60000.60", "40000.40"]


def test_F62_shares_not_100_block_the_close():
    bad = (PartnerShare("pa", "A", "a", D("60.0000")), PartnerShare("pb", "B", "b", D("30.0000")))
    plan = fc.build_closing_plan(firm_books(), ctx(EntityType.PARTNERSHIP, NO_STOCK, bad))
    assert [f.rule_id for f in plan.errors] == ["F-62"] and "90.0000" in plan.errors[0].message


def test_F61_a_firm_without_partner_shares_is_blocked():
    plan = fc.build_closing_plan(firm_books(), ctx(EntityType.LLP, NO_STOCK, ()))
    assert [f.rule_id for f in plan.errors] == ["F-61"]


def test_F63_a_firm_loss_is_shared_as_a_loss():
    books = firm_books()
    books[0] = L("sales", "Sales", "sales_accounts", "income", "-700000")    # (bank 4,50,000 keeps the books balanced) net before: 7,00,000 - 4,00,000 - 3,50,000 = -50,000; balance -1,60,000
    books[7] = L("bank", "Bank", "bank_accounts", "asset", "450000", parent="current_assets")
    plan = fc.build_closing_plan(books, ctx(EntityType.PARTNERSHIP, NO_STOCK, PARTNERS))
    assert plan.balance_to_transfer == D("-160000")
    assert lines_of(plan.vouchers[2]) == [("a", "96000", "0"), ("b", "64000", "0"), ("pl", "0", "160000")]


# ---------------------------------------------------------------------------------------------- company


def test_F63_company_profit_goes_to_surplus_in_pl():
    books = mini() + [L("sur", "Surplus", "reserves_and_surplus", "liability", "0", role="surplus_in_pl", parent="capital_account")]
    plan = fc.build_closing_plan(books, ctx(EntityType.COMPANY))
    assert lines_of(plan.vouchers[2]) == [("pl", "190000", "0"), ("sur", "0", "190000")]


def test_F02_company_without_a_surplus_ledger_is_blocked():
    plan = fc.build_closing_plan(mini(), ctx(EntityType.COMPANY))
    assert [f.rule_id for f in plan.errors] == ["F-02"] and "surplus_in_pl" in plan.errors[0].message


def test_F63_a_year_with_nothing_to_move_creates_no_vouchers():
    quiet = [L("bank", "Bank", "bank_accounts", "asset", "0"), L("tr", "T", "reserves_and_surplus", "liability", "0", role="trading_account"),
             L("pl", "P", "reserves_and_surplus", "liability", "0", role="profit_and_loss")]
    plan = fc.build_closing_plan(quiet, ctx(EntityType.PROPRIETORSHIP, NO_STOCK))
    assert plan.vouchers == () and plan.carry.ledger_openings == ()


# ---------------------------------------------------------------------------------------------- open bills and stock (F-66)


def test_F66_open_bills_carry_with_reference_dates_and_amount_and_tie_to_the_ledger():
    items = [fc.OpenItem("p1", "Mr A", "INV-7", date(2027, 2, 1), date(2027, 3, 3), D("150000")),
             fc.OpenItem("p1", "Mr A", "INV-9", date(2027, 3, 1), date(2027, 3, 31), D("90000")),
             fc.OpenItem("p2", "Supplier", None, date(2027, 1, 5), date(2027, 1, 5), D("-4000"))]
    bills, findings = fc.carry_open_bills(items, {"p1": "Mr A", "p2": "Supplier"}, {"p1": D("240000"), "p2": D("-4000")})
    assert findings == []
    assert [(b.party_ledger_id, b.bill_ref, str(b.amount)) for b in bills] == [("p1", "INV-7", "150000"), ("p1", "INV-9", "90000"), ("p2", "On account", "-4000")]


def test_F66_open_bills_that_do_not_tie_to_the_party_balance_block():
    items = [fc.OpenItem("p1", "Mr A", "INV-7", date(2027, 2, 1), date(2027, 3, 3), D("150000"))]
    _, findings = fc.carry_open_bills(items, {"p1": "Mr A"}, {"p1": D("240000")})
    assert len(findings) == 1 and "90,000.00" in findings[0].message and findings[0].rule_id == "F-66"


def test_F66_a_balance_without_any_open_bill_blocks_and_duplicate_reference_blocks():
    _, findings = fc.carry_open_bills([], {"p1": "Mr A"}, {"p1": D("500")})
    assert len(findings) == 1
    twice = [fc.OpenItem("p1", "Mr A", "X", date(2027, 2, 1), date(2027, 2, 1), D("5")), fc.OpenItem("p1", "Mr A", "x", date(2027, 2, 2), date(2027, 2, 2), D("5"))]
    _, findings = fc.carry_open_bills(twice, {"p1": "Mr A"}, {"p1": D("10")})
    assert "two open items" in findings[0].message


def test_F66_stock_value_is_spread_over_godowns_by_quantity_last_takes_remainder():
    # 1,000.01 over quantities 1:2 -> 333.34 (1/3 of 1,000.01 = 333.3366.. rounds to 333.34), remainder 666.67
    assert [str(v) for v in fc.spread_over_godowns(D("1000.01"), [D("1"), D("2")])] == ["333.34", "666.67"]
    assert [str(v) for v in fc.spread_over_godowns(D("100.00"), [D("5")])] == ["100.00"]


def test_F66_stock_carries_per_item_and_godown_and_must_match_the_approved_figure():
    items = [fc.StockItemIn("i1", "Widget", D("30"), D("2250.00"), (("g1", D("10")), ("g2", D("20")))),
             fc.StockItemIn("i2", "Gadget", D("4"), D("250.00"), (("g1", D("4")),)),
             fc.StockItemIn("i3", "Sold out", D("0"), D("0.00"), ())]
    out, findings = fc.carry_stock(items, D("2500.00"))
    assert findings == []
    assert [(c.item_id, c.godown_id, str(c.quantity), str(c.value)) for c in out] == [
        ("i1", "g1", "10", "750.00"), ("i1", "g2", "20", "1500.00"), ("i2", "g1", "4", "250.00")]
    _, findings = fc.carry_stock(items, D("2600.00"))
    assert len(findings) == 1 and "2,600.00" in findings[0].message
