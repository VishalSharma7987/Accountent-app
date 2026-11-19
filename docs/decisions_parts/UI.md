# UI audit - unresolved items (2026-11-19)

| date | step | decision | reason |
| --- | --- | --- | --- |
| 2026-11-19 | UI audit | OPEN (backend): no `GET /gst/rates/lookup` exists (only `GET /gst/rate-slabs` and the TDS `/tds/rates/lookup`); the item master "Look up rate" button was removed | the contract named the endpoint but the backend never built it; adding it needs a DB test, which this audit did not run. Add the endpoint, then restore the button |
| 2026-11-19 | UI audit | OPEN: GSTR-2B import kind `ims` is offered but the server only accepts `gstr2b` (it answers with a clear message) | IMS file layout not available; hide the option or build the parser |
| 2026-11-19 | UI audit | OPEN: `GET /tds/register` always returns `due_date: null` and `days_late: null` | the register does not compute them (the challan matching tab does); the columns show blank |
| 2026-11-19 | UI audit | OPEN: gst-preview errors carry no `details.item_line_no`, so item-level errors show in the header list, not under the item row | the schema has only rule_id, message, line_no; confirm what line_no means for GST item errors |
| 2026-11-19 | UI audit | OPEN: saved TDS certificate snapshots list has no deductee name (server returns only the ledger id) | the screen shows version and number only; map the id to the deductee list if wanted |
| 2026-11-19 | UI audit | NOT VERIFIED against live data: the dev database has no GST, TDS or inventory rows, so response shapes were compared by reading services and schemas, not by curl | the owner's UI test with real rows is the final check |
