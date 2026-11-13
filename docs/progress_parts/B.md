Step 3.2 / 3.3 (package B): pure tax engine `engine/gst_tax.py` and invoice mode `engine/gst_invoice.py` (G-06, G-08, G-10..G-26, G-30 flags), API (`gst` block on the voucher endpoints, `POST /clients/{c}/vouchers/gst-preview`), hooks in `services/vouchers.py` and bodies of `services/gst_hooks.py`.
Tests: 77 engine unit tests (hand-calculated), 5 API / Excel parser unit tests, 5 new integration tests (create -> approve -> post -> reverse, G-26, G-23, RCM purchase, Excel import); full suite NOT run (owner rule); unit run 767 passed; ruff clean.
Done: Sales, Purchase, Credit Note, Debit Note in invoice mode; CGST / SGST / IGST / cess, RCM, blocked credit flag (tax into cost), zero-rated LUT, round-off option, composition client bill of supply; preview; Excel item rows.
Gaps: G-02 check digit for invoices waits for package A (`InvoiceContext.gstin_check`); purchases of composition clients refused; no schema change requested.
Decisions: docs/decisions_parts/B.md (19 rows).
