# Phase 2 API contract (extends docs/API_CONTRACT.md; same conventions: amounts are 2-decimal strings, dates YYYY-MM-DD, `X-User` on writes, ServiceError → `{code, message, details}`, rule failures → `422 {"errors":[{rule_id, message, line_no}]}`)

New error codes → 409 unless named: `ledger_active`, `party_exists`, `not_a_party_group` (422), `statement_duplicate`, `statement_overlap`, `statement_invalid` (422, `details` = `[{row, message}]`, row 0 = whole file), `statement_in_use` (409, delete refused: lines matched or drafted), `invalid_bank_ledger` (422: ledger missing, other client's, inactive or not under Bank Accounts), `invalid_mapping` (422), `invalid_format` (422), `match_invalid`, `match_not_tied`, `format_exists`, `no_statement`.

## Parties (agent A)
`Party = {ledger_id, ledger_name, nature: "debtor"|"creditor", gstin, pan, state_code, credit_days, msme_category: "none"|"micro"|"small"|"medium", udyam_no, msme_written_agreement, bill_wise}`
- `GET /clients/{c}/parties?nature=` → `[Party]`
- `PUT /clients/{c}/parties/{ledger_id}` body = Party fields without ledger_id/name/nature → `200 {"ok":true}` or `422 {"errors":[{rule_id:"P-0x",message,line_no:null}]}`
- `GET /clients/{c}/parties/{ledger_id}` → Party

## Bill-wise (agent A)
Voucher line gets `allocations: [{kind, amount, bill_ref?, due_date?}]` (kind = new_ref|against_ref|advance|on_account) in `VoucherIn.lines[]` and in `Voucher.lines[]` (with resolved `due_date`). Rule errors B-0x use the standard `errors` list with `line_no`.
- `PUT /clients/{c}/financial-years/{fy}/opening-bills/{ledger_id}` body `{bills:[{bill_ref, bill_date, due_date?, amount, side:"Dr"|"Cr"}]}` (replaces the party's opening bills; `due_date` default bill_date + credit days) → `{"ok":true}`
- `GET /clients/{c}/financial-years/{fy}/opening-bills/{ledger_id}` → `{bills:[…], total: Balance, ledger_opening: Balance, difference: Balance, is_balanced}`
- `GET /clients/{c}/open-bills?party_ledger_id=&as_on=` → `[OpenBill]` where `OpenBill = {party_ledger_id, party_name, bill_ref|null, kind: "bill"|"advance"|"on_account", bill_date, due_date, original: Balance, outstanding: Balance}`
- `GET /clients/{c}/reports/outstanding?kind=receivable|payable&as_on=` → `{kind, as_on, parties:[{party_ledger_id, party_name, bills:[{bill_ref, kind, bill_date, due_date, original, outstanding, days_past_due, bucket}], total: Balance, ledger_balance: Balance, ties: bool}], buckets:{not_due, "0-30", "31-60", "61-90", "90+"} (2-decimal strings, positive), total: Balance, ties: bool}`  — amounts shown as positive with `side` where relevant; `ties` = sum of open items equals the party ledger closing balance
- `GET /clients/{c}/reports/ageing?kind=&as_on=` → party-wise bucket table `{rows:[{party_ledger_id, party_name, not_due, "0-30", "31-60", "61-90", "90+", total}], totals:{…}}`

## Cash / Bank book, MSME (agent B)
- `GET /clients/{c}/reports/cash-book?ledger_id=&from=&to=` → `{ledger_name, opening: Balance, days:[{date, receipts, payments, closing: Balance, entries:[{voucher_id, voucher_number, voucher_type, narration, counter_ledgers:[str], receipt, payment}]}], total_receipts, total_payments, closing: Balance}` (works for any Cash-in-hand or Bank ledger; "Bank Book" is the same call)
- `GET /clients/{c}/reports/msme-due?as_on=` → `{as_on, rule_status: "pending"|"verified", rule_source, items:[{party_ledger_id, party_name, bill_ref, bill_date, legal_days, legal_due_date, days_overdue, outstanding}], total_outstanding}`
- Cash rule C-01 and duplicate-payment D-01 appear as ordinary voucher rule errors on approve/post (and D-01 on create/update).

## Bank statements (agent C1)
`Mapping = {header_row: int (1-based), date_col, date_format ("%d/%m/%Y" …), description_col, reference_col?, debit_col?, credit_col?, amount_col?, drcr_col?, balance_col?, opening_balance_cell?|opening_balance?}` — columns are header names as in the file (case-insensitive) — either debit_col+credit_col or amount_col+drcr_col.
- `GET/POST /clients/{c}/bank-formats` (`{name, mapping}`) → `[{id,name,mapping}]` / `201 {format_id}`
- `POST /clients/{c}/bank-statements/preview` multipart(file, format_id | mapping as a JSON string, opening_balance?, closing_balance?) → `{rows:[first 20 parsed rows], count, opening_balance, closing_balance, problems:[{row, message}]}` (no write)
- `POST /clients/{c}/bank-statements` multipart(file, bank_ledger_id, format_id, opening_balance?, closing_balance?) → `201 {statement_id, lines, opening_balance, closing_balance}`
- `GET /clients/{c}/bank-statements?bank_ledger_id=` → `[{id, file_name, period_from, period_to, opening_balance, closing_balance, line_count, matched_count}]`
- `GET /bank-statements/{id}/lines` → `[{id, line_no, txn_date, description, reference, debit, credit, balance, match_id|null}]`
- `DELETE /bank-statements/{id}` → 204 (refused while any line is matched)

## Reconciliation (agent C2)
- `GET /clients/{c}/reconciliation/{bank_ledger_id}/unmatched?as_on=` → `{bank:[{line_id, txn_date, description, reference, debit, credit}], book:[{voucher_line_id|opening_item_id, date, voucher_number, narration, reference_no, debit, credit}], suggestions:[{bank_line_ids, book_item_ids, reason}]}`
- `POST …/auto-match` `{as_on, date_window_days?}` → `{matched_groups, matched_bank_lines, matched_book_items, suggestions_left}`
- `POST /clients/{c}/reconciliation/{bank_ledger_id}/matches` `{bank_line_ids:[], voucher_line_ids:[], opening_item_ids:[], note?}` → `201 {match_id}` | R-03/R-04 as `409 match_invalid|match_not_tied` with message
- `DELETE /clients/{c}/reconciliation/matches/{match_id}` → 204
- `GET /clients/{c}/reconciliation/{bank_ledger_id}/brs?as_on=` → `{as_on, balance_per_books: Balance, issued_not_presented:[item], deposited_not_cleared:[item], bank_only_credits:[item], bank_only_debits:[item], computed_bank_balance: Balance, balance_per_bank: Balance, difference: Balance, ties: bool}` with `item = {date, reference, description, amount}`
- `GET|PUT /clients/{c}/financial-years/{fy}/bank-opening-items/{bank_ledger_id}` `{items:[{kind, reference?, item_date, amount}]}`
- `POST /clients/{c}/reconciliation/{bank_ledger_id}/bank-only-drafts` `{items:[{bank_line_id, counter_ledger_id}]}` → `201 {created:[{bank_line_id, voucher_id}]}` (drafts only); `GET …/bank-only-suggestions?as_on=` → keyword-based counter-ledger suggestions

## Frontend screens (agent D)
Parties (list+edit), voucher entry with an allocation editor per party line (prefill: Sales/Purchase new_ref named from Reference No; show "allocated x of y"), Opening bills, Outstanding (receivable/payable with bucket columns), Ageing, Cash/Bank Book, MSME due, Bank formats + statement import (preview first), Reconciliation (two lists, drag-free: tick rows + "Match"), BRS.
