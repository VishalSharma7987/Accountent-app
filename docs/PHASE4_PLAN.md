# Phase 4 plan - TDS / TCS (deductee master, deduction on vouchers, register, challans, interest, return data, certificates, 26AS / AIS reconciliation)

Written 2026-11-13 (planning agent) under the working mode of CLAUDE.md section 6. Scope: `docs/PHASE_PROMPTS.md` Phase 4. Interfaces: `docs/PHASE4_API_CONTRACT.md`.
Legal values and their status: `docs/PHASE4_LEGAL_VALUES.md` (**no value is `verified`**; official sites were not read; the blocking list for the owner / CA is section 5 there).
Schema (migrations 0012-0014, seeds 0008-0009) is written FIRST and is the shared contract: **agents never edit it**; a needed change goes to the main agent. Step 4.0 (this commit, branch `p4-plan`) applied the migrations and seeds to the TEST schema only; dev is applied by the main agent after merge and the test run.

## Law selection (owner requirement)
`event_date = min(payment_date, credit_date)` (the one that exists if only one). Act in force: `event_date <= 2026-03-31` -> Income-tax Act 1961; `>= 2026-04-01` -> Income-tax Act 2025 (392 salary, 393 table entries, 394 TCS). The pickers take the rule row in force on `event_date` (rows carry both the Act and the dates); no rule in force -> T-02 error, never a default. Old <-> new mapping = `tds_natures` + `tds_section_refs` (one row per Act per nature, payment code and table serial when verified). The Act, section, table serial and rule-row id of every deduction are copied into `tds_voucher_items` (a later rule change never rewrites history).

## Database design (migrations 0012-0014)
| Table | Kind | Purpose |
| --- | --- | --- |
| `tds_natures`, `tds_section_refs`, `tds_rates`, `tds_provisions`, `tds_due_dates`, `tds_interest_rules`, `tds_forms` | rule tables (system) | nature list; old <-> new section / table / payment code; rate by deductee group + thresholds (single, monthly, annual, `whole_amount` / `excess_only`) + no-PAN rate; other provisions with section refs; due-date patterns; interest per month; form numbers by Act |
| `clients.tan`, `tds_client_fy_flags` | client | deductor TAN; 194Q buyer-turnover flag per FY (entered, never guessed) |
| `tds_deductees` | master | PAN, PAN status (`valid`, `missing`, `invalid`, `applied_for`), deductee type, default nature; one row per party ledger |
| `tds_lower_deduction_certs` | master | certificate no, nature, rate (0 = nil), max amount, validity; used amount computed from items |
| `tds_ledger_roles` | master | TDS payable / TCS payable / receivables / interest / late-fee ledgers (default or per nature) |
| `tds_voucher_items` | per voucher | the engine's whole working per deduction (Act, section, rule id, event date, cumulative before / after, threshold crossed, base, rate, reason, certificate, tax, voucher line); draft-only guard (reuses Phase 3 `gst_voucher_child_guard`), immutable after posting; register = items of POSTED vouchers |
| `tds_challans`, `tds_challan_allocations` | post-posting | challans (BSR, date, serial, tax / interest / fee, total CHECK), allocation of tax to items; `locked` challans and their allocations are frozen by trigger |
| `tds_return_workings`, `tds_filed_returns`, `tds_certificates` | post-posting | versioned working snapshots (final = frozen), typed filed figures, certificate-data snapshots (never changed except number / issue date) |
| `tds_26as_imports`, `tds_26as_rows`, `tds_26as_links` | recon | imported statement rows (hash-unique per client), manual / accepted-difference links |
All money `numeric(18,4)` + round CHECK; rates `numeric(7,4)`; RLS on, no policies; closed grants; function privileges revoked at the end of 0013 and 0014.

## Steps
| Step | Builds | Package |
| --- | --- | --- |
| 4.0 | Migrations 0012-0014, seeds 0008-0009 (applied to TEST), `engine/tds_types.py`, `services/tds_hooks.py` stubs, empty routers `api/tds_*.py` registered in `main.py`, schema tests, three docs | main (done) |
| 4.1 | PAN rules, deductee master, certificates, ledger roles, TAN / flags, rule-table loaders and pickers by date with status roll-up, old <-> new map endpoints | A |
| 4.2 | Pure TDS engine: nature + deductee group + rate by date, thresholds (single / monthly / annual, `whole_amount` catch-up, `excess_only`), no-PAN rate, lower / nil certificate (validity, limit, partial use), rounding, per-deductee per-FY position, TCS entries | B |
| 4.3 | Voucher integration: `tds` block on Payment / Purchase / Journal, generated payable line, hooks into `services/vouchers.py`, TDS register, threshold position, tds-preview | B |
| 4.4 | Challan entry, allocation, matching proposal, due dates, interest for late deduction / deposit, due calendar | C |
| 4.5 | Return working (24Q/26Q/27EQ vs 138/140/143 by quarter-end date), finalise, filed figures, certificate data and snapshots, Excel / JSON export | D |
| 4.6 | 26AS / AIS import (Excel / CSV), reconciliation with the register and with TDS receivable vouchers, manual links | E |
| 4.7 | Screens | F |
| 4.8 | Phase 4 test pack + hand `WORKING.md` + `VERIFICATION_SHEET.xlsx` + runner | G (after merge) |
| 4.9 | Integration, full suite, acceptance report (both Acts, threshold crossing mid-year, missing PAN, lower-deduction certificate) | main |

## Dependencies (honest)
- Everyone needs 4.0 (schema applied, `tds_types.py`, hook stubs). Nobody edits migrations, seeds, `tds_types.py` signatures or `main.py` after 4.0.
- A is independent. B's engine unit tests use literal rule objects (no A); B's service tests need A's loaders and masters: merge A before B's integration tests run.
- C's engine (due dates, interest, matching proposal) is pure and independent; its service tests need B (posted items) and A (rule loaders).
- D's engine / unit tests are independent (plain rows); service tests need B and C. E's parser and matcher unit tests are independent; service tests need B (items) and A.
- F builds against the contract with mocked responses. G starts after A-E are merged and the main agent ran the full suite.
- **Merge order: A -> B -> C -> D -> E -> F -> G.** Branches `p4-A` ... `p4-G`.
- `services/tds_hooks.py`: owned by B after 4.0 (bodies; B adds the calls in `services/vouchers.py` once). C may add logic to `on_reverse` ONLY through a function `services/tds_challans.py::on_reverse_check(conn, client_id, voucher_id)` that B's hook calls (lazy import guarded like Phase 3), so B and C never edit the same file.

## File ownership (no two packages edit the same file; each writes tests in NEW files named for its area under `backend/tests/{unit,integration}/`; decision rows in `docs/decisions_parts/<pkg>.md`, status in `docs/progress_parts/<pkg>.md`)
| Package | Owns (create / edit) | Must not touch |
| --- | --- | --- |
| main (4.0, 4.9) | `database/**`, `engine/tds_types.py` (signatures), `app/main.py`, `tests/unit/test_migrate.py`, `tests/integration/test_schema_guards.py`, `tests/integration/test_tds_schema.py`, `docs/PROGRESS.md`, `docs/DECISIONS.md`, the three PHASE4 docs | |
| A | `engine/tds_masters.py`, `rules/tds_rules.py`, `services/tds_masters.py`, `db/repositories_tds_masters.py`, `api/tds_masters.py`, `api/schemas_tds_masters.py`, tests `tests/unit/engine/test_tds_masters.py`, `tests/unit/rules/test_tds_rules.py`, `tests/integration/test_tds_masters_db.py` | vouchers, bills, gst |
| B | `engine/tds_calc.py`, `engine/models.py` (add optional `tds` field to `VoucherDraft`; nothing else), `engine/validation.py` (one call), `services/tds_deduction.py`, `services/tds_hooks.py` (bodies), `services/vouchers.py` (hook calls only), `services/voucher_import.py` (optional TDS columns, only if time), `db/repositories_tds_deduction.py`, `api/tds_deduction.py`, `api/schemas_tds_deduction.py`, `api/vouchers.py` (the `tds` extension), tests | challans, returns |
| C | `engine/tds_challan.py` (allocation, matching, due dates, interest), `services/tds_challans.py` (incl. `on_reverse_check`), `db/repositories_tds_challans.py`, `api/tds_challans.py`, `api/schemas_tds_challans.py`, tests | vouchers.py, tds_hooks.py |
| D | `engine/tds_returns.py`, `engine/tds_certificates.py`, `services/tds_returns.py`, `services/tds_export.py`, `db/repositories_tds_returns.py`, `api/tds_returns.py`, `api/schemas_tds_returns.py`, tests | |
| E | `importers/form26as.py`, `engine/tds_recon.py`, `services/tds_recon.py`, `db/repositories_tds_recon.py`, `api/tds_recon.py`, `api/schemas_tds_recon.py`, `tests/fixtures/tds26as/*`, tests | register schema |
| F | `frontend/src/tds/**`, `frontend/src/api/tds.ts`, one router / menu entry | backend |
| G | `docs/test-packs/phase4-*/**`, `backend/tests/acceptance/pack_loader_p4.py`, `pack_runner_p4.py`, `scripts/build_verification_sheet_p4.py` | engine, services |
Parallel start: A first (small); then B, C-engine, D-engine, E-parser/matcher together using literal rule objects; service and integration tests of B..E wait for A (and B for C/D/E). DB runs always through `scripts/dbrun.sh`.

## Engine rules (messages in accountant language, Indian number format, dd-mm-yyyy; each error carries `rule_id` and, where it applies, `line_no` = the item number)
Deduction (package B unless noted)
| ID | Rule |
| --- | --- |
| T-01 | Event date = the earlier of payment and credit date; at least one is required; it decides the Act |
| T-02 | A rate rule must be in force on the event date for the nature and deductee group; otherwise refuse ("no rule for 194C on 10-03-2025"); a rule with status `pending` is used but the result carries a warning and `rule_status` |
| T-03 | Nature must exist, be of kind tds (or tcs for a TCS block); salary (slab_manual) needs `manual_tax`, every other nature refuses `manual_tax` |
| T-04 | Rate by deductee group: individual / HUF vs others (company, firm, LLP, AOP, society, trust, local authority, other); group `any` rows apply to all |
| T-05 | Tax amount, rate and tax ledger typed by the caller are refused; the engine computes the amount from the rule table |
| T-06 | Tax is rounded to the nearest rupee, half-up, in ONE shared helper (`engine/money.py` style); tested with literal values (provision 288B pending) |
| T-07 | Thresholds per deductee + nature + financial year: single payment, monthly (rent), annual; below all thresholds: tax 0 and reason `below_threshold`; `whole_amount`: from the payment that crosses a threshold the base is the cumulative amount of the year (catch-up of earlier untaxed payments, less tax already deducted); `excess_only`: base is the part above the threshold |
| T-08 | PAN missing / invalid / applied-for: use `no_pan_rate` (never the lower of the two); a valid certificate does not override a missing PAN unless the accountant records the certificate (the cert rate is applied only when the PAN is valid) |
| T-09 | The deductee ledger must have a deductee row, belong to the client and be active; nature must be allowed for the deductee's type (194M: individual / HUF payer note; 194T: firm-partner relation is the accountant's declaration) |
| T-10 | PAN format `AAAAA9999A`; status `valid` / `invalid` need a PAN, `missing` / `applied_for` carry none |
| T-11 | The 4th PAN letter must fit the deductee type (P individual, H HUF, C company, F firm, A AOP/BOI, T trust, L local authority, J artificial person ...); mismatch is a warning, not an error |
| T-12 | Lower-deduction certificate: in validity on the event date, nature fits, rate < normal rate, amount used + this payment <= `max_amount`; the part above the limit is taxed at the normal rate; rate 0 = nil deduction (reason `nil_certificate`) |
| T-13 | At approve and post the engine re-runs on the stored draft; stored amounts that differ from the recomputation block posting (tamper check) |
| T-14 | Ledger roles: the payable ledger must exist for the nature (or the default) before any tax line is generated; wrong group refused |
| T-15 | A draft that deducts needs the 194Q buyer flag for the FY when the nature is `purchase_of_goods` (missing flag = refuse, no guess) |
| T-16 | Amounts: 2 decimals max, > 0; the payable line never exceeds the party line |
| T-17 | TCS (kind tcs): the same engine on the collection side (Cr TCS payable); nature + amount tiers only as seeded (overseas-tour 20% tier refused as manual) |
Challans, due dates, interest (package C)
| ID | Rule |
| --- | --- |
| T-20 | Challan: BSR code 7 digits, serial 1-5 digits, total = tax + interest + fee + other; the CIN (BSR + date + serial) is unique per client |
| T-21 | Allocation applies tax of a challan to items of the same kind; item must be in a POSTED, non-reversed voucher of the client |
| T-22 | Challan `quarter` and `financial_year` must contain the deducted month (a deposit never precedes the deduction month) |
| T-23 | Sum of allocations of a challan <= its tax amount |
| T-24 | Sum of allocations of an item <= its tds_amount (never over-allocate) |
| T-25 | A voucher with an allocated item cannot be reversed (remove the allocation first); a locked challan cannot change |
| T-26 | Interest for late deduction = items x `late_deduction` monthly rate x months (part of a month = full month) from the date the tax was deductible to the date deducted; computed from rule data, whole rupees, shown not posted |
| T-27 | Interest for late deposit = tax x `late_deposit` monthly rate x months from the deduction date to the deposit date (or `as_on` when undeposited) |
| T-28 | Due date of deposit by pattern (7th of next month; March -> 30 April); calendar of challan / return / certificate dates by pattern |
Returns, certificates (package D)
| ID | Rule |
| --- | --- |
| T-30 | Return working needs the client's TAN; PAN of every deductee (a row without a valid PAN is listed as an error row, with the higher-rate reason) |
| T-31 | Form number chosen by the quarter-END date and the Act in force (24Q / 26Q / 27EQ up to Q4 FY 2025-26, 138 / 140 / 143 after); status shown |
| T-32 | Total deposited (allocated) must be at least the tax deducted of the quarter, else warn per item (short payment, interest due) |
| T-33 | A final working locks its challans; a new version is a new row |
| T-34 | A certificate is produced only for items fully allocated to deposited challans of the quarter; one snapshot per version |
26AS / AIS (package E)
| ID | Rule |
| --- | --- |
| T-40 | Import file: known columns only, amounts max 2 decimals, dates parsed; unknown shape rejected with row-wise messages (no silent skipping) |
| T-41 | The same file (hash) cannot be imported twice for a client |
| T-42 | Matching = PAN / TAN + section mapped through `tds_section_refs` (old or new code) + amount within tolerance + month; classes matched, amount_mismatch, only_in_books, only_in_26as, date_mismatch |
| T-43 | An unmapped section or unknown PAN is reported (never guessed); a manual link and an accepted difference each need a note |
All packages
| ID | Rule |
| --- | --- |
| T-50 | Every output carries `rule_status` (worst verification status per rule table used) and lists the pending sources |

## Accountant cases for the Phase 4 pack (package G; hand-worked, literal expected values)
Both Acts (payment dated 20-03-2026 vs 05-04-2026 for the same nature); contractor individual vs company; annual aggregate crossing mid-year (catch-up on the crossing payment); single payment above the threshold; professional fees below threshold; 194Q excess-only; rent per month; missing PAN (20% vs 5% natures); lower-deduction certificate with a limit that runs out mid-year; nil certificate; payment credited in March and paid in April (earlier date decides); challan paid late (interest working); short deposit; quarterly working and certificate data; 26AS with one matched, one mismatched, one missing row.

## Risks and non-goals
- All legal values pending (see PHASE4_LEGAL_VALUES.md): the pack states this; the owner / CA signs the hand workings.
- Out of scope (suggestions): non-resident payments (195 / Table 2) and Form 15CA/CB, Form 141 challan-cum-statement schedules (property / rent / VDA), late-fee 234E working, payroll / slab computation for salary, TRACES / FVU file generation, 194IA / 194IB / 194N / 194R / 194S, penal provisions 271H.
