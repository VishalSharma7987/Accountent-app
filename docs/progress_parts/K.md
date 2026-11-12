Phase 2.1 agent K: (a) newest-first statements detected from running balances, (b) Cr/Dr balance text, (c) GET reconciliation matches endpoint + Reconciliation screen.
Done: parser (importers/bank_statement.py), notes in preview/import, services/reconciliation.list_matches, API + schemas, frontend types/api/screens, contract doc.
Tests: unit tests/unit/importers/test_bank_statement_orient.py; integration tests/integration/test_recon_matches.py + updated test_bank_statements.py; vitest phase2.test.ts (57 pass), npm build ok.
Commit: branch p21-K (see final report).
Decisions added: 4 rows in docs/decisions_parts/K.md (replaces the 2.6 "file order, no re-sorting" decision).
