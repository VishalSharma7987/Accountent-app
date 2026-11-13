Step 3.10 (package G, branch p3-g): Phase 3 accountant test pack `docs/test-packs/phase3-sunrise-traders-apr-2026/` (client.yaml, ledgers/parties/registrations/items/roles, 14 invoice-mode vouchers, payments, two GSTR-2B JSON files, ITC evidence/claims, 8 wrong cases, composition client, 16 expected_*.csv, WORKING.md, SIGNOFF.md, VERIFICATION_SHEET.xlsx from `scripts/build_verification_sheet_p3.py`).
Done: `pack_loader_p3.py`, `pack_runner_p3.py` (17 sections), `test_pack_runner_p3.py` (integration), `test_pack_p3_selfcheck.py` (7 unit tests), `test_pack_runner.py` skips the Phase 3 pack.
Tests: see the final report (pack runner via dbrun.sh; unit self-check; P1 and P2 runner tests; `ruff check .`). The full suite was NOT run (owner's instruction).
Commit: on branch p3-g (not merged).
Decisions added: see docs/decisions_parts/G.md. Findings (pack vs tool differences) are listed in the final report and are not hidden by editing the pack.
