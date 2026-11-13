Step 3.7-3.8 (package E: GSTR-1, GSTR-3B, tie-out, composition, exports)
Done: pure engines gstr1/gstr3b/gst_tieout/composition, repository, services gst_returns + gst_export (Excel, portal-shape JSON), API + schemas, versions/finalise/filed figures, audit log
Tests: 44 new unit tests (engine, export round trip) + 4 integration tests (tests/integration/test_gst_returns.py via dbrun.sh); ruff clean; FULL SUITE NOT RUN (owner forbids); needs A (registrations, party type), B (voucher_gst/item rows), C (itc_entries/itc_reversals): tests build those rows with raw SQL, real flow untested until merge
Gaps: reclaim journals not in 4(A); Rule 38/42/43, ISD, amendments (GSTR-1 table 9) absent; JSON shape and table numbers unverified against the portal
Commit: branch p3-e; decisions in docs/decisions_parts/E.md
