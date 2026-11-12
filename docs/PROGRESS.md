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
