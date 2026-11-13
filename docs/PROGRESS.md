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
