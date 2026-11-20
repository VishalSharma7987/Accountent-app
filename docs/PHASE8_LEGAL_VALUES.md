# Phase 8 legal values (cash limits, Form 3CD / Form 26) and their status

Written 2026-11-20 (planning step 8.0). **No value is `verified`.** Three web searches / one page read were done: (1) "Income-tax Act 2025 section corresponding to 40A(3) cash payment ... 269ST 269SS 269T new section numbers", (2) "Income-tax Act 2025 Form 3CD tax audit new form number section 63 ...", (3) the page https://www.taxclue.in/blog/section-269ss-269st-income-tax-act-2025-mapping/ (read). incometaxindia.gov.in and indiacode.nic.in pages were returned by search but NOT opened. Per CLAUDE.md 2.5 every value is data in `audit_rule_limits` (seed 0014) and `audit_form_*` (seed 0015); the status shown is the status stored. The owner / CA must confirm the items in section 4 before the audit output is relied on.

Statuses: `secondary_verified` = seen on a secondary page read in this step. `pending` = recalled from the 1961 Act / Rules or carried over to the 2025 Act without reading its text.

## 1. Law selection
Expenditure and receipts dated up to 31-03-2026 are tested under the Income-tax Act 1961 (rows `it_act_1961`, `effective_to` 2026-03-31); dates from 01-04-2026 under the Income-tax Act 2025 (rows `it_act_2025`, `effective_from` 2026-04-01). The engine picks the row by the **transaction date**; if no row covers a date the check skips it and says so (never a default). Limits are never constants in code.

## 2. Cash limits (seed 0014, table `audit_rule_limits`)
| Rule key | Law | Section | Limit | Wording | Disallow % | Status |
| --- | --- | --- | --- | --- | --- | --- |
| cash_payment_daily_limit | 1961 | 40A(3) (Rule 6DD exceptions) | 10,000.00 per person per day | above | 100 | pending (recalled) |
| cash_payment_daily_limit | 2025 | successor of 40A(3): **section number not found** | 10,000.00 (carried over) | above | 100 | pending |
| cash_payment_daily_limit_transport | 1961 | 40A(3A) / Rule 6DD(g) | 35,000.00 | above | 100 | pending (recalled) |
| cash_payment_daily_limit_transport | 2025 | not found | 35,000.00 (carried over) | above | 100 | pending |
| cash_receipt_limit | 1961 | 269ST | 2,00,000.00 | at or above | - | secondary_verified (taxclue.in quotes "2,00,000 or more") |
| cash_receipt_limit | 2025 | section 186 (replaces 269ST per taxclue.in) | 2,00,000.00 (carried over) | at or above | - | pending (mapping seen, text and limit not read) |
Related mappings seen on the same page (not used by the engine; for the owner): 269SS -> s.185, 269T -> s.188, 269SU -> s.187; penalties 271D -> s.450, 271DA -> s.451, 271DB -> s.452, 271E -> s.453; interpretation s.189. The page does not mention 40A(3) at all, so its 2025 section is unknown. Per-person-per-day aggregation, the 100% disallowance, the transport carve-out and the Rule 6DD exceptions (bank holiday, rural area, etc.) are NOT modelled as law: the first three come from the rows above; the exceptions are decided by the reviewer on the working paper (a finding is an exception to confirm or clear, not a computed tax result).

## 3. Tax audit report form (seed 0015)
| Item | Finding | Status |
| --- | --- | --- |
| Form 3CD (1961 Act, section 44AB, Rule 6G) | applies up to FY 2025-26 | secondary_verified (replacement reported) |
| Form 26 (2025 Act section 63, Income-tax Rules 2026 rule 47) | consolidated tax audit report and statement of particulars replacing Forms 3CA / 3CB / 3CD from tax year 2026-27; CBDT FAQ titles `fn-26` and `form-26-faqs` found by search; secondary pages (visaverge.com, taxscan.in, taxguru.in, taxheal.com) agree; some compare a DRAFT form | secondary_verified; **clause numbering not read** |
| Form 3CD clauses 18, 21, 22, 23, 26, 27, 31, 34, 35, 40, 44 and their titles | recalled from memory of the 1961-Act form; the amended form may differ | pending |
No Form 26 clause is seeded. Package F reads the official form first and proposes the seed; everything it cannot read stays `pending`. Applicability of the tax audit itself (turnover and presumptive limits, section 63 conditions) is NOT computed by the engine and is not a rule here.

## 4. For the owner / CA to confirm before real use
1. Section number and exact text of the 2025-Act successor of 40A(3), the limit of 10,000 and the 100% disallowance, and the transport limit (35,000): official text at incometaxindia.gov.in (Act 2025 and Rules 2026) or the section-wise comparison utility.
2. Section 186 text and the 2,00,000 limit (at or above, aggregate per person per day / per transaction / per event).
3. Form 26 clause list and which clauses are derivable from books; Form 3CD clause numbers.
4. That no national / state holiday list is seeded: holidays are the accountant's input per client (nothing invented).
Reused rule tables (MSME days, GST, TDS rates, due dates, interest) keep the status recorded in Phases 2 to 4 (`docs/PHASE3_LEGAL_VALUES.md`, `docs/PHASE4_LEGAL_VALUES.md`); a pending row there shows up as "rule pending" in the report of the corresponding check.
