# LedgerMind API contract (Phase 1)

Base: the FastAPI app (`backend/app/main.py`). All bodies are JSON. In dev the frontend reaches it through the Vite proxy
under `/api/...` (the proxy strips `/api`), so the backend routes below have NO `/api` prefix.

**Conventions**
- **Amounts are strings with 2 decimals** (`"12500.00"`), in requests and responses. A JSON number for an amount is
  rejected with 422. Never floats.
- **Dates** are `YYYY-MM-DD`. **Ids** are UUID strings.
- **Actor:** every request that changes data must send header `X-User: <name>` (no login in Phase 1). Missing or blank
  -> `400 {"code":"invalid_actor","message":"..."}`. Reads do not need it.
- **Side of a balance** is `"Dr"`, `"Cr"` or `null` (nil). `Balance = {"amount": "15000.00", "side": "Dr"}`.
- **Errors**
  - Business refusal (`ServiceError`): `{"code": "...", "message": "plain language", "details": null | [...]}`.
    Status by code: `not_found` 404; `invalid_actor` 400; `invalid_*`, `reason_required`, `client_mismatch`,
    `invalid_range`, `no_financial_year`, `invalid_date` 422; everything else (duplicate_ledger, ledger_in_use,
    ledger_inactive, already_locked, not_locked, period_has_open_vouchers, not_draft, not_approved, not_posted,
    already_reversed, reversal_of_reversal, opening_locked, openings_unbalanced) 409.
  - **Voucher rule failures** -> `422 {"errors": [{"rule_id": "V-04", "message": "...", "line_no": null | 2}, ...]}`
    (create/update draft with rule errors, and approve/post/reverse that fail a rule re-check).
  - Malformed request (FastAPI/Pydantic) -> standard `422 {"detail": [...]}`.

## Clients
- `POST /clients` body `{name, legal_name?, entity_type, business_type, gst_type, pan?, state_code?, books_begin_date?,
  fy_start, proprietor_name?, partners?: [str]}` -> `201 {client_id, financial_year_id, ledger_ids: {name: id}}`
- `GET /clients` -> `[{id, name, legal_name, entity_type, business_type, gst_type, is_active}]`
- `GET /clients/{client_id}` -> client fields + `financial_years: [{id, start_date, end_date}]`

## Groups
- `GET /clients/{client_id}/groups` -> tree `[{code, name, nature, report, is_system, children: [...]}]`
  (system groups plus the client's own groups, nested by parent).

## Ledgers
- `GET /clients/{client_id}/ledgers?as_on=YYYY-MM-DD` -> `[{id, name, group_code, group_name, group_path: [str],
  is_active, balance: Balance}]` (closing balance as on `as_on`; default = today if inside a financial year, else the
  end of the latest year).
- `POST /clients/{client_id}/ledgers` `{name, group_code}` -> `201 {ledger_id}`
- `POST /clients/{client_id}/ledgers/{ledger_id}/deactivate` -> `200 {"ok": true}`
- `GET /clients/{client_id}/financial-years/{fy_id}/opening-balances` ->
  `{rows: [{ledger_id, ledger_name, debit, credit}], total_debit, total_credit, difference: Balance, is_balanced}`
- `PUT /clients/{client_id}/financial-years/{fy_id}/opening-balances/{ledger_id}` `{debit?: str, credit?: str}`
  -> `200 {"ok": true}` (both empty/zero removes the row)

## Vouchers
`VoucherIn = {voucher_type, voucher_date, narration, reference_no?, party_ledger_id?, duplicate_override_reason?,
lines: [{ledger_id, debit?: str, credit?: str}]}`
`Voucher = {id, client_id, financial_year_id, voucher_type, voucher_number | null, voucher_date, narration,
reference_no, party_ledger_id, status, reverses_voucher_id, reversed_by_voucher_id, duplicate_override_reason,
created_by, approved_by, posted_by, lines: [{line_no, ledger_id, ledger_name, debit, credit}]}`
- `POST /clients/{client_id}/vouchers` `VoucherIn` -> `201 {voucher_id}` | `422 {"errors": [...]}`
- `GET /clients/{client_id}/vouchers?from=&to=&type=&status=&ledger_id=&limit=&offset=` ->
  `{items: [{id, voucher_number, voucher_type, voucher_date, narration, reference_no, status, total}], total_count}`
  (`total` = total debit as string; default limit 100; ordered by date then number; `from`/`to` inclusive).
- `GET /vouchers/{voucher_id}` -> `Voucher`
- `PUT /vouchers/{voucher_id}` `VoucherIn` -> `200 {voucher_id}` | `422 {"errors": [...]}` (drafts only)
- `DELETE /vouchers/{voucher_id}` -> `204` (drafts only)
- `POST /vouchers/{voucher_id}/approve` -> `200 {"ok": true}`
- `POST /vouchers/{voucher_id}/return-to-draft` -> `200 {"ok": true}`
- `POST /vouchers/{voucher_id}/post` -> `200 {"voucher_number": "PAY/2026-27/0001"}`
- `POST /vouchers/{voucher_id}/reverse` `{reversal_date, reason}` -> `201 {"reversal_voucher_id": id}`

## Periods
- `GET /clients/{client_id}/periods?fy_id=` -> `[{id, financial_year_id, start, end, status, locked_at, locked_by}]`
- `POST /clients/{client_id}/periods/{period_id}/lock` -> `200 {"ok": true}`; refusal `409 period_has_open_vouchers`
  with `details: [{voucher_id, voucher_type, voucher_date, status, narration}]`
- `POST /clients/{client_id}/periods/{period_id}/unlock` `{reason}` -> `200 {"ok": true}`

## Reports
- `GET /clients/{client_id}/reports/ledger-statement?ledger_id=&from=&to=` ->
  `{ledger_id, ledger_name, from_date, to_date, opening: Balance, closing: Balance, total_debit, total_credit,
  rows: [{kind: "opening"|"entry"|"closing", date, voucher_number, voucher_type, narration, particulars, debit, credit,
  balance: Balance}]}`
- `GET /clients/{client_id}/reports/trial-balance?as_on=&hide_zero=false` ->
  `{as_on, sections: [{group_code, group_name, debit, credit, rows: [{group_path: [str], ledger_id, ledger_name, debit,
  credit}]}], total_debit, total_credit, difference: Balance, is_balanced}`

## Audit log
- `GET /clients/{client_id}/audit-log?entity=&entity_id=&limit=` -> `[{id, actor, action, entity, entity_id, old_data,
  new_data, created_at}]` newest first (default limit 100).

## Excel import (added in step 1.8)
- `GET /clients/{client_id}/imports/vouchers/template` -> the `.xlsx` template (download)
- `POST /clients/{client_id}/imports/vouchers/dry-run` multipart `file` ->
  `{vouchers: [{ref_id, first_row, status: "ok"|"error", errors: [{rule_id, message, line_no, row}],
  allocations: [{line_no, row, kind, bill_ref, amount, due_date, auto}]}], ok_count, error_count}`
- `POST /clients/{client_id}/imports/vouchers/commit` multipart `file` + form field `ref_ids` (comma separated, empty =
  all OK vouchers) -> `{created: [{ref_id, voucher_id, allocations}], skipped: [{ref_id, reason}]}` (drafts only; never posts)

Bill allocation columns (Phase 2.1). The voucher sheet is `ref_id, date, voucher_type, ledger_name, debit, credit,
narration, reference_no, party_ledger, bill_type, bill_ref, bill_amount, due_date` (the old 9-column header is still
accepted). `bill_type`: New Ref / Against Ref / Advance / On Account (case, spaces and underscores ignored) =
`new_ref / against_ref / advance / on_account`; `bill_amount` follows the debit/credit amount rules (max 2 decimals,
text commas stripped); `due_date` is optional and for New Ref only. The first allocation of a line goes on the line's
own row; more allocations of the same line go on continuation rows right below: same `ref_id`, `ledger_name`, `debit`
and `credit` empty, only the bill columns filled. The allocations of a line must add up to the line amount (B-01).
A Sales or Purchase line of a bill-wise party ledger WITHOUT allocation gets ONE New Ref for the full amount with
`bill_ref` = the voucher's `reference_no` (flagged `auto: true` in `allocations`, dry run and commit); a blank
`reference_no` is an error (Sales: B-03, Purchase: V-14). Receipt, Payment, Credit Note, Debit Note and Journal lines
of a bill-wise party are never allocated automatically (B-01). Allocations on non-bill-wise ledgers are passed on and
rejected by the engine (B-01). Errors and `row` numbers point at the Excel row of the line or of the allocation.
