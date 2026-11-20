# Progress log

Five lines per finished step (see CLAUDE.md section 6).

## Phase 0
- Steps 0.1, 0.2, 0.3: done (commits e49a833, 2ab24a8, 39685e8). One Supabase project, schemas `public` (dev) and `ledgermind_test`.

## Phase 1
- **1.1** done: migration 0003 (accounting core, guards) + seed (23 groups); 123 guard tests; commit 3746715.
- **0004** done: exact money (NUMERIC(18,4)+round check), API grants closed, unit/integration test split; commit 1285d17.
- **1.2** done: pure engine `money.py`, `models.py`, `validation.py` (V-01..V-09, V-13, V-14), `duplicates.py` (V-10); pack format gets `party_ledger`; template wrong vouchers X04 (V-13), X05 (V-14) run through the real engine; tests: see commit; decisions: 6 rows added (1.2).
- **1.2** commit 7a4db8b (422 tests passed).
- **1.3** done: pure `engine/reports.py` (ledger statement with running Dr/Cr balance, Trial Balance with group subtotals and explicit difference); mini case verified by hand incl. reversal (Cash 35,000 Dr, Rent 0); 34 new tests; decisions: 5 rows (1.3).
- **1.3** commit 9ca24c3 (456 tests passed).
- **1.4** done: `engine/coa_templates.py` (27 tests), `reports.check_openings`, `db/engine.py` (schema-pinned SQLAlchemy engine), `db/repositories.py`, `services/{errors,audit,client_setup}.py` (create_client, add_ledger, deactivate_ledger, set_opening_balance, opening_balance_difference); 41 integration tests; 6 decisions added.
- **1.4** commit 30ca85d (528 tests passed).
- **1.5** done: `services/vouchers.py` (create_draft, update_draft, delete_draft, approve, return_to_draft, post with gapless numbers, reverse, get_voucher); engine `is_reversal` flag; one-query context/voucher loaders; 51 integration tests incl. 6-thread concurrency and rollback-gives-number-back; 8 decisions added; speed: services use no savepoints, shared module worlds.
- **1.5** commit 0c805cd (583 tests passed).
- **1.6** done: `services/periods.py` (lock/unlock/list), `services/reports.py` (statement, Trial Balance via the pure engine), repository loaders; 24 integration tests including the Step 1.3 mini case loaded through the services (TB Dr 5,65,000 = Cr 5,65,000; reversal leaves Cash 35,000, Rent nil); 3 decisions added.
- **1.6** commit 40a631b (607 tests passed).
- **1.7 / 1.8 / 1.9 / 1.10** built in parallel worktrees (DB runs serialised by scripts/dbrun.sh), merged into main: API (44 tests), Excel import (48 unit + 21 integration + 5 API), web screens (23 vitest, build ok), ABC Traders pack (30 vouchers + 1 reversal, 16 wrong vouchers, TB 13,54,460.00 both sides, tool = hand workings) with acceptance runner (5 tests). Router `imports` wired in main.py. Decisions: 7 rows added. Full-suite gate result follows.
- **1.7-1.10 gate** commit 1e6d9f0: full suite 760 passed (unit + integration incl. API, import, pack runner), ruff clean; frontend `npm run build` ok, vitest 23 passed. One merge bug fixed (import used a text client id where the engine compares UUIDs).
- **Phase 1 acceptance check** run on 2026-11-12: see the report given to the owner; accountant SIGNOFF.md files are pending. Phase 2 NOT started.
### Steps 2.1-2.3 (agent A): party master, bill-wise allocation + opening bills, outstanding + ageing
- Done: engine/parties.py (P-01..P-07), engine/bills.py (B-01..B-05, due dates, open bills, mirrored allocations, opening-bills check, ageing), services/parties.py (P-08), services/bills.py, db/repositories_bills.py, voucher hooks (draft/approve/post/reverse, B-07), API parties + bills, allocations on voucher lines.
- Tests: unit 22 (parties) + 57 (bills, ageing); integration 9 in tests/integration/test_bill_wise.py (services, voucher flow, reversal, DB trigger, API).
- Commit: see git log of branch p2-A.
- Decisions added: see docs/decisions_parts/A.md (9 rows). Contract edits: docs/PHASE2_API_CONTRACT.md (Parties, Bill-wise).

Step 2.4-2.5 (agent B): Cash/Bank Book (engine/cashbook.py, services/cashbook.py, GET reports/cash-book), C-01 no-negative-cash (engine/cash_rules.py, services/cash_checks.py hooked into approve/post/reverse), D-01 duplicate payment (engine/payments.py), M-01 MSME flag (engine/msme.py, rules/msme.py, services/msme.py, GET reports/msme-due).
Tests: 38 new unit tests (tests/unit/engine/test_cashbook|cash_rules|payments|msme.py) + 8 integration (tests/integration/test_cash_book_rules.py).
Rule table msme_payment_rules: all 6 seed rows verification_status='pending'; reports show rule_status/rule_source.
Shared-file edits: services/vouchers.py (4 one-line hooks), main.py (2 routers).
Commit: branch p2-B.

Step 2.6 (C1): bank statement import, formats, listing, delete.
Done: importers/bank_statement.py (pure parser, R-01), services/bank.py (R-02, audit), api/bank.py + schemas_bank.py, router in main.py.
Tests: 21 unit (parser) + 8 integration (service + API); ruff clean.
Commit: on branch p2-C1.
Decisions added: 5 (docs/decisions_parts/C1.md).

- Step 2.7 (agent C2): bank reconciliation.
- Done: engine/reconcile.py (auto_match rules 1-3, validate_match R-03/R-04), engine/brs.py (BRS, R-05), services/reconciliation.py (unmatched, auto/manual match, unmatch, opening items, BRS, bank-only suggestions and DRAFT vouchers), API app/api/reconciliation.py + schemas_recon.py.
- Tests: tests/unit/engine/test_reconcile.py + test_brs.py (38 unit); tests/integration/test_reconciliation.py (5 integration, mini case + raw-SQL statements).
- Commit: on branch p2-C2 (see git log).
- Decisions added: docs/decisions_parts/C2.md (BRS signs, settled matches, FY scope, reference matching, drafts all-or-nothing).

- Step 2.8 (agent D): screens Parties, Opening bills, Outstanding+Ageing, Cash/Bank book, MSME dues, Bank (formats/import/statements), Reconciliation, BRS; AllocationEditor in VoucherEntry.
- Done: typed against docs/PHASE2_API_CONTRACT.md (api.ts/types.ts appended); pure helpers in frontend/src/lib/phase2.ts.
- Tests: vitest 55 passed (22 new in lib/phase2.test.ts); `npm run build` (tsc -b + vite) passes. Not run against a live backend.
- Commit: branch p2-D.
- Decisions added: 4 rows in docs/decisions_parts/D.md.

- **Phase 2 foundation** (2.0): follow-ups, migrations 0005-0007, plan docs/PHASE2_PLAN.md; commit 119b0ab. Steps 2.1-2.8 built by parallel agents and merged (see parts above). Full-suite gate and runner (2.9/2.10) follow.
Step 2.9 (runner part): Phase 2 acceptance runner for abc-traders-phase2-jun-2026.
Done: tests/acceptance/pack_loader_p2.py, pack_runner_p2.py, test_pack_runner_p2.py (integration), test_pack_runner_p2_helpers.py (unit).
Tests: helpers 10 unit tests pass; integration run: 16 passed (all 15 sections + counts) in ~5 min.
Commit: on branch p2-R.
Decisions added: 3 (decisions_parts/R.md).
- **Phase 2 gate**: full suite 991 passed (before runner) + Phase 2 pack runner 16 passed + Phase 1 runner 5 passed; unit 618 passed; ruff clean; frontend build ok, vitest 55 passed. Migrations 0005-0007 + seed 0002 applied to test and dev. Phase 3 NOT started.
- Step 2.1-I: Excel voucher import bill allocation columns (parser, service auto New Ref, API, template notes, ImportScreen, API_CONTRACT).
- Done: bill_type/bill_ref/bill_amount/due_date columns, continuation rows, auto New Ref (Sales/Purchase) flagged in preview and commit.
- Tests: unit importers (parsing/template) + integration test_voucher_import_bills.py, updated test_api_imports.py.
- Commit: branch p21-I.
- Decisions added: 3 rows in docs/decisions_parts/I.md.

Phase 2.1 agent K: (a) newest-first statements detected from running balances, (b) Cr/Dr balance text, (c) GET reconciliation matches endpoint + Reconciliation screen.
Done: parser (importers/bank_statement.py), notes in preview/import, services/reconciliation.list_matches, API + schemas, frontend types/api/screens, contract doc.
Tests: unit tests/unit/importers/test_bank_statement_orient.py; integration tests/integration/test_recon_matches.py + updated test_bank_statements.py; vitest phase2.test.ts (57 pass), npm build ok.
Commit: branch p21-K (see final report).
Decisions added: 4 rows in docs/decisions_parts/K.md (replaces the 2.6 "file order, no re-sorting" decision).

Phase 2.1 step M (MSME rule corrections + acceptance date), branch p21-M.
Done: migration 0008 + seed 0003, party fields (P-09/P-10/P-11), goods_received_date (V-15) through service/API/frontend, MSME engine (activity, Udyam date, acceptance basis, 3-valued status), pack + runner + docs.
Tests: unit suite green (634 passed); integration/pack runner see the final report.
Commit: on branch p21-M.
Decisions added: docs/decisions_parts/M.md (8 rows).


- Step 3.0 (GST foundation, backend only): migrations 0009-0011 + seeds 0004-0007 applied to TEST schema; `engine/gst_types.py`, hook stubs, 5 empty routers registered; package ownership in docs/PHASE3_PACKAGES.md.
  Tests: new tests/integration/test_gst_schema.py, table list in test_schema_guards, seed list in test_migrate (see commit). Full suite deliberately NOT run (owner instruction).
  Commit: p3-plan (see git log). Decisions added: 3 rows. Dev schema NOT migrated yet.

<!-- Phase 3 + Phase 4 package status (folded from progress_parts) -->
<!-- progress_parts/A.md -->
Step 3.1 (package A, branch p3-a): GSTIN (G-01..G-04 incl. mod-36 check char), registrations + ledger roles (G-05, G-06, G-08), item master (G-07), rule loaders/pickers for all nine tables, masters API, party `gst_registration_type`.
Done: engine/gstin.py, engine/gst_masters.py, engine/parties.py (new field + G hand-over), rules/gst_rules.py, db/repositories_gst_masters.py, services/gst_registrations.py + gst_items.py + parties.py (new field), api/gst_masters.py + schemas_gst_masters.py (+ one field in schemas_bills.py / api/parties.py).
Tests: unit (gstin, masters, party, rules) added to the 633-test unit run (all pass); 6 integration tests in test_gst_masters_db.py pass via dbrun.sh; `ruff check .` clean. The full suite was NOT run (owner's instruction).
Commit: on branch p3-a (not merged).
Decisions added: see docs/decisions_parts/A.md (parties do not yet use the check digit: Phase 2 fixtures use an invalid check character).

<!-- progress_parts/A4.md -->
Step 4.1 (package A): TDS masters.
Done: PAN / TAN / certificate / ledger-role rules (engine/tds_masters.py), rule loaders and pickers by date with status roll-up (rules/tds_rules.py), repository, service, API (profile, FY flags, deductees, certificates, ledger roles, rule tables, rate lookup, section map).
Tests: unit engine 25 + rules 11 (all unit suite 865 passed); integration tests/integration/test_tds_masters_db.py 4 passed via dbrun.sh; ruff clean.
Commit: branch p4-a (see report). Shared edit: api/errors.py one line (no_rule, allocation_exceeds are 422).
Decisions added: docs/decisions_parts/A4.md (7 rows).

<!-- progress_parts/B.md -->
Step 3.2 / 3.3 (package B): pure tax engine `engine/gst_tax.py` and invoice mode `engine/gst_invoice.py` (G-06, G-08, G-10..G-26, G-30 flags), API (`gst` block on the voucher endpoints, `POST /clients/{c}/vouchers/gst-preview`), hooks in `services/vouchers.py` and bodies of `services/gst_hooks.py`.
Tests: 77 engine unit tests (hand-calculated), 5 API / Excel parser unit tests, 5 new integration tests (create -> approve -> post -> reverse, G-26, G-23, RCM purchase, Excel import); full suite NOT run (owner rule); unit run 767 passed; ruff clean.
Done: Sales, Purchase, Credit Note, Debit Note in invoice mode; CGST / SGST / IGST / cess, RCM, blocked credit flag (tax into cost), zero-rated LUT, round-off option, composition client bill of supply; preview; Excel item rows.
Gaps: G-02 check digit for invoices waits for package A (`InvoiceContext.gstin_check`); purchases of composition clients refused; no schema change requested.
Decisions: docs/decisions_parts/B.md (19 rows).

<!-- progress_parts/B4.md -->
Step 4.2 + 4.3 (package B): pure TDS / TCS engine `engine/tds_calc.py` (T-01 .. T-12, T-15 .. T-17, T-50, `round_tax`, `expand_lines`), deduction service + hook bodies, T-13 recheck, register / by-deductee / threshold-position / tds-preview endpoints, `tds` block on the voucher endpoints.
Tests: `tests/unit/engine/test_tds_calc.py` (56, hand-calculated: law by date 31-03 / 01-04-2026, earlier-of-two-dates, threshold crossing, excess only, monthly rent, no PAN, certificate limit / nil / validity, rounding, TCS), `tests/unit/test_tds_input.py` (5), `tests/integration/test_tds_deduction_db.py` (13).
Files: engine/tds_calc.py, db/repositories_tds_deduction.py, services/tds_deduction.py, services/tds_hooks.py (bodies), api/tds_deduction.py, api/schemas_tds_deduction.py; shared: engine/models.py (VoucherDraft `tds`, `tds_results`), services/vouchers.py (hook calls), api/vouchers.py + api/schemas.py (tds field in / out).
Decisions: docs/decisions_parts/B4.md. Gaps: TDS on GST invoice-mode vouchers refused; register due dates null (package C); voucher_import TDS columns not built.
Dependencies: integration tests insert masters with SQL (no package A needed); `on_reverse_check` of package C is called only once that module exists.

<!-- progress_parts/C.md -->
Step 3.4/3.5 (package C, ITC register): engine/gst_itc.py (classify, deadline, 180-day share, reversal/reclaim arithmetic), services/gst_itc.py (on_post, on_reverse, evidence, confirm, tag-blocked, apply_2b_result for D, set_claimed_period for E, exposure, reversal/reclaim drafts, register tie), repository, API + schemas.
Tests: 32 engine unit tests; 6 integration tests in tests/integration/test_gst_itc_register.py run via dbrun.sh (pass). Full suite NOT run (owner instruction). ruff clean.
Dependencies: B must call hooks on post/reverse (integration tests call on_post by hand); A for registrations/ledger roles (tests insert them by SQL).
Decisions: docs/decisions_parts/C.md. Pending legal: 180-day formula, Section 16(4) annual-return clause, RCM credit timing, 17(5) rows.

<!-- progress_parts/C4.md -->
Step 4.4 (package C): challans, allocation, matching proposal, due dates, interest, due calendar, on_reverse_check.
Done: engine/tds_challan.py, db/repositories_tds_challans.py, services/tds_challans.py, api/tds_challans.py + schemas_tds_challans.py; contract notes in decisions_parts/C4.md.
Tests: tests/unit/engine/test_tds_challan.py (47) and tests/integration/test_tds_challans.py (8, items inserted with raw SQL; B / A not needed).
Commit: see git log of branch p4-c.
Decisions added: 8 rows in decisions_parts/C4.md (interest dates, months, due rules, calendar status, error shapes).

<!-- progress_parts/D.md -->
Step 3.6 (package D, branch p3-d): GSTR-2B import and reconciliation.
Done: importers/gstr2b.py (JSON + Excel, strict), engine/gst_recon.py, repository, service, API + schemas, hand-made fixtures.
Tests: unit 30 passed (engine 18, importer 12); integration tests/integration/test_gst_recon.py 3 passed via dbrun.sh; ruff clean; full suite NOT run (owner instruction).
Commit: see git log of p3-d. Open: a real GSTR-2B JSON/Excel and an IMS sample from the owner; C's apply_2b_result hook.
Decisions added: 9 rows in docs/decisions_parts/D.md.

<!-- progress_parts/D4.md -->
Step 4.5 (package D, branch p4-d): quarterly return working, certificate data, filed figures, Excel / JSON export (T-30 .. T-34, T-50).
Done: engine/tds_returns.py, services/tds_returns.py + tds_export.py, db/repositories_tds_returns.py, api/tds_returns.py + schemas_tds_returns.py.
Tests: 24 unit tests (engine + export) pass; 6 integration tests in test_tds_returns_db.py pass via dbrun.sh (raw SQL items / challans, so they need only 0012-0014); `ruff check .` clean. Full suite NOT run.
Commit: on branch p4-d (not merged).
Decisions added: docs/decisions_parts/D4.md (PAN rows non-blocking, challan selection, stale-working refusal, own-structure exports).

<!-- progress_parts/E.md -->
Step 3.7-3.8 (package E: GSTR-1, GSTR-3B, tie-out, composition, exports)
Done: pure engines gstr1/gstr3b/gst_tieout/composition, repository, services gst_returns + gst_export (Excel, portal-shape JSON), API + schemas, versions/finalise/filed figures, audit log
Tests: 44 new unit tests (engine, export round trip) + 4 integration tests (tests/integration/test_gst_returns.py via dbrun.sh); ruff clean; FULL SUITE NOT RUN (owner forbids); needs A (registrations, party type), B (voucher_gst/item rows), C (itc_entries/itc_reversals): tests build those rows with raw SQL, real flow untested until merge
Gaps: reclaim journals not in 4(A); Rule 38/42/43, ISD, amendments (GSTR-1 table 9) absent; JSON shape and table numbers unverified against the portal
Commit: branch p3-e; decisions in docs/decisions_parts/E.md

<!-- progress_parts/E4.md -->
Step 4.6 (package E): 26AS / AIS import and reconciliation.
Done: `importers/form26as.py` (strict CSV / xlsx parser), `engine/tds_recon.py`, `db/repositories_tds_recon.py`, `services/tds_recon.py`, `api/tds_recon.py` + `schemas_tds_recon.py`, fixtures `tests/fixtures/tds26as/`.
Tests: unit 24 (9 parser T-40, 15 engine T-42/T-43); integration 4 (`tests/integration/test_tds_recon_db.py`); ruff clean.
Commit: see git log of branch p4-e. Dependencies: none on A..D code (raw SQL on tds_section_refs / tds_deductees / tds_voucher_items / tds_ledger_roles); real use needs A's masters and B's posted items.
Decisions added: docs/decisions_parts/E4.md (layout unverified: a real 26AS / AIS sample file is needed).

<!-- progress_parts/F.md -->
- Step 3.F (frontend GST), branch p3-f.
- Done: api/gst.ts; screens Registrations (live GSTIN check, ledger roles), Items, Rules viewer, InvoiceGstPanel + GST invoice, ITC register (evidence, confirm, tag blocked, events, 180-day, reversals, ledger tie), 2B import/reconciliation, GSTR-1, GSTR-3B, Tie-out, Composition, Workings; GST nav group + routes.
- Tests: vitest 71 passed (gst/lib.test.ts added, nav test covers new routes); `npm run build` ok. Not run against a real backend.
- Commit: see git log on p3-f.
- Decisions added: docs/decisions_parts/F.md (6 rows).

<!-- progress_parts/F4.md -->
- Step 4.7 (frontend TDS), branch p4-f.
- Done: api/tds.ts; screens Deductees (PAN status, certificates, ledger roles, TAN and 194Q flag), Rules viewer (1961<->2025 map, pending badges), TdsPanel + Voucher with TDS (tds-preview, threshold headroom), Register (+by deductee, Excel), Challans (entry, allocation, auto-propose, interest, due calendar), Returns (working, versions, finalise, export, certificates), 26AS import + reconciliation + links; TDS nav group + 7 routes.
- Tests: vitest 78 passed (tds/lib.test.ts added, nav test covers new routes); `npm run build` ok. Not run against a real backend (mocked contract only).
- Commit: see git log on p4-f.
- Decisions added: docs/decisions_parts/F4.md (7 rows).

<!-- progress_parts/G.md -->
Step 3.10 (package G, branch p3-g): Phase 3 accountant test pack `docs/test-packs/phase3-sunrise-traders-apr-2026/` (client.yaml, ledgers/parties/registrations/items/roles, 14 invoice-mode vouchers, payments, two GSTR-2B JSON files, ITC evidence/claims, 8 wrong cases, composition client, 16 expected_*.csv, WORKING.md, SIGNOFF.md, VERIFICATION_SHEET.xlsx from `scripts/build_verification_sheet_p3.py`).
Done: `pack_loader_p3.py`, `pack_runner_p3.py` (17 sections), `test_pack_runner_p3.py` (integration), `test_pack_p3_selfcheck.py` (7 unit tests), `test_pack_runner.py` skips the Phase 3 pack.
Tests: see the final report (pack runner via dbrun.sh; unit self-check; P1 and P2 runner tests; `ruff check .`). The full suite was NOT run (owner's instruction).
Commit: on branch p3-g (not merged).
Decisions added: see docs/decisions_parts/G.md. Findings (pack vs tool differences) are listed in the final report and are not hidden by editing the pack.

<!-- progress_parts/G4.md -->
Step 4.8 (package G): Phase 4 test pack, hand workings, sign-off, verification sheet, acceptance runner.
Done: `docs/test-packs/phase4-greenfield-contractors-2026/` (inputs, 14 expected_*.csv, WORKING.md, SIGNOFF.md, VERIFICATION_SHEET.xlsx via `scripts/build_verification_sheet_p4.py`), `tests/acceptance/pack_loader_p4.py`, `pack_runner_p4.py`, `test_pack_runner_p4.py`, `test_pack_p4_selfcheck.py`; `test_pack_runner.py` skips packs with deductees.csv.
Tests: unit self-check 8 pass; P4 runner (locked, once) 14 of 15 sections pass, the 15th differed only by a typo in the expected total (fixed, same value the tool gave); ruff clean.
Commit: see git log of branch p4-g (not merged).
Decisions added: docs/decisions_parts/G4.md (two FYs, 26AS Deductee PAN column, blended certificate rate left blank).

<!-- progress_parts/P4.md -->
Step 4.0 (planning + foundation, branch p4-plan): Phase 4 plan, API contract, legal values sheet; migrations 0012-0014 and seeds 0008-0009 (TDS/TCS rule tables, deductee master, items, challans, returns, certificates, 26AS tables).
Done: `engine/tds_types.py`, `services/tds_hooks.py` stubs, empty routers `api/tds_{masters,deduction,challans,returns,recon}.py` registered in `main.py`, `test_migrate.py` seed list, `test_schema_guards.py` table list, `test_tds_schema.py`.
Tests: unit tests, `ruff check .`, and the schema / guard / grant integration tests only (see the report); the full suite was NOT run (owner's instruction).
Commit: on branch p4-plan (not merged). Migrations applied to the TEST schema only; dev is applied after merge.
Decisions added: see docs/decisions_parts/P4.md. Legal values: none verified, see docs/PHASE4_LEGAL_VALUES.md section 5.


Step 4.1 (owner orders 2026-11-13, branch p41): TDS on GST invoices (T-18), per-payment catch-up at the crossing, certificate rate + effective rate, rent by the deductor's profile (T-19, ex-194-IB), interest / rounding / GST-base provisions as secondary_verified.
Done: engine (`tds_calc.py`, `tds_types.py`), G-26 made TDS-aware, migration 0015 (`tds_deductor_fy_profile`, `pan_status_at_event`), seed 0011, API + services + frontend (profile flag, both rates, TDS block on the GST purchase invoice), pack addendum `p41/` + WORKING.md + verification sheet.
Tests: unit tests + ruff + frontend build / vitest in the worktree; DB tests NOT run by the author (database busy): the main agent applies 0015 + seed 0011 and runs the integration tests.
Commit: branch p41 (not merged).
Decisions added: see DECISIONS.md rows of 2026-11-13 step 4.1. Pending for the CA: whole-month reading of ex-194-IB, circular number for the GST-excluded base, certificate on an untaxed earlier payment.
<!-- progress_parts/P5.md -->
Step 5.0 (planning + foundation, branch p5-plan): Phase 5 plan, API contract; migration 0016 (godowns, stock items, policy, opening, stock journals, movements, voucher stock lines, NRV).
Done: `engine/inventory_types.py`, `services/inventory_hooks.py` stubs, empty routers `api/inventory_{masters,journals,reports}.py` registered in `main.py`, `test_schema_guards.py` table list, `test_inventory_foundation.py` (unit), `test_inventory_schema.py` (integration).
Tests: unit suite 1158 passed (+7 new), `ruff check .` clean; the database was NOT touched: migration 0016 and the schema tests are not yet run.
Commit: on branch p5-plan (not merged). Main agent applies 0016 to test, runs test_inventory_schema.py, then dev.
Decisions added: 9 rows (see DECISIONS.md, step 5.0). Legal values: none needed.

<!-- Phase 4.1/5 package status (folded from progress_parts) -->
<!-- progress_parts/A5.md -->
Step 5.1 package A (masters and opening): godowns, stock items (PUT upsert, no delete), per-FY policy (+copy), opening stock (replace whole FY) with audit; rules S-02/03/04/07/08/09/18.
Done: engine/inventory_masters.py, db/repositories_inventory_masters.py, services/inventory_masters.py, api/inventory_masters.py + schemas_inventory_masters.py.
Tests: 11 unit tests (tests/unit/engine/test_inventory_masters.py) pass; 11 integration tests (tests/integration/test_inventory_masters_db.py) written, NOT run (migration 0016 not applied when written). Unit suite: 1169 passed; ruff clean.
Commit: branch p5-a (not merged).
Decisions added: 5 rows in docs/decisions_parts/A5.md. Needs from main: api/errors.py UNPROCESSABLE += {"no_policy", "period_locked", "negative_stock", "journal_reversal_blocked", "no_original_movement"} (contract says 422).

<!-- progress_parts/B5.md -->
Step 5.1 package B (valuation engine)
Done: engine/inventory_valuation.py (FIFO, WA periodic, WA moving, returns/reversals, S-01 chronology, register, by-godown), inventory_nrv.py (AS 2, S-15), inventory_costing.py (S-14).
Tests: tests/unit/engine/test_inventory_valuation.py + test_inventory_nrv_costing.py, 38 unit tests, hand-derived literals (plan figures confirmed).
Commit: branch p5-b (not merged).
Decisions added: docs/decisions_parts/B5.md (7 rows).

<!-- progress_parts/C5.md -->
Step 5.2 package C (voucher integration), branch p5-c.
Done: engine/inventory_voucher.py (S-02/03/06/07/12/14 plan), db/repositories_inventory_movements.py, services/inventory_movements.py + inventory_hooks bodies, hook calls in vouchers.py, `stock` block on item lines, stock-preview and returnable endpoints, movements at posting, mirror at reversal (S-17).
Tests: tests/unit/engine/test_inventory_voucher.py (17), tests/integration/test_inventory_vouchers_db.py (8 passed in one locked run).
Commit: on branch p5-c (not merged).
Decisions: docs/decisions_parts/C5.md.

<!-- progress_parts/D5.md -->
Step 5.2 D (stock journals): S-10 / S-11 engine (engine/inventory_journals.py), service (create / update / delete draft, approve, post with gapless SJ number, reverse with mirror movements, audit), repository, API + schemas.
Tests: 19 engine unit tests (tests/unit/engine/test_inventory_journals.py); 9 integration tests (tests/integration/test_inventory_journals_db.py): lifecycle, write-off reason, S-01 block/warn, backdated chain, reversal once + blocked, period lock, no policy, API.
Commit: on branch p5-d (not merged).
Decisions added: docs/decisions_parts/D5.md (7 rows).

<!-- progress_parts/E5.md -->
Step 5.3 package E (reports and NRV): stock register (item / by godown / window), item ledger, closing stock at lower of cost and NRV, NRV CRUD with audit, Excel exports.
Done: engine/inventory_report.py, db/repositories_inventory_reports.py, services/inventory_reports.py + inventory_nrv.py + inventory_export.py, api/inventory_reports.py + schemas_inventory_reports.py.
Tests: 11 engine + 2 export unit tests; 5 integration tests (tests/integration/test_inventory_reports_db.py) passed (5 passed in 72s via dbrun.sh).
Commit: branch p5-e (not merged).
Decisions added: 10 rows in docs/decisions_parts/E5.md. No shared file edited (main.py already lists the router).

<!-- progress_parts/F5.md -->
Step: Phase 5 package F (inventory frontend)
Done: api/inventory.ts; screens Masters (godowns, stock items, opening), Policy, Journals, Register (+ item ledger), ClosingStock (NRV, AS 2 write-down, Excel export); InvoiceStockPanel on GST invoice; nav group + 5 routes.
Tests: vitest 92 passed (8 files, 15 new in inventory/lib.test.ts); npm run build ok; tsc clean.
Commit: branch p5-f (not merged).
Decisions added: 4 rows in docs/decisions_parts/F5.md (policy PUT query param, stock-preview not wired).

<!-- progress_parts/G5.md -->
Step 5.5 G: test pack phase5-fresh-pharma-apr-2026 (3 clients: FIFO, WA periodic, WA moving), runner, loader, self-check, verification sheet.
Done: hand values for register, movement cost, by godown, AS 2 closing stock all matched the tool; W4 (4-decimal qty) is refused by G-17 before S-02, pack expects G-17.
Tests: unit green; P5 runner 21 sections run once (all ok except W4 rule id, since fixed in the pack).
Known issue (not fixed): B's FIFO reversal_in opens a new layer, so reversing the original purchase is still refused S-17.
Decisions: docs/decisions_parts/G5.md


<!-- Phase 7 package status (folded from progress_parts) -->
<!-- progress_parts/A6.md -->
Step 6.1 package A (adjustments + partners), branch p6-a.
Done: engine/final_adjustments.py (F-01..F-11 builders and pure calculations), services/final_adjustments.py (ledger roles, setup-ledgers, partners, deed terms, helper -> DRAFT journal through the voucher service, auto-reversal, delete while draft), db/repositories_final_adjustments.py, api/final_adjustments.py + schemas_final_adjustments.py.
Tests: tests/unit/engine/test_final_adjustments.py (55, hand-typed) and tests/integration/test_final_adjustments_db.py (see commit message / report for the DB run result).
Commit: on branch p6-a (not merged).
Decisions added: docs/decisions_parts/A6.md (12 rows).

<!-- progress_parts/A7.md -->
Step 7.A (documents, branch p7-a): upload with content-type sniffing, SHA-256 duplicate check, private store, text reading, OCR adapters, voucher links, download endpoint.
Done: engine/doc_files.py, ai/storage.py, ai/ocr.py, services/documents.py, db/repositories_documents.py, api/documents.py + schemas_documents.py, 503 mapping in api/errors.py.
Tests: tests/unit/test_documents_intake.py (30 + 1 skipped symlink) and tests/integration/test_documents_service.py (see final report for the locked run).
Commit: on branch p7-a (not merged).
Decisions added: docs/decisions_parts/A7.md (9 rows); owner: set DOCUMENT_STORE_DIR; install an OCR engine only for scanned documents.

<!-- progress_parts/B6.md -->
Step 6.1 package B (fixed assets + depreciation, branch p6-b): engines final_assets.py and final_it_depreciation.py (F-20..F-34), repository, service, router and schemas written.
Done: register, events, Companies Act run -> ONE draft Journal through the voucher service, IT block working with the half-rate rule, flags, finalise; rate/life rows read from the seeded tables, `pending` shown on lines and the working.
Tests: unit tests/unit/test_final_assets_engine.py + test_final_it_depreciation_engine.py (43); integration tests/integration/test_final_assets_db.py (7, one locked run).
Commit: on branch p6-b (not merged). Shared file touched: api/errors.py (one line, event_order).
Decisions added: docs/decisions_parts/B6.md (12 rows); plan arithmetic for the package-B examples re-derived by hand: no error found.

<!-- progress_parts/B7.md -->
Phase 7 package B (Tally XML import / export), 2026-11-20
Step: 7.1 B. Done: strict reader (importers/tally_xml.py, defusedxml), mapping rules (engine/tally_map.py), export text (engine/tally_export.py), services tally_import / tally_export, repositories_tally, api/tally.py + schemas_tally.py.
Tests: 43 unit (parser 18, mapping 18, export 7) plus 3 integration in tests/integration/test_tally_import_db.py (one locked run); ruff clean.
Commit: branch p7-b (not merged). Decisions added: 17 rows in decisions_parts/B7.md.
Open: needs a real Tally export sample (schema unverified); plain-lines GST vouchers are invisible to GST returns (warning added); contract updated for new endpoint / codes.

<!-- progress_parts/C6.md -->
Step 6.1 package C (branch p6-c): closing stock approval + Trading A/c, P&L, Balance Sheet (vertical / horizontal), appropriation, ledger positions.
Done: engine/final_statements.py (F-40..F-43, F-44b, F-48, F-61, F-62), services/final_closing_stock.py, services/final_statements.py, db/repositories_final_statements.py, api/final_statements.py + schemas, one line in api/errors.py.
Tests: tests/unit/engine/test_final_statements.py (25) and tests/integration/test_final_statements_db.py (7); results in the final report.
Commit: on branch p6-c (not merged).
Decisions added: docs/decisions_parts/C6.md (12 rows; one plan arithmetic error: the 1,00,001.00 split example).

<!-- progress_parts/C7.md -->
Step 7.1 package C (branch p7-c): masking engine, OpenRouter client, AI switch service + API, llm gateway with call log and rate / cost guard.
Done: engine/doc_mask.py, ai/openrouter.py, db/repositories_ai.py, services/ai_settings.py, services/llm_gateway.py, api/ai_settings.py (4 routes under /clients/{id}/ai), api/schemas_ai.py.
Tests: unit tests/unit/engine/test_doc_mask.py, test_openrouter_client.py (httpx.MockTransport only), test_llm_gateway_pure.py; integration tests/integration/test_ai_gateway_db.py (one locked run).
Commit: on branch p7-c (not merged).
Decisions added: docs/decisions_parts/C7.md (13 rows).

<!-- progress_parts/D6.md -->
Step 6.1 package D (Schedule III) - branch p6-d.
Done: engine/final_sch3.py (classify F-44, Balance Sheet / P&L / notes F-44b F-45 F-46, PPE register rows), repositories_final_sch3, services/final_sch3 (classification CRUD with audit, comparatives, rule status), api/final_sch3 + schemas (5 endpoints).
Tests: tests/unit/engine/test_final_sch3.py (22), tests/integration/test_final_sch3_db.py (1 end-to-end).
Commit: see git log on p6-d.
Decisions added: docs/decisions_parts/D6.md.

<!-- progress_parts/D7.md -->
Phase 7 package D (extraction schemas, prompts, engine checks, extraction service and API), branch p7-d
Done: ai/schemas.py (invoice + bank, Pydantic v2 strict, extra=forbid), ai/prompts.py (versioned, document as data), engine/doc_check.py (D-03, D-05..D-17), engine/doc_bank.py (D-18, D-19), db/repositories_extractions.py, services/extractions.py, api/extractions.py + api/schemas_extractions.py
Tests: tests/unit/test_doc_schemas.py, tests/unit/engine/test_doc_check.py (unit); tests/integration/test_extractions_service.py (database, scripted FakeLlmClient answers with wrong total / tax / GSTIN / missing field / low confidence / invalid JSON / extra key)
Commit: see git log of p7-d
Decisions added: docs/decisions_parts/D7.md

<!-- progress_parts/E6.md -->
Step 6.E (package E): cash flow statement (F-49, F-50) and Excel / PDF export (F-70, F-71).
Done: engine/final_cashflow.py, services/final_cashflow.py, services/final_export.py + final_export_render.py, routers final_cashflow / final_export, reportlab dependency.
Tests: tests/unit/engine/test_final_cashflow.py (10), tests/unit/test_final_export_render.py (7), tests/integration/test_final_export_db.py (1, one batched run).
Commit: branch p6-e (not merged). Company cash flow was not exercised against the database (unit only).
Decisions added: docs/decisions_parts/E6.md. Plan arithmetic for the cash flow mini-example re-derived: correct (1,50,000 / 55,000 / 2,05,000).

<!-- progress_parts/E7.md -->
Step 7.1 package E (branch p7-e): saved party / line mappings with CRUD + audit + API, and the GST invoice-mode draft builder (D-20..D-25, D-27).
Done: engine/doc_map.py, engine/doc_build.py, services/doc_mappings.py, services/doc_drafts.py, db/repositories_doc_mappings.py, api/doc_mappings.py + schemas_doc_mappings.py (routes under /clients/{id}/mappings/... and /documents/{id}/build-draft).
Tests: tests/unit/engine/test_doc_map_build.py (24 unit); tests/integration/test_doc_drafts_db.py (one locked run, incl. the vouchers_ai_queue_guard gate through the real voucher service).
Commit: on branch p7-e (not merged). Depends on package D only for the injected checker (services.extractions.check) used by the API route.
Decisions added: docs/decisions_parts/E7.md (9 rows).

<!-- progress_parts/F6.md -->
Step 6.2 package F (branch p6-f): year-end close and reopen (F-60..F-67).
Done: engine/final_close.py, services/final_close.py, db/repositories_final_close.py, api/final_close.py + schemas, hooks in vouchers.py / client_setup.py / api/errors.py.
Tests: tests/unit/engine/test_final_close.py (25), tests/integration/test_final_close_db.py (3); results in the final report.
Commit: on branch p6-f (not merged).
Decisions added: docs/decisions_parts/F6.md.

<!-- progress_parts/F7.md -->
Phase 7 package F (approval queue backend, narration suggestions, voucher guard hooks), branch p7-f
Done: engine/narration.py (D-40..D-43), engine/queue_edit.py (D-61), services/approval_queue.py (list, detail, claim/release, edit, accept, accept-clean, reject, audit, learning), services/narration.py, services/queue_guard.py, db/repositories_queue.py, api/approval_queue.py, api/narration.py, api/schemas_queue.py; hook lines in services/vouchers.py (approve, post, delete_draft).
Tests: tests/unit/test_narration_engine.py, tests/unit/test_queue_edit_engine.py; tests/integration/test_approval_queue_db.py (wrong extraction via the fake LLM can never be accepted / approved / posted until fixed; correct one posts only after accept + approve + post; Tally items; narration; API). Updated one assertion of package E's test_doc_drafts_db.py (the voucher service now refuses first with queue_not_accepted; the DB trigger is asserted by a direct UPDATE).
Commit: see git log of p7-f (not merged)
Decisions added: docs/decisions_parts/F7.md

<!-- progress_parts/G6.md -->
Step 6.3 package G (branch p6-g): Phase 6 acceptance pack and runner.
Done: docs/test-packs/phase6-full-year-accounts-2026-27 (proprietor, partnership, company; WORKING.md, SIGNOFF.md, VERIFICATION_SHEET.xlsx), pack_loader_p6.py, pack_runner_p6.py, test_pack_runner_p6.py, test_pack_p6_selfcheck.py, scripts/build_verification_sheet_p6.py, PHASE6_SIGNOFF.md, one skip line in test_pack_runner.py.
Tests: unit self-check (35) and ruff green; the pack runner was run once through scripts/dbrun.sh (result in the final report).
Commit: on branch p6-g (not merged).
Decisions added: docs/decisions_parts/G6.md.

<!-- progress_parts/G7.md -->
Phase 7 package G (acceptance pack and runner), branch p7-g
Done: docs/test-packs/phase7-documents-and-ai-2026-27/ (12 synthetic invoices as txt + pdf, scripted fake-model answers, bank statement text + CSV with narration script, 3 Tally XML files, expected_*.csv, WORKING.md, SIGNOFF.md, VERIFICATION_SHEET.xlsx); scripts/build_pack_p7_inputs.py, scripts/build_verification_sheet_p7.py; tests/acceptance/pack_loader_p7.py, pack_runner_p7.py, test_pack_runner_p7.py, test_pack_p7_selfcheck.py; one-line skip in test_pack_runner.py.
Tests: selfcheck 21 unit tests pass, ruff clean; runner via dbrun.sh once: 13 of 14 passed, 1 difference (TB-2 final finding path) re-derived by hand and corrected in expected_findings.csv (not re-run).
Commit: see git log of p7-g (not merged)
Decisions added: docs/decisions_parts/G7.md

<!-- progress_parts/P6.md -->
Step 6.0 (planner, branch p6-plan): plan, API contract and legal values written (docs/PHASE6_PLAN.md, PHASE6_API_CONTRACT.md, PHASE6_LEGAL_VALUES.md).
Done: migration 0017 (20 tables, guards, RLS, closed grants), seeds 0012 / 0013, engine/final_types.py, services/final_hooks.py, 7 empty routers registered, unit lists updated.
Tests: unit 1299+ passed with ruff clean; integration test_final_accounts_schema.py 9 passed (0017 and seeds applied to the TEST schema only; dev not touched).
Commit: on branch p6-plan (not merged). A one-function hotfix (final_append_only_guard) was applied to the test schema by CREATE OR REPLACE and is already in the 0017 file.
Decisions added: docs/decisions_parts/P6.md (14 rows); owner questions: PDF library, legal values (PHASE6_LEGAL_VALUES.md section 5).

<!-- progress_parts/P7.md -->
Step 7.0 (planner, branch p7-plan): plan and API contract written (docs/PHASE7_PLAN.md, PHASE7_API_CONTRACT.md); 50 rules D-01..D-64 catalogued in engine/doc_types.py.
Done: migration 0018 (14 tables, guards incl. vouchers_ai_queue_guard, RLS, closed grants), engine/doc_types.py, ai/llm.py + ai/fake.py, services/ai_hooks.py, 7 empty routers registered, config getters, .env.example, pyproject (pypdf, defusedxml, httpx; OCR extras).
Tests: see the final report of the planner (unit + ruff, then 0018 applied to the TEST schema only and tests/integration/test_documents_schema.py run once).
Commit: on branch p7-plan (not merged).
Decisions added: docs/decisions_parts/P7.md (17 rows); owner items: .env values (DOCUMENT_STORE_DIR, OPENROUTER_API_KEY, LLM_MODEL), pip install, OCR engine choice, tolerance and confidence defaults.

<!-- progress_parts/SYNC7.md -->
- Step: SYNC7, Phase 7 UI sync (api/ai.ts and ai/* screens vs the real routers and schemas).
- Done: narration GET sends X-User; Tally imports list uses `id`; export list typed; queue history uses `at`; queue_blocked shows unacknowledged warnings; note_reason / original_invoice_date rows for credit/debit notes; Tally group picker (groups API exposes ids); loading/empty states; UNVERIFIED markers removed.
- Tests: vitest 132 passed (lib.test.ts extended), `npm run build` ok, pytest tests/unit/test_groups_api_ids.py 1 passed, ruff clean. No DB tests run.
- Commit: branch p7-sync (not merged).
- Decisions added: docs/decisions_parts/SYNC7.md (3 rows).

<!-- progress_parts/UI.md -->
# UI audit (branch ui-audit) - fixes (2026-11-19)

Static audit of frontend/src/api/{gst,tds,inventory}.ts and api.ts against the real FastAPI routers and pydantic schemas (OpenAPI dump plus the services). 17 mismatches found, 16 fixed in the frontend, 1 reported (see decisions_parts/UI.md).

- GST: 2B documents URL needed the client (`/clients/{id}/gst/2b/imports/{import}/documents`); ITC register `period` is now sent as a date (YYYY-MM becomes YYYY-MM-01, was a 422); Rules screen read `rule_status` but the server sends `status.overall`; composition "Save as working" sent return_type `composition` (server: `cmp08`); Credit/Debit Note reason was free text (server accepts 7 keys), now a select; item master sent UQC `''` (fails G-07), now null via `cleanItem`; removed the "Look up rate" button (no such endpoint); preview `gst` can be null on rule errors (screen crashed), now guarded.
- TDS: certificate kinds were form_16a/form_27d (server: non_salary/salary/tcs); ledger roles interest/late_fee are interest_expense/late_fee_expense; deductee types aop/society replaced by aop_boi/co_operative_society (trust kept); due-calendar response is `{rows}` not a bare array; interest and challan-matching rule status read from the wrong place; return working showed `undefined` for the period (now financial_year, quarter, dates); preview `tds` null guarded; 26AS books side tolerates the deductee side (no name or section) and shows the server's `reason`.
- Inventory: item ledger document number is `document_number` (screen read voucher_number/journal_number); stock register `totals` is null with a godown filter, guarded.
- Parties: GST registration type could not be set from the UI (saving a party sent none); added the field with the server's 7 values.
- Forms: ErrorBox no longer repeats each rule message twice, shows `(line N)` per rule error and the row-by-row details of a rejected import file.
- Tests: frontend/src/lib/uiAudit.test.ts (10 tests: enum keys typed from the backend, cleanItem, monthStart, lineLabel, detailLines, every sidebar link has a route). vitest 102 passed, `npm run build` ok.

<!-- progress_parts/UI6.md -->
Step UI6 (Phase 6 UI package, branch p6-ui)
Done: api/final.ts; final/ screens (setup+partners, adjustments, fixed assets, closing stock, statements, Schedule III, cash flow, export, year-end close); Final accounts nav group + routes.
Tests: vitest 116 passed (final/lib.test.ts added); npm run build ok.
Commit: on p6-ui, not merged.
Decisions added: docs/decisions_parts/UI6.md

<!-- progress_parts/UI7.md -->
Step: Phase 7 UI package (branch p7-ui).
Done: api/ai.ts; screens in frontend/src/ai (queue, documents, extraction, narration, mappings, Tally import / export, AI settings); nav group "Documents & AI" and 8 routes (append-only).
Tests: vitest 126 passed (ai/lib.test.ts adds 12); `npm run build` clean.
Commit: see git log of p7-ui.
Decisions added: docs/decisions_parts/UI7.md (7 rows); queue and narration endpoints unverified against package F.


<!-- Phase 8 package status (folded from progress_parts) -->
<!-- progress_parts/A8.md -->
Step 8.1 package A (framework, runs, report). Branch p8-a.
Done: engine/audit_registry.py, services/audit_runs.py, audit_load_common.py, audit_report.py, db/repositories_audit.py, api/audit_checks.py + schemas; errors.py one line; contract note.
Tests: tests/unit/test_audit_registry.py (A00), tests/integration/test_audit_runs_db.py (API on the mini case).
Commit: see branch p8-a.
Decisions added: docs/decisions_parts/A8.md (9 rows).

<!-- progress_parts/B8.md -->
### Phase 8, package B (books checks) on branch `p8-b`
- Step: 8.1 B. Done: `engine/audit_checks_books.py` (A-01..A-06, A-12, A-13, A-14, BooksFacts), `services/audit_load_books.py` (read-only loader), `services/audit_holidays.py`, `api/audit_holidays.py` + `schemas_audit_holidays.py` (GET / POST / DELETE holidays, audit-logged).
- Tests: `tests/unit/test_audit_checks_books.py` (18, literal facts); `tests/integration/test_audit_books_db.py` (2, one locked run); `ruff check .` clean.
- Commit: see `git log p8-b`. Decisions added: 12 rows in `docs/decisions_parts/B8.md`.
- Depends on package A: its registry must call `load_books_facts` and `CHECKS[id](facts, params, rules)`; transport cash limit needs an `is_transporter` mark that does not exist in the schema.

<!-- progress_parts/C8.md -->
Step 8.1 package C: compliance checks A-07..A-11, A-16, A-17 (engine/audit_checks_compliance.py, services/audit_load_compliance.py incl. load_extra).
Done: adapters over msme, gst tie-out service, tds_calc, tds_challan, cash_rules C-01, inventory S-01; registry wrapper (facts.extra["compliance"]).
Tests: tests/unit/test_audit_compliance.py (20), tests/integration/test_audit_compliance_db.py (1, one locked run, passed); ruff clean.
Commit: branch p8-c.
Decisions: docs/decisions_parts/C8.md (4 rows).

<!-- progress_parts/D8.md -->
Phase 8 package D (analytical + related party), branch p8-d
Done: engine/audit_checks_analytic.py (A-15, A-18, previous_period), services/audit_load_analytic.py, services/audit_related.py, api/audit_related.py + schemas_audit_related.py.
Tests: tests/unit/test_audit_analytic.py (16 unit); tests/integration/test_audit_analytic_db.py (loaders, flag API, audit_log, books unchanged).
Commit: see git log of p8-d.
Decisions added: docs/decisions_parts/D8.md (6 rows).

<!-- progress_parts/E8.md -->
Phase 8 step 8.1 package E (audit working papers + sampling), branch p8-e.
Done: engine/audit_sampling.py (SplitMix64, random / systematic / value), engine/audit_papers.py (W-02..W-05 checks, population), services/audit_papers.py, db/repositories_audit_papers.py, api/audit_papers.py, api/audit_sampling.py, api/schemas_audit_papers.py.
Tests: tests/unit/test_audit_sampling.py (21), tests/unit/test_audit_papers_engine.py (16), tests/integration/test_audit_papers_db.py (4, one locked run).
Commit: see git log on p8-e. Decisions added: docs/decisions_parts/E8.md (4 rows).
Open: errors.py maps decision_reason_required / sample_invalid / unknown_check / no_period to 409 (contract says 422): main agent to add them to UNPROCESSABLE.

<!-- progress_parts/F8.md -->
Phase 8 package F (tax audit form data + AI summary), branch p8-f, 2026-11-20
Done: engine/audit_form.py (form by FY end, derive 3CD clauses), services/audit_form.py (+xlsx), services/audit_summary.py, ai/prompts_audit.py, api/audit_tax.py, api/audit_summary.py, gateway purpose.
Tests: unit tests/unit/test_audit_form_engine.py + test_audit_summary_text.py; integration tests/integration/test_audit_form_summary_db.py (fake LLM, raw-SQL runs/findings).
Commit: see git log on p8-f. Depends on package A only through the audit_runs / audit_findings tables (raw SQL in tests), not on its code.
Decisions: docs/decisions_parts/F8.md. Form 26 clauses not seeded (official form unreadable, HTTP 403): owner / CA to supply.

<!-- progress_parts/G8.md -->
Phase 8 package G (acceptance pack and runner), branch p8-g, 2026-11-20
Done: docs/test-packs/phase8-audit-checks-2026-27/ (inputs, hand-typed expected_*.csv, WORKING.md, SIGNOFF.md, VERIFICATION_SHEET.xlsx), scripts/build_pack_p8_inputs.py, scripts/build_verification_sheet_p8.py, tests/acceptance/pack_loader_p8.py, pack_runner_p8.py, test_pack_runner_p8.py, test_pack_p8_selfcheck.py.
Tests: selfcheck 17 passed (no DB, independent re-derivation of every expected figure); runner via scripts/dbrun.sh 12 passed + 1 strict xfail (form clause 21 rule status); ruff clean.
Commit: see git log on p8-g. test_pack_runner.py only gets the phase8.yaml marker exclusion.
Decisions: docs/decisions_parts/G8.md. Open: SIGNOFF Q1-Q21 and the missing Form 26 clause list.

<!-- progress_parts/P8.md -->
### Phase 8, step 8.0 (plan, schema, catalogue, stubs)
- Step: 8.0 on branch `p8-plan`. Done: PHASE8_PLAN / API_CONTRACT / LEGAL_VALUES, migration 0019 (14 tables, guards, RLS, closed grants), seeds 0014 / 0015, `engine/audit_types.py`, `services/audit_hooks.py`, 3 stub check modules, 7 empty routers.
- Tests: unit `tests/unit/test_audit_foundation.py`; integration `tests/integration/test_audit_schema.py` (one locked run, TEST schema only); results in the commit message / report.
- Commit: see `git log p8-plan`. Decisions added: 12 rows in `docs/decisions_parts/P8.md`.
- Pending legal values: 40A(3) successor section and limit, transport limit, s.186 text, Form 26 clauses (see PHASE8_LEGAL_VALUES.md).

<!-- progress_parts/UI8.md -->
Step: UI8 audit screens (frontend only, branch p8-ui).
Done: api/audit.ts; audit/{Catalogue,Runs,RunReport,Papers,PaperDetail,Related,Holidays,TaxForm,AiSummary,common,lib}; Audit nav group; 8 routes.
Tests: vitest 137 passed (5 new in audit/lib.test.ts); npm run build passes (tsc + vite).
Commit: on p8-ui, not merged.
Decisions added: 5 in docs/decisions_parts/UI8.md.

<!-- progress_parts/glue8.md -->
Step: Phase 8 glue. Done: population in run summary, papers use it, contract updated, end-to-end test.
Tests: unit 1785 passed (before final test add); test_audit_end_to_end.py 1 passed (87s); ruff clean.
Commit: p8-glue. Decisions: docs/decisions_parts/glue8.md.

