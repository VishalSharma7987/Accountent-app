Step 3.1 (package A, branch p3-a): GSTIN (G-01..G-04 incl. mod-36 check char), registrations + ledger roles (G-05, G-06, G-08), item master (G-07), rule loaders/pickers for all nine tables, masters API, party `gst_registration_type`.
Done: engine/gstin.py, engine/gst_masters.py, engine/parties.py (new field + G hand-over), rules/gst_rules.py, db/repositories_gst_masters.py, services/gst_registrations.py + gst_items.py + parties.py (new field), api/gst_masters.py + schemas_gst_masters.py (+ one field in schemas_bills.py / api/parties.py).
Tests: unit (gstin, masters, party, rules) added to the 633-test unit run (all pass); 6 integration tests in test_gst_masters_db.py pass via dbrun.sh; `ruff check .` clean. The full suite was NOT run (owner's instruction).
Commit: on branch p3-a (not merged).
Decisions added: see docs/decisions_parts/A.md (parties do not yet use the check digit: Phase 2 fixtures use an invalid check character).
