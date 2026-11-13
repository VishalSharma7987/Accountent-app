# Phase 5 plan - Inventory (trading): item master, opening stock, movements, valuation, AS 2, stock register

Written 2026-11-13 (planning agent) under the working mode of CLAUDE.md section 6. Scope: `docs/PHASE_PROMPTS.md` Phase 5. Interfaces: `docs/PHASE5_API_CONTRACT.md`.
Schema (migration **0016**; 0015 is reserved for Phase 4.1) is written FIRST and is the shared contract: **agents never edit it**; a needed change goes to the main agent.
Step 5.0 (this commit, branch `p5-plan`) wrote the migration, types, stubs and empty routers only; it did **not** touch the database (the main agent applies 0016 to test, runs `tests/integration/test_inventory_schema.py`, then dev).
No legal value is needed in this phase (AS 2 and costing are accounting standards, not rate tables); nothing is `pending` in a rule table. Two accounting choices need the accountant's sign-off at the end of the phase (section "Sign-off questions").

## How items, godowns and invoice lines link (the key decision)
* A **stock item = a `gst_items` goods row (name, HSN, unit/UQC) + one `stock_items` row (SKU, default godown)**. `voucher_item_lines.item_id` already points at `gst_items`, so no change to the Phase 3 tables: an invoice item line whose `item_id` has a `stock_items` row moves stock; any other line (service, expense, asset, untracked goods) does not.
* A trigger on `gst_items` freezes unit (UQC) and kind of an item that has opening stock or movements (S-18). HSN/name stay editable; the invoice line keeps its own HSN snapshot.
* `voucher_stock_lines` (draft-only, same guard as the GST child tables) carries what an item line cannot: the **godown** if it differs from the item's default, and for a **Credit Note / Debit Note the physical-return marker + `original_movement_id`**. A note line without a row is value-only (post-sale discount, rate correction): no stock effect. `voucher_gst.note_reason` is not used for this because it has no purchase-return value.
* **Movements are created by the service at posting** (`inventory_hooks.on_post`) from the posted voucher's item lines, and by stock-journal posting. There is no endpoint that creates a movement directly (S-05). `stock_movements` is INSERT-only (trigger); a correction is a mirror movement (`reversal_in` / `reversal_out`) written when the voucher or journal is reversed.
* Valuation is **per item** (cost layers / averages are not split by godown); godowns carry quantities (for transfers, write-offs, S-01 per godown, register by godown). Transfers never change an item's cost or value.

## Database design (migration 0016)
| Table | Purpose |
| --- | --- |
| `godowns` | client's godowns; unique name per client |
| `inventory_settings` | PK (client, FY): `valuation_method` fifo / wa_periodic / wa_moving, `negative_stock_mode` block (default) / warn. No row = S-04 error (policy never defaulted silently). Method change blocked once the FY has a movement (trigger) |
| `stock_items` | PK item_id -> gst_items (goods only, trigger); `sku` unique per client (case-insensitive), `default_godown_id` NOT NULL, `is_active` |
| `stock_opening` | per client + FY + item + godown: `quantity numeric(18,4)` (CHECK = round(qty,3)), `value numeric(18,4)` (CHECK = round(value,2)); value > 0 needs qty > 0 |
| `stock_journals` + `stock_journal_lines` + `stock_journal_sequences` | transfer / write-off documents (no ledger lines). Status draft -> approved -> posted -> reversed with a strict trigger; number `SJ/2026-27/0001` assigned at posting, gapless; write-off needs `reason_code` + `reason_note`; lines editable only in draft |
| `stock_movements` | append-only: `seq` identity (order tie-break), kind (purchase, sale, sales_return, purchase_return, transfer_in, transfer_out, write_off, reversal_in, reversal_out), direction (CHECK vs kind), quantity, `value` (purchase only: CHECKed against the item line's taxable value + tax that is part of cost), source voucher+item line or journal+line, `ref_movement_id` (required for returns and reversals, kind-checked by trigger), reversed-once unique index |
| `voucher_stock_lines` | see above |
| `stock_nrv_entries` | per client + item + as_on_date: `nrv_per_unit` (2 decimals, >= 0), `basis_note` required; editable, audited |

Quantity rule (decision): **3 decimals**, stored `numeric(18,4)` with `CHECK (qty = round(qty, 3))` exactly like money, so 1.0005 is rejected, never rounded (S-02); read back with 4 decimals and quantized to 3 in Python. (`voucher_item_lines.quantity` is `numeric(18,3)` from Phase 3 and rounds silently at the database; the Phase 5 service rejects a 4th decimal before it gets there, and the movement trigger requires the movement's quantity to equal the line's.) Money values go through `engine/money.round_half_up`.
No outward cost is stored anywhere: reports always recompute, so a backdated entry can never leave a stale cost. RLS on all 10 tables; function privileges re-closed at the end of the migration.

## Rules (IDs used in messages and test names)
| ID | Rule |
| --- | --- |
| S-01 | No negative stock: quantity on hand per item and godown, checked over the **whole chronology** (date, seq) from the FY opening, so a backdated sale cannot hide a gap. Mode `block`: error, the voucher / journal cannot be approved or posted. Mode `warn`: same finding as a warning |
| S-02 | Quantity > 0, at most 3 decimals (rejected, not rounded); opening quantity >= 0 |
| S-03 | Only an active goods item with a stock_items row moves stock; SKU unique per client |
| S-04 | Inventory policy (method + negative mode) must exist for the FY; method cannot change once the FY has movements; a new FY's policy is set explicitly (API offers "copy from previous FY") |
| S-05 | Movements come only from posted invoice item lines and posted stock journals; immutable; corrected only by reversal |
| S-06 | Invoice line unit (uqc) must equal the item's unit; line HSN must equal the item's HSN |
| S-07 | Godown exists, belongs to the client, is active; line godown = override else item default |
| S-08 | Opening stock: one row per item + godown + FY; value 2 decimals; the opening total is shown against the Stock-in-hand ledger's opening balance and any difference is displayed (information, not a block: Phase 6 books the closing stock) |
| S-09 | Opening / policy / NRV edits are blocked for a FY whose periods are locked (V-07 style) and are audit-logged |
| S-10 | Stock journal: >= 1 line; transfer: from <> to godown; write-off: reason code + note, qty <= stock (S-01); date inside a FY and an open period (V-06 / V-07) |
| S-11 | Stock journal lifecycle Draft -> Approved -> Posted -> Reversed; number at posting; reversal needs a reason, only once, and is blocked if the mirror movements would make stock negative |
| S-12 | Credit Note / Debit Note stock effect needs `original_movement_id` (sale / purchase of the same item); return qty <= original qty minus earlier returns; under FIFO a purchase return needs enough of that layer left |
| S-13 | Cost of everything outward (sale, write-off, returns, reversals) is **computed by the engine from the policy**, never typed or stored |
| S-14 | Purchase cost = item line taxable value (after discount) + CGST/SGST/IGST/cess only when `tax_in_cost` (blocked credit); recoverable GST is not cost. Freight / other direct costs are not allocated in Phase 5 (suggestion) |
| S-15 | AS 2: closing stock at lower of cost and NRV, **item by item**; NRV entered per item at period end; write-down shown; no NRV entered = warning and no write-down computed (never guessed) |
| S-16 | Every report states method, as-on date, items without NRV, negative-stock findings (warn mode) |
| S-17 | Reversing a voucher / journal appends mirror movements dated the reversal date, same godown and quantity, cost from the engine; blocked when it would make stock negative |
| S-18 | Unit and kind of an item with stock entries cannot change (database trigger); an item with entries cannot be deleted (foreign keys); deactivation needs zero closing stock |
| S-19 | Backdated entry (date before an existing movement) is allowed but re-runs S-01 for the whole chain |
| S-20 | Movement and journal dates inside the FY; periods follow V-06 / V-07 |

## Valuation (engine/inventory_valuation.py, pure)
Per item, movements sorted by (date, seq); opening = sum of `stock_opening` of the item (one cost layer; qty and value). Outward value is rounded half-up to 2 places; **when an outward takes the last unit on hand, its value is the whole remaining value** (no rounding residue is ever left behind). Transfers are ignored for value (quantities only).

### Worked example (one item, UOM Nos; all values typed by hand)
Opening 01-04: 100 @ 10.00 = 1,000.00. Movements in April:
| Date | Movement | Qty | Cost |
| --- | --- | --- | --- |
| 05-04 | Purchase | 200 | 2,400.00 (12.00 each) |
| 10-04 | Sale | 150 | |
| 15-04 | Purchase | 100 | 1,500.00 (15.00 each) |
| 20-04 | Sale | 180 | |

Closing quantity = 100 + 200 - 150 + 100 - 180 = **70** in all three methods. Check: total available cost 1,000 + 2,400 + 1,500 = 4,900.00.

**FIFO.** Layers: L0 100 @ 10 (1,000), L1 200 @ 12 (2,400), L2 100 @ 15 (1,500).
Sale 10-04 (150): 100 from L0 = 1,000.00 + 50 from L1 = 600.00 -> cost 1,600.00; L1 left 150 @ 12 (1,800.00).
Sale 20-04 (180): 150 from L1 = 1,800.00 + 30 from L2 = 450.00 -> cost 2,250.00; L2 left 70 @ 15.
Outward 3,850.00; **closing 70 = 1,050.00** (4,900 - 3,850).

**Weighted average, periodic** (window = the report period; opening of a window that starts after the FY start = the same method's valuation of FY start..day before, as one period). April window: qty 100 + 200 + 100 = 400, value 4,900.00, average 12.25. Outward 330 x 12.25 = 4,042.50; **closing 70 x 12.25 = 857.50** (4,900.00 - 4,042.50). The statutory year-end figure is the FY window.

**Weighted average, moving** (average recomputed after each inward; unit cost = running value / running qty, kept exact, never rounded before use).
After 05-04: qty 300, value 3,400.00 (11.3333.. each). Sale 150: 150 x 3,400/300 = 1,700.00; left 150, 1,700.00.
After 15-04: qty 250, value 3,200.00 (12.80). Sale 180: 180 x 12.80 = 2,304.00; left 70, **closing 896.00** (4,900 - 1,700 - 2,304).

| Method | Outward cost | Closing 70 |
| --- | --- | --- |
| FIFO | 3,850.00 | 1,050.00 |
| WA periodic | 4,042.50 | 857.50 |
| WA moving | 4,004.00 | 896.00 |

### Returns and reversals (decision, standard practice)
* **Sales return** (Credit Note, goods back): inward at the **unit cost of the sale it refers to** (the engine's outward cost of that movement / its qty; value = qty x that unit cost, half-up). FIFO: a new layer at that cost dated the return; moving: added at that cost; periodic: treated as a reduction of the period's outward quantity at the period average (cost of the original sale is unknown until period end).
  Example (FIFO above): 10 units returned from the 20-04 sale (cost 2,250.00 / 180 = 12.50) -> +125.00.
* **Purchase return** (Debit Note): outward at the unit cost of the purchase it refers to; FIFO takes it from that layer (S-12 error if the layer no longer has the quantity: review, never guess); moving: removed at that cost; periodic: reduces the period's inward qty and value by qty x that unit cost.
* **Reversal movements** (`reversal_in` / `reversal_out`) follow the same two rules (ref = the reversed movement).

### AS 2 (engine/inventory_nrv.py)
Per item: `nrv_value = round_half_up(closing_qty x nrv_per_unit, 2)`; `write_down = max(0, cost_value - nrv_value)`; `carrying = cost_value - write_down` (= lower of cost and NRV). Item-by-item, never netted across items. No NRV for an item -> carrying = cost, warning S-15.
Example (FIFO closing above): cost 1,050.00 (70 x 15.00). NRV entered 13.50 -> nrv_value 945.00; write-down **105.00**; carrying **945.00**. NRV 16.00 -> nrv_value 1,120.00; write-down 0.00; carrying 1,050.00. NRV 13.505 is rejected (2 decimals).

The register and valuation reports return both: closing stock **at cost** and **after write-down** (what Phase 6 takes into the Trading A/c; the write-down is shown separately, no journal is posted).

## Packages and file ownership (parallel agents never collide)
After 5.0 nobody edits `main.py`, `database/**`, `engine/inventory_types.py` signatures (add optional fields at the end, via the main agent), `services/inventory_hooks.py` signatures. Decision rows go to `docs/decisions_parts/<pkg>.md`, status to `docs/progress_parts/<pkg>.md`; tests in new files named for the area. DB runs through `scripts/dbrun.sh`.

| Pkg | Creates / edits | Never touches | Depends on |
| --- | --- | --- | --- |
| A masters | `engine/inventory_masters.py` (S-02, S-03, S-04, S-07, S-08 validators), `services/inventory_masters.py` (godowns, stock items, policy, opening; audit), `db/repositories_inventory_masters.py`, `api/inventory_masters.py`, `api/schemas_inventory_masters.py` | vouchers, journals, valuation | none |
| B valuation engine | `engine/inventory_valuation.py` (FIFO, WA periodic, moving, returns, S-01 chronology check, register assembly), `engine/inventory_nrv.py` (AS 2), `engine/inventory_costing.py` (purchase cost from an item line, S-14), tests `tests/unit/engine/test_inventory_*.py` with literal expectations (the worked example above is the first test) | DB, services, API | none (pure; literal Movement objects) |
| C voucher integration | `services/inventory_hooks.py` (bodies), `services/inventory_movements.py` (build movements from posted lines, mirror on reversal, S-01 re-check via B, S-05, S-06, S-12, S-17), `db/repositories_inventory_movements.py` (incl. `load_movements(conn, client, fy, to_date)` and `load_opening`, read-only use by E), `services/vouchers.py` (hook calls only), `api/vouchers.py` + `api/schemas.py` (optional `stock` block on item lines), `engine/inventory_voucher.py` | masters tables, journals | A (integration tests), B (S-01) |
| D stock journals | `engine/inventory_journals.py` (S-10, S-11 validators), `services/inventory_journals.py` (create/update draft, approve, post with gapless number, reverse, mirror movements, audit), `db/repositories_inventory_journals.py`, `api/inventory_journals.py`, `api/schemas_inventory_journals.py` | vouchers.py, masters | A, B (S-01), C's repository `load_movements` (use after merge; literal data before) |
| E reports and NRV | `engine/inventory_report.py` (register / closing valuation assembly, by-godown), `services/inventory_reports.py`, `services/inventory_nrv.py` (CRUD + audit, S-09, S-15), `services/inventory_export.py` (Excel), `db/repositories_inventory_reports.py`, `api/inventory_reports.py`, `api/schemas_inventory_reports.py` | movements writers | A, B, C repository |
| F UI (separate package, later) | `frontend/src/inventory/**`, `frontend/src/api/inventory.ts`, one router/menu entry | backend | contract |
| G test pack + acceptance | `docs/test-packs/phase5-*/**` (accountant-computed FIFO and weighted-average month incl. returns, transfer, write-off, NRV), `backend/tests/acceptance/pack_loader_p5.py`, `pack_runner_p5.py`, `PHASE5_SIGNOFF.md` | engine, services | A..E merged |

**Parallel split.** Wave 1 (no dependencies): **A and B**. Wave 2 (after A merged; B available): **C and D** in parallel (D reads movements only through C's repository after merge, literal data before). Wave 3: **E**. F (UI) can start from the contract during wave 2. G last. Docs-only parts of G (hand-worked packs) can start in wave 1.

## Steps
5.0 plan + schema + types + stubs (this commit). 5.1 A + B (parallel). 5.2 C + D (parallel). 5.3 E. 5.4 F. 5.5 G, acceptance run (accountant FIFO / weighted-average month), report to owner. Each step: tests first, full suite + `ruff check .` before every commit, 5-line status in PROGRESS.md.

## Accounting stays periodic
Nothing in this phase posts a voucher or a ledger line. Sales / Purchase vouchers keep posting through the Phase 3 engine (Purchase Accounts / Sales Accounts); the stock tables are a sub-ledger. `GET /inventory/closing-stock` gives Phase 6 the number for the Trading A/c (at cost and after AS 2 write-down); the Phase 6 closing-stock entry reads it, it is not built here.

## Sign-off questions (for the accountant at the end of the phase)
1. Returns valued at the **original** transaction's unit cost (above) rather than the current average. 2. Weighted average *periodic* windows (month report chains from "FY start to day before" as one period). 3. Valuation per item, not per godown. 4. Freight and other direct costs are not capitalised into inventory in Phase 5.

## Suggestions (not built)
Landed-cost allocation of freight; batch / expiry / serial tracking; godown-wise valuation; carry-forward of closing stock into the next FY's opening (Phase 6 year-end close); barcode / unit conversions (box to pieces); reorder levels; Tally item import (Phase 7).
