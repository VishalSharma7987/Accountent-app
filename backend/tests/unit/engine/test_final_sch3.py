"""Schedule III engine (package D, rules F-44..F-46). Expected values are the hand-worked mini-example of docs/PHASE6_PLAN.md
(company, no drawings, extra 1,00,000 in bank), re-derived by hand: assets 90,000 + 2,50,000 + 2,28,000 + 3,05,000 + 2,000 = 8,75,000;
equity and liabilities 5,00,000 + 1,90,000 + 20,000 + 1,60,000 + 5,000 = 8,75,000; expenses 8,00,000 - 50,000 + 1,20,000 + 10,000
+ 1,35,000 = 10,15,000; profit before tax 12,05,000 - 10,15,000 = 1,90,000."""

from datetime import date
from decimal import Decimal as D

from app.engine.final_sch3 import (
    FsLineRule,
    GroupDefault,
    LedgerOverride,
    PpeRow,
    RegisterDepLine,
    RegisterEvent,
    Sch3Input,
    amounts_from_payload,
    amounts_of,
    build_ppe_rows,
    build_sch3,
    classify,
    statement_payload,
)
from app.engine.final_types import ClosingStockIn, LedgerBalanceIn

FY_FROM, FY_TO = date(2026, 4, 1), date(2027, 3, 31)


def rule(fmt, code, label, section, sort, note=None, cf="operating"):
    return FsLineRule(fmt, code, label, section, sort, note, cf, "pending", "seed 0013")


LINES = (
    rule("sch3_bs", "share_capital", "Share capital", "equity", 10, "Share capital"),
    rule("sch3_bs", "reserves_surplus", "Reserves and surplus", "equity", 20, "Reserves and surplus"),
    rule("sch3_bs", "long_term_borrowings", "Long-term borrowings", "non_current_liabilities", 30, "Long-term borrowings"),
    rule("sch3_bs", "trade_payables", "Trade payables", "current_liabilities", 80, "Trade payables"),
    rule("sch3_bs", "other_current_liabilities", "Other current liabilities", "current_liabilities", 90, "Other current liabilities"),
    rule("sch3_bs", "ppe", "Property, plant and equipment", "non_current_assets", 110, "Property, plant and equipment"),
    rule("sch3_bs", "inventories", "Inventories", "current_assets", 190, "Inventories"),
    rule("sch3_bs", "trade_receivables", "Trade receivables", "current_assets", 200, "Trade receivables"),
    rule("sch3_bs", "cash_and_cash_equivalents", "Cash and cash equivalents", "current_assets", 210, "Cash and cash equivalents"),
    rule("sch3_bs", "other_current_assets", "Other current assets", "current_assets", 230, "Other current assets"),
    rule("sch3_pl", "revenue_from_operations", "Revenue from operations", "income", 10, "Revenue from operations"),
    rule("sch3_pl", "other_income", "Other income", "income", 20, "Other income"),
    rule("sch3_pl", "purchases_stock_in_trade", "Purchases of stock-in-trade", "expenses", 40),
    rule("sch3_pl", "changes_in_inventories", "Changes in inventories", "expenses", 50),
    rule("sch3_pl", "employee_benefits_expense", "Employee benefits expense", "expenses", 60, "Employee benefits expense"),
    rule("sch3_pl", "depreciation_amortisation", "Depreciation and amortisation expense", "expenses", 80),
    rule("sch3_pl", "other_expenses", "Other expenses", "expenses", 90, "Other expenses"),
    rule("sch3_pl", "tax_expense", "Tax expense", "expenses", 100),
)

GROUP_DEFAULTS = (
    GroupDefault("capital_account", "sch3_bs", "share_capital", False),
    GroupDefault("reserves_surplus", "sch3_bs", "reserves_surplus", True),
    GroupDefault("sundry_creditors", "sch3_bs", "trade_payables", False),
    GroupDefault("provisions", "sch3_bs", "short_term_provisions", False),
    GroupDefault("fixed_assets", "sch3_bs", "ppe", False),
    GroupDefault("sundry_debtors", "sch3_bs", "trade_receivables", True),
    GroupDefault("bank_accounts", "sch3_bs", "cash_and_cash_equivalents", True),
    GroupDefault("cash_in_hand", "sch3_bs", "cash_and_cash_equivalents", True),
    GroupDefault("stock_in_hand", "sch3_bs", "inventories", True),
    GroupDefault("sales_accounts", "sch3_pl", "revenue_from_operations", True),
    GroupDefault("indirect_incomes", "sch3_pl", "other_income", True),
    GroupDefault("purchase_accounts", "sch3_pl", "purchases_stock_in_trade", False),
    GroupDefault("direct_expenses", "sch3_pl", "other_expenses", False),
    GroupDefault("indirect_expenses", "sch3_pl", "other_expenses", False),
)

NATURE = {"stock_in_hand": "asset", "purchase_accounts": "expense", "direct_expenses": "expense", "indirect_expenses": "expense",
          "fixed_assets": "asset", "sundry_debtors": "asset", "provisions": "liability", "cash_in_hand": "asset",
          "bank_accounts": "asset", "current_assets": "asset", "capital_account": "liability", "loans_liability": "liability",
          "sundry_creditors": "liability", "current_liabilities": "liability", "sales_accounts": "income", "indirect_incomes": "income"}

# name, group, opening, closing (signed, debit positive), override line
BOOKS = [
    ("Opening Stock", "stock_in_hand", "200000", "200000", None),
    ("Purchases", "purchase_accounts", "0", "800000", None),
    ("Freight", "direct_expenses", "0", "30000", None),
    ("Salary", "indirect_expenses", "0", "120000", "employee_benefits_expense"),
    ("Rent", "indirect_expenses", "0", "65000", None),
    ("Electricity", "indirect_expenses", "0", "18000", None),
    ("Depreciation", "indirect_expenses", "0", "10000", "depreciation_amortisation"),
    ("Bad Debts", "indirect_expenses", "0", "10000", None),
    ("Provision for Doubtful Debts Exp", "indirect_expenses", "0", "12000", None),
    ("Furniture", "fixed_assets", "100000", "100000", None),
    ("Accumulated Depreciation", "fixed_assets", "0", "-10000", None),
    ("Sundry Debtors", "sundry_debtors", "150000", "240000", None),
    ("Provision for Doubtful Debts", "provisions", "0", "-12000", "trade_receivables"),
    ("Cash", "cash_in_hand", "30000", "25000", None),
    ("Bank", "bank_accounts", "120000", "280000", None),
    ("Prepaid Expenses", "current_assets", "0", "2000", "other_current_assets"),
    ("Share Capital", "capital_account", "-500000", "-500000", None),
    ("Loan", "loans_liability", "-20000", "-20000", "long_term_borrowings"),
    ("Sundry Creditors", "sundry_creditors", "-80000", "-160000", None),
    ("Outstanding Expenses", "current_liabilities", "0", "-5000", "other_current_liabilities"),
    ("Sales", "sales_accounts", "0", "-1200000", None),
    ("Interest Income", "indirect_incomes", "0", "-5000", None),
]


def raw_ledgers(books=BOOKS):
    out = []
    for i, (name, group, opening, closing, _) in enumerate(books, start=1):
        c = D(closing)
        out.append(LedgerBalanceIn(
            ledger_id=f"L{i}", name=name, group_code=group, parent_group_code=None, nature=NATURE[group], opening=D(opening),
            debit_total=max(c, D(0)), credit_total=max(-c, D(0)), closing=c))
    return tuple(out)


def classified(books=BOOKS):
    overrides = {f"L{i}": LedgerOverride(b[4], None) for i, b in enumerate(books, start=1) if b[4]}
    return tuple(c.ledger for c in classify(raw_ledgers(books), overrides, GROUP_DEFAULTS, LINES))


STOCK = ClosingStockIn(D("260000.00"), D("10000.00"), D("250000.00"), "manual", FY_TO)


def run(ledgers=None, stock=STOCK, previous_bs=None, previous_pl=None, register=None, required=True):
    return build_sch3(Sch3Input(FY_FROM, FY_TO, ledgers if ledgers is not None else classified(), stock, required, LINES,
                                previous_bs, previous_pl, register))


def by_code(statement):
    return {ln.code: ln for ln in statement.left}


def test_F44_worked_example_balance_sheet_lines_and_totals():
    bs = run().balance_sheet
    lines = by_code(bs)
    assert lines["share_capital"].amount == D("500000.00")
    assert lines["reserves_surplus"].amount == D("190000.00")
    assert lines["long_term_borrowings"].amount == D("20000.00")
    assert lines["trade_payables"].amount == D("160000.00")
    assert lines["other_current_liabilities"].amount == D("5000.00")
    assert lines["total_equity_liabilities"].amount == D("875000.00")
    assert lines["ppe"].amount == D("90000.00")
    assert lines["inventories"].amount == D("250000.00")
    assert lines["trade_receivables"].amount == D("228000.00")
    assert lines["cash_and_cash_equivalents"].amount == D("305000.00")
    assert lines["other_current_assets"].amount == D("2000.00")
    assert lines["total_assets"].amount == D("875000.00")
    assert bs.totals["difference"] == D("0.00")
    assert lines["section_equity"].amount == D("690000.00")


def test_F44_worked_example_profit_and_loss():
    pl = run().profit_loss
    lines = by_code(pl)
    assert lines["revenue_from_operations"].amount == D("1200000.00")
    assert lines["other_income"].amount == D("5000.00")
    assert lines["purchases_stock_in_trade"].amount == D("800000.00")
    assert lines["changes_in_inventories"].amount == D("-50000.00")
    assert lines["employee_benefits_expense"].amount == D("120000.00")
    assert lines["depreciation_amortisation"].amount == D("10000.00")
    assert lines["other_expenses"].amount == D("135000.00")
    assert lines["total_expenses"].amount == D("1015000.00")
    assert lines["profit_before_tax"].amount == D("190000.00")
    assert lines["profit_for_year"].amount == D("190000.00")
    assert "tax_expense" not in lines


def test_F44_contra_ledgers_net_and_show_negative_drill():
    lines = by_code(run().balance_sheet)
    drill = {d.ledger_name: d.amount for d in lines["trade_receivables"].drill}
    assert drill == {"Sundry Debtors": D("240000.00"), "Provision for Doubtful Debts": D("-12000.00")}


def test_F46_notes_numbered_in_statement_order_with_ledger_breakup():
    result = run()
    lines = by_code(result.balance_sheet)
    assert [lines[c].note_no for c in ("share_capital", "reserves_surplus", "long_term_borrowings", "trade_payables",
                                       "other_current_liabilities", "ppe", "inventories", "trade_receivables",
                                       "cash_and_cash_equivalents", "other_current_assets")] == list(range(1, 11))
    pl_lines = by_code(result.profit_loss)
    assert [pl_lines[c].note_no for c in ("revenue_from_operations", "other_income", "employee_benefits_expense", "other_expenses")] \
        == [11, 12, 13, 14]
    notes = {n: (title, ls) for n, title, ls in result.balance_sheet.notes}
    assert notes[2][0] == "Reserves and surplus"
    assert [(ln.label, ln.amount) for ln in notes[2][1]] == [
        ("Surplus / (deficit) in the Statement of Profit and Loss for the year", D("190000.00")),
        ("Total (Reserves and surplus)", D("190000.00"))]
    assert [(ln.label, ln.amount) for ln in notes[9][1]] == [
        ("Cash", D("25000.00")), ("Bank", D("280000.00")), ("Total (Cash and cash equivalents)", D("305000.00"))]
    assert result.profit_loss.notes == result.balance_sheet.notes


def test_F46_inventories_note_shows_cost_and_ast2_write_down():
    notes = {n: ls for n, _, ls in run().balance_sheet.notes}
    assert [(ln.label, ln.amount) for ln in notes[7]] == [
        ("Closing stock at cost", D("260000.00")),
        ("Less: write-down to net realisable value (AS 2)", D("-10000.00")),
        ("Total (Inventories)", D("250000.00"))]


def test_F46_ppe_note_from_register_and_difference_warning():
    row = PpeRow("Furniture", D("100000.00"), D("0.00"), D("0.00"), D("0.00"), D("10000.00"), D("0.00"))
    result = run(register=(row,))
    notes = {n: ls for n, _, ls in result.balance_sheet.notes}
    amounts = {ln.code: ln.amount for ln in notes[6]}
    assert amounts["ppe_gross_closing"] == D("100000.00")
    assert amounts["ppe_acc_closing"] == D("10000.00")
    assert amounts["ppe_net_block"] == D("90000.00")
    assert not [f for f in result.balance_sheet.findings if f.rule_id == "F-46"]
    other = PpeRow("Furniture", D("100000.00"), D("0.00"), D("0.00"), D("0.00"), D("9000.00"), D("0.00"))
    findings = [f for f in run(register=(other,)).balance_sheet.findings if f.rule_id == "F-46"]
    assert len(findings) == 1 and "1,000.00" in findings[0].message and findings[0].severity == "warning"


def test_F44_unclassified_ledger_is_an_error_not_a_default():
    books = [b if b[0] != "Prepaid Expenses" else (*b[:4], None) for b in BOOKS]
    result = run(classified(books))
    errors = [f for f in result.balance_sheet.findings if f.rule_id == "F-44" and f.severity == "error"]
    assert len(errors) == 1 and "Prepaid Expenses" in errors[0].message and errors[0].ledger_id == "L16"
    assert result.unclassified == ("L16",)
    assert result.balance_sheet.totals["difference"] == D("-2000.00")  # the unclassified 2,000 is left out, never guessed


def test_F44_group_default_gives_warning_listing_the_ledger_firm_default_does_not():
    result = run()
    warned = {f.ledger_id for f in result.balance_sheet.findings if f.rule_id == "F-44" and f.severity == "warning"}
    # Purchases (L2), Freight (L3), Rent (L5), Electricity (L6), Bad Debts (L8), Prov exp (L9), Furniture (L10), Acc dep (L11),
    # Share Capital (L17), Creditors (L19) are non-firm defaults; Sales, Cash, Bank, Debtors are firm
    assert warned == {"L2", "L3", "L5", "L6", "L8", "L9", "L10", "L11", "L17", "L19"}
    assert not [f for f in result.balance_sheet.findings if f.severity == "error"]


def test_F44_ledger_without_any_activity_needs_no_classification():
    idle = LedgerBalanceIn("X", "Idle Loan", "loans_liability", None, "liability", D(0), D(0), D(0), D(0))
    result = run(classified() + (idle,))
    assert not [f for f in result.balance_sheet.findings if f.severity == "error"]


def test_F44b_balance_sheet_that_does_not_balance_is_an_error():
    books = [b if b[0] != "Opening Stock" else (b[0], b[1], b[2], "210000", None) for b in BOOKS]
    books = [b if b[0] != "Sundry Creditors" else (b[0], b[1], b[2], "-170000", None) for b in books]
    result = run(classified(books))
    errors = [f for f in result.balance_sheet.findings if f.rule_id == "F-44b"]
    assert len(errors) == 1 and errors[0].severity == "error"
    assert "10,000.00" in errors[0].message
    assert result.balance_sheet.totals["difference"] == D("-10000.00")


def test_F40_unbalanced_books_block_the_statements():
    books = [b if b[0] != "Cash" else (b[0], b[1], b[2], "26000", None) for b in BOOKS]
    result = run(classified(books))
    messages = [f.message for f in result.balance_sheet.findings if f.rule_id == "F-40"]
    assert messages == ["Trial Balance: Debit 19,13,000.00 and Credit 19,12,000.00 are not equal (difference 1,000.00)."]


def test_F40_opening_balances_must_balance():
    books = [b if b[0] != "Cash" else (b[0], b[1], "31000", b[3], None) for b in BOOKS]
    messages = [f.message for f in run(classified(books)).balance_sheet.findings if f.rule_id == "F-40"]
    assert messages == ["Opening balances of the year: Debit 6,01,000.00 and Credit 6,00,000.00 are not equal (difference 1,000.00)."]


def test_F41_closing_stock_missing_is_an_error_for_trading_but_not_for_service():
    trading = run(stock=None)
    assert [f.rule_id for f in trading.balance_sheet.findings if f.severity == "error" and f.rule_id == "F-41"] == ["F-41"]
    service = run(stock=None, required=False)
    assert not [f for f in service.balance_sheet.findings if f.rule_id == "F-41"]


def test_F45_first_year_comparatives_are_dash_with_warning():
    result = run()
    assert by_code(result.balance_sheet)["ppe"].previous_amount is None
    for stmt in (result.balance_sheet, result.profit_loss):
        warning = [f for f in stmt.findings if f.rule_id == "F-45"]
        assert len(warning) == 1 and warning[0].severity == "warning"


def test_F45_previous_year_amounts_by_line_code_and_missing_line_is_zero():
    result = run(previous_bs={"ppe": D("100000.00"), "total_assets": D("700000.00"), "other_current_assets": D("500.00"),
                              "short_term_loans_advances": D("1.00")},
                 previous_pl={"revenue_from_operations": D("900000.00")})
    lines = by_code(result.balance_sheet)
    assert lines["ppe"].previous_amount == D("100000.00")
    assert lines["total_assets"].previous_amount == D("700000.00")
    assert lines["inventories"].previous_amount == D("0.00")
    assert by_code(result.profit_loss)["revenue_from_operations"].previous_amount == D("900000.00")
    assert not [f for f in result.balance_sheet.findings if f.rule_id == "F-45"]


def test_F45_line_with_only_previous_amount_still_shown():
    books = [b for b in BOOKS if b[0] != "Prepaid Expenses"]
    books = [b if b[0] != "Bank" else (b[0], b[1], b[2], "282000", None) for b in books]
    result = run(classified(books), previous_bs={"other_current_assets": D("700.00")})
    line = by_code(result.balance_sheet)["other_current_assets"]
    assert line.amount == D("0.00") and line.previous_amount == D("700.00")


def test_F43_loss_year_reduces_reserves_and_tax_expense_follows_profit_before_tax():
    books = [b for b in BOOKS if b[0] != "Sales"]
    books += [("Sales", "sales_accounts", "0", "-1000000", None), ("Income Tax", "indirect_expenses", "0", "0", None)]
    books = [b if b[0] != "Bank" else (b[0], b[1], b[2], "80000", None) for b in books]
    result = run(classified(books))
    lines = by_code(result.profit_loss)
    # revenue 10,00,000 + other 5,000 - expenses 10,15,000 = -10,000
    assert lines["profit_before_tax"].amount == D("-10000.00")
    assert by_code(result.balance_sheet)["reserves_surplus"].amount == D("-10000.00")


def test_F44_tax_expense_line_reduces_profit_for_the_year():
    tax_line = ("Provision for Tax", "indirect_expenses", "0", "20000", "tax_expense")
    books = [b if b[0] != "Bank" else (b[0], b[1], b[2], "260000", None) for b in BOOKS] + [tax_line]
    result = run(classified(books))
    lines = by_code(result.profit_loss)
    assert lines["profit_before_tax"].amount == D("190000.00")
    assert lines["tax_expense"].amount == D("20000.00")
    assert lines["profit_for_year"].amount == D("170000.00")
    assert by_code(result.balance_sheet)["reserves_surplus"].amount == D("170000.00")
    assert result.balance_sheet.totals["difference"] == D("0.00")


def test_F44_classify_override_beats_group_and_parent_group_is_used_for_own_subgroups():
    sub = LedgerBalanceIn("S", "Local Creditors", "my_creditors", "sundry_creditors", "liability", D(0), D(0), D(5), D(-5))
    loan = LedgerBalanceIn("N", "Bank Loan", "loans_liability", None, "liability", D(0), D(0), D(5), D(-5))
    ledgers = (sub, loan)
    out = {c.ledger.ledger_id: c for c in classify(ledgers, {}, GROUP_DEFAULTS, LINES)}
    assert (out["S"].ledger.line_code, out["S"].source, out["S"].ledger.line_is_default) == ("trade_payables", "group_default", True)
    assert (out["N"].ledger.line_code, out["N"].source) == (None, "none")  # loans have no safe default (F-44)
    over = {c.ledger.ledger_id: c for c in classify(ledgers, {"S": LedgerOverride("other_current_liabilities", "financing"),
                                                              "N": LedgerOverride("long_term_borrowings", None)},
                                                    GROUP_DEFAULTS, LINES)}
    assert (over["S"].ledger.line_code, over["S"].source, over["S"].ledger.cf_class) == ("other_current_liabilities", "ledger", "financing")
    assert (over["N"].ledger.line_code, over["N"].ledger.cf_class) == ("long_term_borrowings", "operating")


def test_F44_cash_flow_class_override_alone_keeps_group_default_line():
    cash = LedgerBalanceIn("C", "Cash", "cash_in_hand", None, "asset", D(0), D(5), D(0), D(5))
    out = classify((cash,), {"C": LedgerOverride(None, "investing")}, GROUP_DEFAULTS, LINES)[0]
    assert (out.ledger.line_code, out.source, out.ledger.cf_class) == ("cash_and_cash_equivalents", "group_firm", "investing")


def test_F45_snapshot_payload_round_trip_uses_line_codes_and_two_decimals():
    bs = run().balance_sheet
    payload = statement_payload(bs)
    assert payload["key"] == "balance_sheet" and payload["format"] == "sch3" and payload["to_date"] == "2027-03-31"
    amounts = amounts_from_payload(payload)
    assert amounts["ppe"] == D("90000.00") and amounts["total_assets"] == D("875000.00")
    assert amounts == amounts_of(bs)


def test_F46_register_rows_opening_addition_disposal_and_prior_depreciation():
    assets = (("A1", "Furniture"), ("A2", "Machine"), ("A3", "Old scooter"), ("A4", "Truck"))
    events = (
        RegisterEvent("A1", "opening", date(2025, 4, 1), D("100000.00"), D("20000.00")),
        RegisterEvent("A2", "opening", date(2025, 4, 1), D("200000.00")),
        RegisterEvent("A2", "addition", date(2026, 10, 1), D("50000.00")),
        RegisterEvent("A3", "opening", date(2025, 4, 1), D("30000.00")),
        RegisterEvent("A3", "disposal", date(2025, 12, 1), D("1000.00")),
        RegisterEvent("A4", "purchase", date(2025, 5, 1), D("80000.00")),
        RegisterEvent("A4", "disposal", date(2026, 9, 30), D("60000.00")),
    )
    dep = (
        RegisterDepLine("A1", date(2026, 3, 31), D("10000.00")), RegisterDepLine("A1", date(2027, 3, 31), D("10000.00")),
        RegisterDepLine("A2", date(2027, 3, 31), D("15000.00")),
        RegisterDepLine("A4", date(2026, 3, 31), D("8000.00")), RegisterDepLine("A4", date(2027, 3, 31), D("3000.00")),
    )
    rows = {r.name: r for r in build_ppe_rows(assets, events, dep, FY_FROM, FY_TO)}
    assert set(rows) == {"Furniture", "Machine", "Truck"}  # the scooter was disposed before the year
    furniture = rows["Furniture"]
    assert (furniture.opening_cost, furniture.additions, furniture.disposals) == (D("100000.00"), D("0.00"), D("0.00"))
    assert (furniture.opening_accumulated, furniture.depreciation_for_year) == (D("30000.00"), D("10000.00"))
    machine = rows["Machine"]
    assert (machine.opening_cost, machine.additions, machine.depreciation_for_year) == (D("200000.00"), D("50000.00"), D("15000.00"))
    truck = rows["Truck"]
    assert (truck.opening_cost, truck.disposals, truck.opening_accumulated) == (D("80000.00"), D("80000.00"), D("8000.00"))
    assert (truck.depreciation_for_year, truck.disposal_accumulated) == (D("3000.00"), D("11000.00"))
