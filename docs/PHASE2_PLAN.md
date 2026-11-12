# Phase 2 plan — Parties, bill-wise, cash and bank, Bank Reconciliation

Written 2026-11-12 under the working mode of CLAUDE.md section 6 (no approval wait). Scope: `docs/PHASE_PROMPTS.md` Phase 2.
Schema (migrations 0005–0007, seed 0002) is written FIRST and shared; engine/services/API/screens are built in parallel.
Interfaces: `docs/PHASE2_API_CONTRACT.md`.

## Steps

| Step | Builds | Owner agent |
| --- | --- | --- |
| 2.0 | Phase 1 follow-ups: reversal ignores the inactive-ledger check (V-05), `reactivate_ledger` (service + API). Migrations 0005–0007 + seed, models. | main |
| 2.1 | Party master (`engine/parties.py`, `services/parties.py`, API) | A |
| 2.2 | Bill-wise allocation on voucher lines; opening bills (`engine/bills.py`, `services/bills.py`, voucher service hooks) | A |
| 2.3 | Outstanding (receivable / payable) + ageing | A |
| 2.4 | Cash Book / Bank Book; no-negative-cash (C-01); duplicate payment (D-01) | B |
| 2.5 | MSME rule table loader, due flag (M-01) | B |
| 2.6 | Bank statement import, saved column mappings (`importers/bank_statement.py`, `services/bank.py`) | C1 |
| 2.7 | Auto + manual reconciliation (pure `engine/reconcile.py`), BRS (`engine/brs.py`), bank-only draft vouchers (`services/reconciliation.py`) | C2 |
| 2.8 | Screens (party, allocation in voucher entry, outstanding, ageing, cash/bank book, statement import, reconciliation, BRS, MSME) | D |
| 2.9 | Phase 2 test pack + hand WORKING.md + VERIFICATION_SHEET.xlsx + runner extension | E |
| 2.10 | Integration, full suite, acceptance report | main |

## New rule IDs (all error messages in accountant language, Indian number format, dd-mm-yyyy)

| ID | Rule |
| --- | --- |
| P-01 | GSTIN must be 15 characters in the GST format (format only; check digit comes in Phase 3) |
| P-02 | PAN must be 5 letters, 4 digits, 1 letter |
| P-03 | If both are given, characters 3–12 of the GSTIN must equal the PAN |
| P-04 | State code is 2 digits; if a GSTIN is given it must equal the GSTIN's first 2 digits |
| P-05 | MSME category micro/small/medium needs a valid Udyam number (`UDYAM-XX-00-0000000`) |
| P-06 | Credit days: whole number, not negative |
| P-07 | A party can only be a ledger under Sundry Debtors / Sundry Creditors |
| P-08 | Bill-wise cannot be switched on for a ledger that already has posted voucher lines without allocation, or whose opening balance is not covered by opening bills |
| B-01 | Every line of a bill-wise party ledger is allocated in full: sum of allocations = line amount (also on non-party lines: no allocations allowed) |
| B-02 | Allocation kind vs side: `new_ref` only on the party's natural side (debtor Dr / creditor Cr); `advance` only on the opposite side; `against_ref` must be on the side opposite to the bill it settles; `on_account` any side |
| B-03 | New bill/advance reference: required, unique per party (also against opening bills), case-insensitive, trimmed |
| B-04 | `against_ref` must name an existing posted bill of the same party and may not settle more than is outstanding: a bill never ends on the wrong side of zero (also checked on reversal, so a bill with receipts applied cannot be reversed first) |
| B-05 | Allocation amounts: positive, max 2 decimals (V-03 style); `due_date` not before the bill date |
| B-06 | Allocations are accepted only for party ledgers that exist as `parties` rows (otherwise B-01 does not apply: legacy Phase 1 behaviour) |
| B-07 | A voucher touching a bill-wise party cannot be posted while that party's opening bills do not add up to its opening balance (difference shown) |
| C-01 | Cash-in-hand can never be negative on any date: posting (or reversing) a voucher that makes the end-of-day balance of a cash ledger credit on ANY date in the financial year is refused, naming the first date and amount |
| D-01 | Possible duplicate payment: another Payment (any status except reversed) to the same party ledger with the same total within N days (default 7, constant `DUPLICATE_PAYMENT_DAYS`) → blocked unless `duplicate_override_reason` is given (same override field as V-10) |
| M-01 | MSME flag (report, not a block): open bill of a micro/small supplier past its legal due date |
| R-01 | Bank statement integrity: opening + credits − debits = closing, and where a running-balance column exists every row's balance agrees; any failure rejects the whole file naming the row |
| R-02 | Statement already imported (same file hash) or its dates overlap another statement of the same bank ledger |
| R-03 | A match item must be an unmatched, posted voucher line of that bank ledger / an unmatched bank line / an unmatched opening item |
| R-04 | A match must tie exactly: total book side (Dr deposits − Cr payments) = total bank side (credit − debit) |
| R-05 | BRS: balance as per books ± reconciling items must equal balance as per bank; otherwise the difference is shown and the BRS is marked "does not tie" |

## Design decisions (also logged in DECISIONS.md)
- Signed bill amounts: Dr +, Cr − (existing convention). Outstanding of a bill = sum over its allocations (new_ref/advance create, against_ref moves toward zero) + opening bill. Party ledger balance (period close) = sum of outstanding items incl. on-account — **tie check shown on the outstanding report**.
- A party ledger WITHOUT a `parties` row behaves exactly as in Phase 1 (no allocation). Creating the party row with `bill_wise=true` is the switch (P-08).
- Reversal vouchers get mirrored allocations (`against_ref` on the same reference with the opposite side; `on_account` mirrored) created by the service; B-02 and B-04's "cannot settle" parts are exempt, the "never wrong side of zero" check is not.
- Outstanding/ageing are computed inside one financial year (opening bills of the year + posted allocations up to the date); no carry-forward until Phase 6.
- Ageing buckets by days past due date as on the report date: `not_due` (due date after report date), `0-30`, `31-60`, `61-90`, `90+`. (Owner listed four buckets; "not due" is shown separately so nothing is hidden — confirm.) Due date = bill date + party credit days unless the allocation gives one.
- Cash balance is checked on end-of-day balances (same-day receipt and payment net off).
- Bank statement signs: statement "debit" = withdrawal, "credit" = deposit; book side: Dr to bank ledger = deposit. Matching is amount-equal with opposite wording (bank credit ↔ book Dr).
- Auto-match (deterministic, never guesses): rule 1 exact amount + same direction + reference/cheque no found in voucher reference or narration, date within window; rule 2 exact amount + date within window and exactly one candidate on each side; rule 3 one-to-many / many-to-one where the unique subset (max 6 items) sums exactly. Ambiguity → left unmatched, listed as a suggestion. Window default ±7 days (`RECON_DATE_WINDOW_DAYS`, not law).
- BRS as on D: books balance at D; reconciling items = book items dated ≤ D not matched or matched to a bank line dated after D (issued-not-presented = Cr items, deposited-not-cleared = Dr items); bank-only = bank lines dated ≤ D not matched (or matched to a voucher dated after D). Balance as per bank = statement balance at D (opening + movement of lines ≤ D). The BRS must tie to the paisa, else the difference is displayed.
- Bank-only drafts: the accountant chooses a counter ledger per bank line (keyword suggestions for "charges"/"interest" are a convenience); the tool creates a DRAFT Payment/Receipt (never posts) and records the link in `bank_line_drafts`.
- Database changes by agents: agents do NOT apply or edit migrations; they report a needed change to the main agent.

## Legal values to verify (none may be treated as verified until read from the official text)
| Value | Planned source | Status |
| --- | --- | --- |
| Payment time limit: 45 days max with written agreement, 15 days without (MSMED Act 2006 s.15) | indiacode.nic.in MSMED Act 2006 | **pending** — official sites returned errors to the research agent; secondary sources agree |
| Disallowance provision: Income-tax Act 1961 s.43B(h) (FY 2023-24 on, w.e.f. 1-4-2024) | incometaxindia.gov.in | **pending** (snippets only) |
| Matching provision in Income-tax Act 2025: s.37(2)(g), from 1-4-2026 | Act text on incometaxindia.gov.in / indiacode | **pending** — number from a secondary copy of a Rajya Sabha reply (21-07-2026) |
| Micro and small only; medium excluded | s.43B(h) Explanation | **pending** |
| Whether supplier must be Udyam-registered before the supply date | Ministry of MSME / CBDT | **unresolved**; the tool flags by category and Udyam number held, registration date not used |
| Acceptance day = bill date | MSMED s.15 | design assumption, owner/CA to confirm |
All stored in `msme_payment_rules` with `verification_status='pending'`. No other legal value is used in Phase 2 (ageing buckets, duplicate window, match window are configuration, not law).
