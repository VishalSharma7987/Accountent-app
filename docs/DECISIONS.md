# Decisions log

Small decisions taken without asking the owner (see CLAUDE.md section 6). Each row: date, step, decision, reason.
Anything that touches a legal value, existing data or `docs/REQUIREMENTS.md` is NOT decided here; it goes to the owner.

| Date | Step | Decision | Reason |
| --- | --- | --- | --- |
| 2026-11-11 | 1.1 | System group codes are snake-case slugs (`sundry_debtors`, `cash_in_hand`, ...). | CLAUDE.md lists names only; the rule engine needs stable identifiers. Owner was told. |
| 2026-11-11 | 1.1 | Voucher number exists exactly from posting onwards; vouchers must be created as draft; reversal links are composite foreign keys. | Matches "drafts get an internal ID only" and the client-isolation requirement. |
| 2026-11-11 | 1.1 | `voucher_number_sequences` can only count up by 1 and cannot be deleted. | Gapless numbering is a stated requirement. |
| 2026-11-11 | 1.1 | Custom account groups keep nature/report/parent for life (only name/code editable). | Guarantees "equals the parent's" forever without re-validating children. |
| 2026-11-11 | 1.1 | Test DB cleanup is once per session; every test runs in a rolled-back transaction. | Speed; leftovers fail the session loudly. |
| 2026-11-11 | 0004 | Money columns are NUMERIC(18,4) + CHECK (x = round(x,2)) instead of `scale()`. | `scale()` is always 4 on a (18,4) column; `round` rejects 10.005. Owner approved. |
| 2026-11-11 | 1.2 | `VoucherLine` keeps amounts as entered (str/int/Decimal/None); blank or None means zero. | V-03 must see `10.005`, `-5` and non-numbers; importers pass raw cells. |
| 2026-11-11 | 1.2 | V-10 applies only when a reference no exists; trimmed, case-insensitive; ignores reversed vouchers, reversal vouchers and the voucher being edited. | Requirements say party + bill no + amount; a corrected re-entry must be allowed. Owner approved. |
| 2026-11-11 | 1.2 | V-14: a blank reference counts as missing. V-07 with no period row for a date inside a financial year is an error, checked only after V-06 passes. Dates in messages are dd-mm-yyyy; amounts Indian format. | Owner approved. |
| 2026-11-11 | 1.2 | `parse_amount` rejects commas, signs, exponents and floats; importers must strip commas explicitly. Result always has 2 decimals. Maximum amount 9,99,99,99,99,99,999.99 (14 whole digits). | No guessing; matches the database column. |
| 2026-11-11 | 1.2 | V-08 is judged only when every line's ledger exists and every line has valid amounts (otherwise only V-05/V-02/V-03 are reported). | Prevents false V-08 errors caused by an unknown ledger or an unreadable amount. |
| 2026-11-11 | 1.2 | A Contra voucher with a party ledger set is a V-08 error. | The Step 1.2 test list says "Contra with a party ledger -> V-08". |
| 2026-11-11 | 1.2 | Pack format: `party_ledger` is a required column (value may be empty) placed after `reference_no`. | Strict headers keep the loader simple; the template shows it. |
| 2026-11-11 | 1.2 | Suggestion (not built): require the party ledger to be under Sundry Debtors/Creditors for Sales/Purchase/Receipt/Payment. | Owner said "not restricted for now". |
| 2026-11-11 | 1.2 | V-04 and V-08 are judged only when the voucher has 2 or more lines; V-04 and V-08 also need readable amounts (no V-02/V-03 error); V-08 also needs usable ledgers (no V-05 error on a line). Within one rule, errors are ordered by line, voucher-level errors last. | Avoids cascades of misleading errors (a one-line voucher is always "unbalanced"). |
