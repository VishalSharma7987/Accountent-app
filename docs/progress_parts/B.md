Step 2.4-2.5 (agent B): Cash/Bank Book (engine/cashbook.py, services/cashbook.py, GET reports/cash-book), C-01 no-negative-cash (engine/cash_rules.py, services/cash_checks.py hooked into approve/post/reverse), D-01 duplicate payment (engine/payments.py), M-01 MSME flag (engine/msme.py, rules/msme.py, services/msme.py, GET reports/msme-due).
Tests: 38 new unit tests (tests/unit/engine/test_cashbook|cash_rules|payments|msme.py) + 8 integration (tests/integration/test_cash_book_rules.py).
Rule table msme_payment_rules: all 6 seed rows verification_status='pending'; reports show rule_status/rule_source.
Shared-file edits: services/vouchers.py (4 one-line hooks), main.py (2 routers).
Commit: branch p2-B.
