# Progress log

Five lines per finished step (see CLAUDE.md section 6).

## Phase 0
- Steps 0.1, 0.2, 0.3: done (commits e49a833, 2ab24a8, 39685e8). One Supabase project, schemas `public` (dev) and `ledgermind_test`.

## Phase 1
- **1.1** done: migration 0003 (accounting core, guards) + seed (23 groups); 123 guard tests; commit 3746715.
- **0004** done: exact money (NUMERIC(18,4)+round check), API grants closed, unit/integration test split; commit 1285d17.
- **1.2** done: pure engine `money.py`, `models.py`, `validation.py` (V-01..V-09, V-13, V-14), `duplicates.py` (V-10); pack format gets `party_ledger`; template wrong vouchers X04 (V-13), X05 (V-14) run through the real engine; tests: see commit; decisions: 6 rows added (1.2).
