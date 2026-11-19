-- Seed: Phase 6 Schedule III (Companies Act 2013, Division I: companies following Accounting Standards) line items and the default
-- map from system account groups to those lines. Safe to run more than once. Schedule-agnostic and law-as-data: the layout headings are
-- rows, so a change in the Schedule is a new row with an effective_from, not a code change.
-- Status 'pending' everywhere: the Schedule III text was recalled, not read from the Act in step 6.0 (docs/PHASE6_LEGAL_VALUES.md).
-- cf_class is the default Cash Flow (AS 3) class of the line's balance-sheet movement: operating (working capital), investing,
-- financing, cash_equivalent (cash and bank), equity_profit (reserves: moves with profit, not a cash item).

INSERT INTO fs_lines (format_key, line_code, label, section, sort_order, note_title, cf_class, effective_from, source_reference, verification_status)
VALUES
    ('sch3_bs', 'share_capital', 'Share capital', 'equity', 10, 'Share capital', 'financing', DATE '2014-04-01', 'Companies Act 2013 Schedule III Division I, Balance Sheet I.1(a) (recalled)', 'pending'),
    ('sch3_bs', 'reserves_surplus', 'Reserves and surplus', 'equity', 20, 'Reserves and surplus', 'equity_profit', DATE '2014-04-01', 'Schedule III Div I, BS I.1(b)', 'pending'),
    ('sch3_bs', 'long_term_borrowings', 'Long-term borrowings', 'non_current_liabilities', 30, 'Long-term borrowings', 'financing', DATE '2014-04-01', 'Schedule III Div I, BS I.2(a)', 'pending'),
    ('sch3_bs', 'deferred_tax_liabilities', 'Deferred tax liabilities (net)', 'non_current_liabilities', 40, NULL, 'non_cash', DATE '2014-04-01', 'Schedule III Div I, BS I.2(b)', 'pending'),
    ('sch3_bs', 'other_long_term_liabilities', 'Other long-term liabilities', 'non_current_liabilities', 50, 'Other long-term liabilities', 'financing', DATE '2014-04-01', 'Schedule III Div I, BS I.2(c)', 'pending'),
    ('sch3_bs', 'long_term_provisions', 'Long-term provisions', 'non_current_liabilities', 60, 'Long-term provisions', 'operating', DATE '2014-04-01', 'Schedule III Div I, BS I.2(d)', 'pending'),
    ('sch3_bs', 'short_term_borrowings', 'Short-term borrowings', 'current_liabilities', 70, 'Short-term borrowings', 'financing', DATE '2014-04-01', 'Schedule III Div I, BS I.3(a)', 'pending'),
    ('sch3_bs', 'trade_payables', 'Trade payables', 'current_liabilities', 80, 'Trade payables', 'operating', DATE '2014-04-01', 'Schedule III Div I, BS I.3(b)', 'pending'),
    ('sch3_bs', 'other_current_liabilities', 'Other current liabilities', 'current_liabilities', 90, 'Other current liabilities', 'operating', DATE '2014-04-01', 'Schedule III Div I, BS I.3(c)', 'pending'),
    ('sch3_bs', 'short_term_provisions', 'Short-term provisions', 'current_liabilities', 100, 'Short-term provisions', 'operating', DATE '2014-04-01', 'Schedule III Div I, BS I.3(d)', 'pending'),
    ('sch3_bs', 'ppe', 'Property, plant and equipment', 'non_current_assets', 110, 'Property, plant and equipment', 'investing', DATE '2014-04-01', 'Schedule III Div I, BS II.1(a)(i)', 'pending'),
    ('sch3_bs', 'intangible_assets', 'Intangible assets', 'non_current_assets', 120, 'Intangible assets', 'investing', DATE '2014-04-01', 'Schedule III Div I, BS II.1(a)(ii)', 'pending'),
    ('sch3_bs', 'capital_wip', 'Capital work-in-progress', 'non_current_assets', 130, NULL, 'investing', DATE '2014-04-01', 'Schedule III Div I, BS II.1(a)(iii)', 'pending'),
    ('sch3_bs', 'non_current_investments', 'Non-current investments', 'non_current_assets', 140, 'Non-current investments', 'investing', DATE '2014-04-01', 'Schedule III Div I, BS II.1(b)', 'pending'),
    ('sch3_bs', 'deferred_tax_assets', 'Deferred tax assets (net)', 'non_current_assets', 150, NULL, 'non_cash', DATE '2014-04-01', 'Schedule III Div I, BS II.1(c)', 'pending'),
    ('sch3_bs', 'long_term_loans_advances', 'Long-term loans and advances', 'non_current_assets', 160, 'Long-term loans and advances', 'investing', DATE '2014-04-01', 'Schedule III Div I, BS II.1(d)', 'pending'),
    ('sch3_bs', 'other_non_current_assets', 'Other non-current assets', 'non_current_assets', 170, 'Other non-current assets', 'investing', DATE '2014-04-01', 'Schedule III Div I, BS II.1(e)', 'pending'),
    ('sch3_bs', 'current_investments', 'Current investments', 'current_assets', 180, 'Current investments', 'investing', DATE '2014-04-01', 'Schedule III Div I, BS II.2(a)', 'pending'),
    ('sch3_bs', 'inventories', 'Inventories', 'current_assets', 190, 'Inventories', 'operating', DATE '2014-04-01', 'Schedule III Div I, BS II.2(b)', 'pending'),
    ('sch3_bs', 'trade_receivables', 'Trade receivables', 'current_assets', 200, 'Trade receivables', 'operating', DATE '2014-04-01', 'Schedule III Div I, BS II.2(c)', 'pending'),
    ('sch3_bs', 'cash_and_cash_equivalents', 'Cash and cash equivalents', 'current_assets', 210, 'Cash and cash equivalents', 'cash_equivalent', DATE '2014-04-01', 'Schedule III Div I, BS II.2(d)', 'pending'),
    ('sch3_bs', 'short_term_loans_advances', 'Short-term loans and advances', 'current_assets', 220, 'Short-term loans and advances', 'operating', DATE '2014-04-01', 'Schedule III Div I, BS II.2(e)', 'pending'),
    ('sch3_bs', 'other_current_assets', 'Other current assets', 'current_assets', 230, 'Other current assets', 'operating', DATE '2014-04-01', 'Schedule III Div I, BS II.2(f)', 'pending'),

    ('sch3_pl', 'revenue_from_operations', 'Revenue from operations', 'income', 10, 'Revenue from operations', 'operating', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss I', 'pending'),
    ('sch3_pl', 'other_income', 'Other income', 'income', 20, 'Other income', 'operating', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss II', 'pending'),
    ('sch3_pl', 'cost_of_materials_consumed', 'Cost of materials consumed', 'expenses', 30, NULL, 'operating', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss IV(a)', 'pending'),
    ('sch3_pl', 'purchases_stock_in_trade', 'Purchases of stock-in-trade', 'expenses', 40, NULL, 'operating', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss IV(b)', 'pending'),
    ('sch3_pl', 'changes_in_inventories', 'Changes in inventories of finished goods, work-in-progress and stock-in-trade', 'expenses', 50, NULL, 'operating', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss IV(c)', 'pending'),
    ('sch3_pl', 'employee_benefits_expense', 'Employee benefits expense', 'expenses', 60, 'Employee benefits expense', 'operating', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss IV(d)', 'pending'),
    ('sch3_pl', 'finance_costs', 'Finance costs', 'expenses', 70, 'Finance costs', 'financing', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss IV(e)', 'pending'),
    ('sch3_pl', 'depreciation_amortisation', 'Depreciation and amortisation expense', 'expenses', 80, NULL, 'non_cash', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss IV(f)', 'pending'),
    ('sch3_pl', 'other_expenses', 'Other expenses', 'expenses', 90, 'Other expenses', 'operating', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss IV(g)', 'pending'),
    ('sch3_pl', 'tax_expense', 'Tax expense', 'expenses', 100, NULL, 'operating', DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss VIII', 'pending')
ON CONFLICT (format_key, line_code, effective_from) DO UPDATE SET label = EXCLUDED.label, section = EXCLUDED.section,
    sort_order = EXCLUDED.sort_order, note_title = EXCLUDED.note_title, cf_class = EXCLUDED.cf_class,
    source_reference = EXCLUDED.source_reference, verification_status = EXCLUDED.verification_status;

-- Default classification of the system groups. is_firm = true: that group always belongs on that line. is_firm = false: the usual
-- home of the group but the accountant must confirm ledger by ledger (the statement warns, F-44w). Groups NOT listed here
-- (loans_liability, investments, deposits_asset, current_liabilities as a direct group, current_assets as a direct group) have no
-- safe default (long-term or short-term? current or non-current?) and every ledger in them must be classified (F-44, error).
INSERT INTO fs_group_map (group_code, format_key, line_code, is_firm, effective_from, source_reference, verification_status)
VALUES
    ('capital_account', 'sch3_bs', 'share_capital', false, DATE '2014-04-01', 'Default: Capital Account of a company holds share capital; securities premium etc. belong to reserves', 'pending'),
    ('reserves_surplus', 'sch3_bs', 'reserves_surplus', true, DATE '2014-04-01', 'Schedule III Div I, BS I.1(b)', 'pending'),
    ('sundry_creditors', 'sch3_bs', 'trade_payables', false, DATE '2014-04-01', 'Default: creditors for goods and services are trade payables; others (capital creditors) need a ledger override', 'pending'),
    ('duties_taxes', 'sch3_bs', 'other_current_liabilities', true, DATE '2014-04-01', 'Schedule III Div I, BS I.3(c) (statutory dues)', 'pending'),
    ('provisions', 'sch3_bs', 'short_term_provisions', false, DATE '2014-04-01', 'Default: short-term; a long-term provision needs a ledger override', 'pending'),
    ('suspense', 'sch3_bs', 'other_current_liabilities', false, DATE '2014-04-01', 'Default: a suspense balance is shown as other current liability and flagged for the accountant', 'pending'),
    ('fixed_assets', 'sch3_bs', 'ppe', false, DATE '2014-04-01', 'Default: tangible; intangible assets and capital work-in-progress need a ledger override', 'pending'),
    ('sundry_debtors', 'sch3_bs', 'trade_receivables', true, DATE '2014-04-01', 'Schedule III Div I, BS II.2(c)', 'pending'),
    ('bank_accounts', 'sch3_bs', 'cash_and_cash_equivalents', true, DATE '2014-04-01', 'Schedule III Div I, BS II.2(d)', 'pending'),
    ('cash_in_hand', 'sch3_bs', 'cash_and_cash_equivalents', true, DATE '2014-04-01', 'Schedule III Div I, BS II.2(d)', 'pending'),
    ('stock_in_hand', 'sch3_bs', 'inventories', true, DATE '2014-04-01', 'Schedule III Div I, BS II.2(b)', 'pending'),
    ('loans_advances_asset', 'sch3_bs', 'short_term_loans_advances', false, DATE '2014-04-01', 'Default: short-term; long-term advances need a ledger override', 'pending'),
    ('sales_accounts', 'sch3_pl', 'revenue_from_operations', true, DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss I', 'pending'),
    ('direct_incomes', 'sch3_pl', 'revenue_from_operations', false, DATE '2014-04-01', 'Default: operating income; other income needs a ledger override', 'pending'),
    ('indirect_incomes', 'sch3_pl', 'other_income', true, DATE '2014-04-01', 'Schedule III Div I, Statement of Profit and Loss II', 'pending'),
    ('purchase_accounts', 'sch3_pl', 'purchases_stock_in_trade', false, DATE '2014-04-01', 'Default: trading purchases; a manufacturer overrides raw-material ledgers to cost of materials consumed', 'pending'),
    ('direct_expenses', 'sch3_pl', 'other_expenses', false, DATE '2014-04-01', 'Default: other expenses; direct manufacturing costs need a ledger override', 'pending'),
    ('indirect_expenses', 'sch3_pl', 'other_expenses', false, DATE '2014-04-01', 'Default: other expenses; salary, interest and depreciation ledgers must be moved to their own lines by override or role', 'pending')
ON CONFLICT (group_code, format_key, effective_from) DO UPDATE SET line_code = EXCLUDED.line_code, is_firm = EXCLUDED.is_firm,
    source_reference = EXCLUDED.source_reference, verification_status = EXCLUDED.verification_status;
