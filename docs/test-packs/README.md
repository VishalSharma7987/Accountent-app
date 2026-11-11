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
```

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
