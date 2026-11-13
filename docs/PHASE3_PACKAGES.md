# Phase 3 packages: exactly which files each owns (after step 3.0)

Step 3.0 (done, main): migrations 0009-0011, seeds 0004-0007, `engine/gst_types.py`, `services/gst_hooks.py` (stubs),
empty routers `api/gst_{masters,invoices,itc,recon,returns}.py` registered in `main.py`. After 3.0 nobody edits
`main.py`, `database/**`, `engine/gst_types.py` signatures (add optional fields at the end only, via the main agent).
Every package writes tests under `backend/tests/{unit,integration}/` in new files named for its area, and its decision rows /
status in `docs/decisions_parts/<pkg>.md` and `docs/progress_parts/<pkg>.md` (main merges them).

| Pkg | Creates / edits | Never touches |
| --- | --- | --- |
| A | `engine/gstin.py`, `engine/gst_masters.py`, `engine/parties.py` (gst_registration_type only), `rules/gst_rules.py`, `services/gst_registrations.py`, `services/gst_items.py`, `services/parties.py` (new field only), `db/repositories_gst_masters.py`, `api/gst_masters.py`, `api/schemas_gst_masters.py` | vouchers, bills |
| B | `engine/gst_tax.py`, `engine/gst_invoice.py`, `engine/models.py` (optional `gst` field), `engine/validation.py` (one call), `services/gst_invoices.py`, `services/gst_hooks.py` (bodies of validate/persist/load only), `services/vouchers.py` (hook calls only), `services/voucher_import.py`, `db/repositories_gst_invoice.py`, `api/gst_invoices.py`, `api/schemas_gst_invoices.py`, `api/vouchers.py` (gst extension) | ITC, 2B |
| C | `engine/gst_itc.py`, `services/gst_itc.py` (must define `on_post(conn, client_id, voucher_id, actor)` and `on_reverse(conn, client_id, original_id, reversal_id, actor)`), `db/repositories_gst_itc.py`, `api/gst_itc.py`, `api/schemas_gst_itc.py` | vouchers.py, gst_hooks.py |
| D | `importers/gstr2b.py`, `engine/gst_recon.py`, `services/gst_recon.py`, `db/repositories_gst_recon.py`, `api/gst_recon.py`, `api/schemas_gst_recon.py`, `tests/fixtures/gstr2b/*` | ITC schema |
| E | `engine/gstr1.py`, `engine/gstr3b.py`, `engine/gst_tieout.py`, `engine/composition.py`, `services/gst_returns.py`, `services/gst_export.py`, `db/repositories_gst_returns.py`, `api/gst_returns.py`, `api/schemas_gst_returns.py` | |
| F | `frontend/src/gst/**`, `frontend/src/api/gst.ts`, one router/menu entry | backend |
| G | `docs/test-packs/phase3-*/**`, `backend/tests/acceptance/pack_loader_p3.py`, `pack_runner_p3.py` (after A-E merged) | engine, services |

Recommended parallel start: A, then B and (C engine, D parser/matcher, E engine) in parallel using literal rule objects;
service/integration tests of B..E wait for A (and C for D/E) to be merged. DB runs always through `scripts/dbrun.sh`.
