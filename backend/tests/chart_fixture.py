"""The seeded chart of account groups, typed literally (CLAUDE.md section 5).

Used by the database tests (the seed must produce exactly this) and by the engine tests (a real group tree).
"""

EXPECTED_GROUPS = [
    # code, name, parent code, nature, report
    ("bank_accounts", "Bank Accounts", "current_assets", "asset", "balance_sheet"),
    ("capital_account", "Capital Account", None, "liability", "balance_sheet"),
    ("cash_in_hand", "Cash-in-hand", "current_assets", "asset", "balance_sheet"),
    ("current_assets", "Current Assets", None, "asset", "balance_sheet"),
    ("current_liabilities", "Current Liabilities", None, "liability", "balance_sheet"),
    ("deposits_asset", "Deposits (Asset)", "current_assets", "asset", "balance_sheet"),
    ("direct_expenses", "Direct Expenses", None, "expense", "trading"),
    ("direct_incomes", "Direct Incomes", None, "income", "trading"),
    ("duties_taxes", "Duties & Taxes", "current_liabilities", "liability", "balance_sheet"),
    ("fixed_assets", "Fixed Assets", None, "asset", "balance_sheet"),
    ("indirect_expenses", "Indirect Expenses", None, "expense", "profit_loss"),
    ("indirect_incomes", "Indirect Incomes", None, "income", "profit_loss"),
    ("investments", "Investments", None, "asset", "balance_sheet"),
    ("loans_advances_asset", "Loans & Advances (Asset)", "current_assets", "asset", "balance_sheet"),
    ("loans_liability", "Loans (Liability)", None, "liability", "balance_sheet"),
    ("provisions", "Provisions", "current_liabilities", "liability", "balance_sheet"),
    ("purchase_accounts", "Purchase Accounts", None, "expense", "trading"),
    ("reserves_surplus", "Reserves & Surplus", "capital_account", "liability", "balance_sheet"),
    ("sales_accounts", "Sales Accounts", None, "income", "trading"),
    ("stock_in_hand", "Stock-in-hand", "current_assets", "asset", "balance_sheet"),
    ("sundry_creditors", "Sundry Creditors", "current_liabilities", "liability", "balance_sheet"),
    ("sundry_debtors", "Sundry Debtors", "current_assets", "asset", "balance_sheet"),
    ("suspense", "Suspense A/c", None, "liability", "balance_sheet"),
]


GROUP_TREE = {code: (name, parent, nature, report) for code, name, parent, nature, report in EXPECTED_GROUPS}
