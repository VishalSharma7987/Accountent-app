# Test packs

A test pack is a folder of plain files that describes **one small set of books and the answers we expect**.
The accountant team fills in and checks the pack by hand. The tool is then tested against it: if the tool's numbers
differ from the pack by even one paisa, the tool is wrong (or the pack is — the team decides which).

> The expected answers must be worked out **by hand** (T-accounts, Tally or Excel) — never copied from this tool.
> Use dummy names only: no real client names, PAN, Aadhaar or bank account numbers.

## Folder layout

One folder per pack, named `<client>-<period>`, e.g. `abc-traders-apr-2026`. Start by copying `_template/`.

| File | What you write | Used for |
| --- | --- | --- |
| `client.yaml` | The client's profile and the pack's end date | Sets up the client |
| `ledgers.csv` | Every ledger, its group and opening balance | Chart of accounts + openings |
| `vouchers.csv` | The **correct** vouchers | Must post without any error |
| `invalid_vouchers.csv` | **Wrong** vouchers on purpose, and the rule each one breaks | Each must be rejected with that rule |
| `expected_ledger_balances.csv` | Closing balance of every ledger on the pack's end date | Compared with the tool |
| `expected_trial_balance.csv` | The Trial Balance on the pack's end date, with a TOTAL row | Compared with the tool |
| `reversals.csv` | *(optional)* Vouchers to reverse, with date and reason | Reversals are done after all vouchers are posted |
| `locked_periods.csv` | *(optional)* Months to lock before the wrong vouchers are tried | Lets a wrong voucher hit a locked period (V-07) |
| `WORKING.md` | *(recommended)* Your hand workings (T-accounts) | How the expected files were worked out |
| `SIGNOFF.md` | Who verified the pack, when, and how | Required before a phase can be accepted |

## Writing rules (apply to every file)

- **Amounts:** plain numbers with exactly 2 decimals: `12500.00`. No commas, no `₹`, no minus sign. Use `0.00` for "nothing".
  (Exception: `invalid_vouchers.csv`, where you may type a bad amount like `1000.005` — that is the test.)
- **Dates:** `YYYY-MM-DD`, e.g. `2026-04-05`. Day and month must be real (`2026-02-30` is an error).
- **Ledger names:** must be spelled **exactly** as in `ledgers.csv` (capital letters included) in every other file.
- **Groups:** must be one of the standard groups (Capital Account, Sundry Debtors, Bank Accounts, Cash-in-hand,
  Sales Accounts, Indirect Expenses, … — the full list is in `CLAUDE.md` section 5).
- **Debit / credit:** one side per line. A debit balance goes in the `dr` / `closing_dr` / `opening_dr` column, a credit
  balance in the `cr` / `closing_cr` / `opening_cr` column. The other column is `0.00`.
- Save CSVs as **CSV UTF-8** from Excel. Do not leave blank columns out; keep every column, even if empty.

## client.yaml

```yaml
name: Template Client
entity_type: proprietorship     # proprietorship | partnership | llp | company
business_type: trading          # trading | service | manufacturing
gst_type: regular               # regular | composition | unregistered
fy_start: 2026-04-01            # must be 1 April
pack_end_date: 2026-04-30       # inside the financial year; "closing" files are as on this date
proprietor_name: Owner          # required for a proprietorship: the Capital account is "Owner Capital A/c"
# partners: [Anil Shah, Bina Shah]   # required instead for a partnership / LLP (Capital + Current account each)
```

The tool creates the client's standard ledgers (Cash, Suspense A/c, Capital, Drawings, Purchases, Sales, ... see
`backend/app/engine/coa_templates.py`). List **every** ledger of the pack in `ledgers.csv`, including those standard
ones, using exactly the names the tool creates (the Capital account name comes from `proprietor_name` / `partners`).
A ledger you list that the tool does not create is added to the client.

## ledgers.csv

`ledger_name, group_name, opening_dr, opening_cr`. Total opening debits must equal total opening credits, otherwise
the tool will not allow posting for that client.

## vouchers.csv — the correct vouchers

`ref_id, date, voucher_type, ledger_name, debit, credit, narration, reference_no, party_ledger`

- **One row per voucher line.** Rows with the same `ref_id` are **one voucher** (V01, V02, … — your own label).
  All rows of a voucher must have the same date, voucher type, narration and reference number.
- `voucher_type` is one of: `contra`, `payment`, `receipt`, `sales`, `purchase`, `credit_note`, `debit_note`, `journal`.
- Every voucher must balance (total debit = total credit) and every line has either a debit or a credit.
- `narration` is required. `reference_no` (bill / cheque / UTR number) may be empty, except for `purchase` and `debit_note`, which need the supplier bill number or the original reference (rule V-14).
- `party_ledger` is the voucher's party (customer or supplier) as a ledger name; leave it empty when there is none. If it is filled, that ledger must also be one of the voucher's lines (rule V-13). Every row of a voucher carries the same value.
- Put the vouchers in the order you want them posted.

## invalid_vouchers.csv — the deliberately wrong vouchers

Same columns as `vouchers.csv`, plus:

- `expected_rule_id` — the rule that must reject it, `V-01` … `V-14` (list in `CLAUDE.md` section 5).
- `expected_message_contains` — one word the error message should contain (not case-sensitive), e.g. `narration`.

All lines of one wrong voucher carry the same two values. Here anything may be wrong **except** the date format and the
voucher type: an unknown ledger, a missing narration, an unbalanced total, an amount like `1000.005`, a date in a
locked period. Make each wrong voucher wrong in **one** way only, so the expected rule is unambiguous.

## expected_ledger_balances.csv

`ledger_name, closing_dr, closing_cr` — **every** ledger of `ledgers.csv`, once, including nil balances (`0.00, 0.00`).

## expected_trial_balance.csv

`group_name, ledger_name, dr, cr` — one line per ledger (same figures as the balances file) and **one last row**
`TOTAL,,<total dr>,<total cr>`. The totals must be equal. The ledger's `group_name` must be the group in `ledgers.csv`.

## reversals.csv (optional)

`ref_id, reversal_date, reason` — each `ref_id` is a voucher of `vouchers.csv`. After **all** vouchers are posted, the
tool reverses it on `reversal_date` (a mirror voucher with every Dr/Cr swapped). The reversed voucher and its mirror
**both** count, so they cancel out: the expected files simply show no effect from that voucher. A voucher can be
reversed only once; the date must be inside the pack period.

## locked_periods.csv (optional)

`month` — one `YYYY-MM` per row. The tool locks these months **after** the correct vouchers are posted and
**before** the wrong vouchers are tried, so a wrong voucher dated in a locked month must be rejected with rule V-07.
Lock a month that has no correct vouchers.

## SIGNOFF.md

The person who checked the pack ticks the checklist and signs with name and date. A phase is accepted only when its
packs are signed off **and** the tool matches them.

## Checking a pack's format

The loader `backend/tests/acceptance/pack_loader.py` reads a pack and lists every format problem with the file name
and row number (unknown ledger, bad date, unbalanced expected Trial Balance, …):

```powershell
cd backend
..\.venv\Scripts\python -c "import sys; sys.path.insert(0,'tests/acceptance'); from pack_loader import load_pack; load_pack(r'..\docs\test-packs\_template'); print('pack format OK')"
```

It checks the files' **format and agreement with each other**; it does not run the accounting engine.
`_template/` is a valid, tiny example (3 vouchers, 3 wrong vouchers) — copy it, then replace its contents.

## Self-check: do the expected balances agree with the vouchers? (warnings only)

`balance_warnings(pack)` in the same file recomputes every ledger's closing balance with plain addition —
opening balance + all debits - all credits of `vouchers.csv` (`invalid_vouchers.csv` is ignored) — and lists each
ledger where `expected_ledger_balances.csv` says something different, e.g.

```text
expected_ledger_balances.csv: 'Cash' is Dr 4000.00 there, but ledgers.csv + vouchers.csv give Dr 5000.00 (difference 1000.00)
```

It only **warns**: it never changes a pack file and never stops a pack from loading. A difference means "look again" —
you may have mistyped a voucher or an expected figure; the accountant decides which one is right.

```powershell
cd backend
..\.venv\Scripts\python -c "import sys; sys.path.insert(0,'tests/acceptance'); from pack_loader import load_pack, balance_warnings; w = balance_warnings(load_pack(r'..\docs\test-packs\_template')); print('\n'.join(w) or 'no differences')"
```

## Phase 2 pack files (parties, bill-wise, cash, bank, BRS)

The Phase 2 pack `abc-traders-phase2-jun-2026/` keeps the Phase 1 formats unchanged (`client.yaml`, `ledgers.csv`,
`vouchers.csv`, `reversals.csv`, `expected_trial_balance.csv`; same writing rules: 2-decimal amounts, `YYYY-MM-DD`
dates, exact ledger names) and adds the files below. Allocations are kept in a **separate file** so `vouchers.csv` stays
one row per voucher line. The wrong vouchers are in `wrong_vouchers.csv` (not `invalid_vouchers.csv`), because they
carry Phase 2 rule ids (B-, C-, D-, P-). All expected files are typed by hand (see `WORKING.md`), never copied from the tool.
Report date of this pack: 30-06-2026 (`pack_end_date`).

| File | Columns | Meaning |
| --- | --- | --- |
| `parties.csv` | `ledger_name, gstin, pan, state_code, credit_days, msme_category, udyam_no, msme_written_agreement, bill_wise` | Party master for the ledgers under Sundry Debtors / Creditors. `msme_category` = none / micro / small / medium; flags are `true` / `false`; empty = not given. |
| `opening_bills.csv` | `ledger_name, bill_ref, bill_date, due_date, amount, side` | Opening bills (side `Dr` debtor, `Cr` creditor). Per party they must add up to that ledger's opening balance. |
| `opening_balances.csv` | `ledger_name, opening_dr, opening_cr` | The non-zero openings of `ledgers.csv` again (a compact copy; the self-check makes sure the two agree). |
| `allocations.csv` | `ref_id, line_no, kind, amount, bill_ref, due_date` | Bill-wise allocation of a voucher line. `ref_id` = voucher of `vouchers.csv`; `line_no` = 1-based position of the line inside that voucher; `kind` = `new_ref` / `against_ref` / `advance` / `on_account`; `bill_ref` empty for `on_account`; `due_date` optional (empty = bill date + credit days). Every party line carries allocations that add up to the line amount; one line may have several rows (an invoice that absorbs an advance: `new_ref` 88,000 + `against_ref` 30,000 on a 1,18,000 line). No allocation on non-party lines. |
| `wrong_vouchers.csv` | the `vouchers.csv` columns + `expected_rule_id, expected_message_contains` | Wrong vouchers (B-, C-, D- rules), tried AFTER all correct vouchers and reversals are posted. `expected_message_contains` is advisory. |
| `wrong_allocations.csv` | same columns as `allocations.csv` | Allocations of the wrong vouchers (by their `ref_id`). |
| `wrong_parties.csv` | the `parties.csv` columns, with `ledger_name` of an existing party, + `ref_id` first and `expected_rule_id, expected_message_contains` last | Party edits that must be refused (P-01, P-03, P-05). |
| `bank_format.json` | `{name, bank_ledger, mapping{...}}` | The saved column mapping of the bank's CSV (see `PHASE2_API_CONTRACT.md`, Mapping); `mapping.opening_balance` is the statement's opening balance. |
| `bank_statement.csv` | `Txn Date, Narration, Chq/Ref No, Withdrawal Amt, Deposit Amt, Closing Balance` | The bank's own file: dates `dd/mm/yyyy`, plain amounts, the empty side left blank. |
| `bank_opening_items.csv` | `kind, reference, item_date, amount` | Reconciling items carried from the previous year (`issued_not_presented` / `deposited_not_cleared`). |
| `expected_outstanding_receivable.csv`, `expected_outstanding_payable.csv` | `row_type, party, bill_ref, kind, side, bill_date, due_date, original, outstanding, days_past_due, bucket` | `row_type` = `bill` / `on_account` / `party_total` / `grand_total`. Amounts positive; `side` is the direction of the item (an item on the side opposite to the party's natural side reduces the party total). `days_past_due` = report date minus due date (negative = still to run). Fully settled bills are not listed. |
| `expected_ageing.csv` | `kind, row_type, party, not_due, 0-30, 31-60, 61-90, 90+, total` | `kind` = receivable / payable; `row_type` = `party` / `total`. Buckets by days past due date; items on the opposite side net off inside their bucket. |
| `expected_cash_book.csv` | `row_type, date, receipts, payments, closing_dr` | Cash ledger, `opening` / `day` (only days with entries) / `total`. |
| `expected_brs.csv` | `line_type, item_date, reference, description, amount` | BRS: books balance, reconciling items, bank-only items, computed and statement balance, `difference` (0.00 = ties). |
| `expected_matches.csv` | `bank_line_no, book_refs, how` | Which statement line (1-based row of `bank_statement.csv`) matches which voucher(s) (`V24+V25+V26`), `OPENING:<cheque>`, or nothing (bank only). |
| `expected_bank_only_drafts.csv` | `bank_line_no, txn_date, voucher_type, counter_ledger, amount` | Draft vouchers expected for the bank-only lines. |
| `expected_msme_due.csv` | `row_type, party, bill_ref, bill_date, msme_category, written_agreement, legal_days, legal_due_date, days_overdue, outstanding` | Flagged open bills (rule status PENDING); `item` / `total`. |

The sheet `VERIFICATION_SHEET.xlsx` is built from the pack files by `scripts/build_verification_sheet_p2.py`; the
pure self-check `backend/tests/acceptance/test_pack_p2_selfcheck.py` checks the pack's internal consistency with plain
Decimal arithmetic. The Phase 1 loader `pack_loader.py` does not read this pack (it needs `invalid_vouchers.csv`).
