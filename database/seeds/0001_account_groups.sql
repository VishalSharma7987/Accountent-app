-- Seed: the system account groups of CLAUDE.md section 5 (client_id NULL, is_system = true).
-- Safe to run more than once. Schema-agnostic: the connection's search_path decides the schema.
-- Codes are stable identifiers used by the rule engine (e.g. voucher-type rules); names are what users see.

-- top-level groups
INSERT INTO account_groups (code, name, parent_id, nature, report, is_system)
SELECT v.code, v.name, NULL, v.nature, v.report, true
FROM (VALUES
    ('capital_account',     'Capital Account',     'liability', 'balance_sheet'),
    ('loans_liability',     'Loans (Liability)',   'liability', 'balance_sheet'),
    ('current_liabilities', 'Current Liabilities', 'liability', 'balance_sheet'),
    ('fixed_assets',        'Fixed Assets',        'asset',     'balance_sheet'),
    ('investments',         'Investments',         'asset',     'balance_sheet'),
    ('current_assets',      'Current Assets',      'asset',     'balance_sheet'),
    ('sales_accounts',      'Sales Accounts',      'income',    'trading'),
    ('direct_incomes',      'Direct Incomes',      'income',    'trading'),
    ('indirect_incomes',    'Indirect Incomes',    'income',    'profit_loss'),
    ('purchase_accounts',   'Purchase Accounts',   'expense',   'trading'),
    ('direct_expenses',     'Direct Expenses',     'expense',   'trading'),
    ('indirect_expenses',   'Indirect Expenses',   'expense',   'profit_loss'),
    ('suspense',            'Suspense A/c',        'liability', 'balance_sheet')
) AS v (code, name, nature, report)
ON CONFLICT (code) WHERE client_id IS NULL DO NOTHING;

-- sub-groups (each parent is a top-level group inserted above)
INSERT INTO account_groups (code, name, parent_id, nature, report, is_system)
SELECT v.code, v.name, p.id, v.nature, v.report, true
FROM (VALUES
    ('reserves_surplus',       'Reserves & Surplus',       'capital_account',     'liability', 'balance_sheet'),
    ('sundry_creditors',       'Sundry Creditors',         'current_liabilities', 'liability', 'balance_sheet'),
    ('duties_taxes',           'Duties & Taxes',           'current_liabilities', 'liability', 'balance_sheet'),
    ('provisions',             'Provisions',               'current_liabilities', 'liability', 'balance_sheet'),
    ('sundry_debtors',         'Sundry Debtors',           'current_assets',      'asset',     'balance_sheet'),
    ('bank_accounts',          'Bank Accounts',            'current_assets',      'asset',     'balance_sheet'),
    ('cash_in_hand',           'Cash-in-hand',             'current_assets',      'asset',     'balance_sheet'),
    ('stock_in_hand',          'Stock-in-hand',            'current_assets',      'asset',     'balance_sheet'),
    ('loans_advances_asset',   'Loans & Advances (Asset)', 'current_assets',      'asset',     'balance_sheet'),
    ('deposits_asset',         'Deposits (Asset)',         'current_assets',      'asset',     'balance_sheet')
) AS v (code, name, parent_code, nature, report)
JOIN account_groups p ON p.code = v.parent_code AND p.client_id IS NULL
ON CONFLICT (code) WHERE client_id IS NULL DO NOTHING;
