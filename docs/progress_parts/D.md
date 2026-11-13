Step 3.6 (package D, branch p3-d): GSTR-2B import and reconciliation.
Done: importers/gstr2b.py (JSON + Excel, strict), engine/gst_recon.py, repository, service, API + schemas, hand-made fixtures.
Tests: unit 30 passed (engine 18, importer 12); integration tests/integration/test_gst_recon.py 3 passed via dbrun.sh; ruff clean; full suite NOT run (owner instruction).
Commit: see git log of p3-d. Open: a real GSTR-2B JSON/Excel and an IMS sample from the owner; C's apply_2b_result hook.
Decisions added: 9 rows in docs/decisions_parts/D.md.
