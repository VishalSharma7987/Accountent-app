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
