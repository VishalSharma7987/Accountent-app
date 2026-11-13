| date | step | decision | reason |
| --- | --- | --- | --- |
| 2026-11-13 | 3.F | GST API client lives in `frontend/src/api/gst.ts` with its own request helper (imports API_BASE/getUser from `api.ts`) | `api.ts` does not export its helpers; avoids editing a shared file |
| 2026-11-13 | 3.F | Invoice mode is a separate screen `/gst/invoice` (InvoiceEntry + InvoiceGstPanel), VoucherEntry is untouched | Panel stays a reusable component; no risk to the Phase 1/2 voucher screen. Saves a draft, then opens it in the existing voucher screen |
| 2026-11-13 | 3.F | GSTR-1/3B/composition tables are drawn by a generic DataView straight from the server `tables`; no portal table numbers hard-coded in the browser | Numbers and portal numbering are unconfirmed (PHASE3_LEGAL_VALUES section 5); the screen shows what the server sends, including `portal_table` fields |
| 2026-11-13 | 3.F | Unknown or missing rule status renders as the amber "pending" badge, never as verified | G-55; safest option |
| 2026-11-13 | 3.F | Quarterly (QRMP / composition) period: user types any month, the browser derives the Indian-FY quarter start for `period_start` | Display convenience only; the server validates the period (`period_invalid`) |
| 2026-11-13 | 3.F | JSON exports are labelled "unverified format"; filed-returns (PUT/GET) endpoint not wired in the UI | Contract says portal JSON is unverified; filed-return entry is outside the listed screens |
