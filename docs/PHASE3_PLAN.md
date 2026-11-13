# Phase 3 plan — GST (registrations, tax engine, invoice mode, ITC, GSTR-2B, GSTR-1 / 3B workings, composition)

Written 2026-11-13 (planning agent) under the working mode of CLAUDE.md section 6. Scope: `docs/PHASE_PROMPTS.md` Phase 3. Interfaces: `docs/PHASE3_API_CONTRACT.md`.
Legal values and their status: `docs/PHASE3_LEGAL_VALUES.md` (no value is `verified`; official sites were unreadable).
Schema (migrations 0009-0011, seeds 0004-0007) is written FIRST and is the shared contract: **agents never edit it**; a needed change goes to the main agent. Migrations were written but NOT applied or run by the planner (the shared test DB was in use): the main agent applies them (`--target test`, tests, then `--target dev`) and fixes any SQL typo in step 3.0.

## Steps

| Step | Builds | Package |
| --- | --- | --- |
| 3.0 | Apply 0009-0011 and seeds 0004-0007 (test then dev); update `tests/unit/test_migrate.py` (seed list now 0001-0007) and the schema-agnostic test; `engine/gst_types.py` (frozen dataclasses of the contract: `StateCode, RateRule, RateSlab, RcmRule, BlockedRule, ItcCondition, Threshold, CompositionRule, GstRegistration, GstItem, ItemLineIn, TaxLine, InvoiceIn, InvoiceResult`), empty router modules `api/gst_*.py` registered in `main.py`, no-op hook stubs (`services/gst_hooks.py`: `on_post`, `on_reverse`, `validate_invoice`, `persist_invoice`, `load_invoice`) so every package imports from day one | main |
| 3.1 | GSTIN validation incl. check digit, state codes, PAN/state consistency, registrations CRUD, ledger-role map, item/service master, rule-table loaders (all nine tables, by date, with status roll-up) | A |
| 3.2 | Pure tax engine: place of supply, CGST/SGST/IGST, line rounding, round-off, RCM, exempt/nil/non-GST/zero-rated, cess | B |
| 3.3 | Invoice-mode vouchers: engine builds the voucher lines and the tax lines; hooks into `services/vouchers.py`; Credit/Debit Note against an original invoice | B |
| 3.4 | ITC register: eligibility (Section 16 evidence, 17(5), pending 2B, reversed), claim deadline, status events | C |
| 3.5 | 180-day rule: reversal draft journal and re-claim on payment | C |
| 3.6 | GSTR-2B / IMS import (JSON + Excel), reconciliation with the purchase register, manual links | D |
| 3.7 | GSTR-1 working (all tables), HSN summary, documents issued | E |
| 3.8 | GSTR-3B working (3.1, 3.2, 4, 5, 6.1), tie-out report Books - GSTR-1 - GSTR-3B (- filed figures), composition working, JSON/Excel outputs | E |
| 3.9 | Screens | F |
| 3.10 | Phase 3 test pack + hand `WORKING.md` + `VERIFICATION_SHEET.xlsx` + runner | G (after merge) |
| 3.11 | Integration, full suite, acceptance report | main |

## Dependencies (honest)
- Everyone needs 3.0 first (schema applied, `gst_types.py`, hook stubs). Nobody edits migrations, `gst_types.py` signatures, or `main.py` after 3.0.
- A is independent. B's unit tests (engine) use literal rule objects and do not need A; B's service tests need A's loaders and masters (registrations, ledger roles, items): **merge A before B's integration tests run**. B merges second.
- C unit tests (engine) are independent; C's service tests need B (posted purchase vouchers with item lines) and, for the 180-day rule, Phase 2 bills (already merged).
- D unit tests (parser, matcher) are independent; D's service tests need B (posted purchase vouchers) and C (`itc_entries`, `supplier_tax_paid` / status update on link).
- E unit tests use plain data; its service tests need B (sales register), C (ITC statuses), D (2B figures for 3B 4(A)(5) comparison).
- F builds against the contract with mocked responses; finishes against the merged API.
- G (test pack) starts only after A-E are merged and the main agent has run the full suite.
- **Merge order: A -> B -> C -> D -> E -> F -> G.** Branches: `p3-A` ... `p3-G`.
- The hook functions `services/gst_hooks.py`: owned by B (it adds the calls inside `services/vouchers.py` once, for validate / persist / load / post / reverse). C implements `on_post` / `on_reverse` bodies inside `services/gst_itc.py` and the stub in `gst_hooks.py` imports it lazily (main wires this in 3.0, so C and B never touch each other's files).

## File ownership (no two packages edit the same file)

| Package | Owns (create/edit) | Must not touch |
| --- | --- | --- |
| main (3.0, 3.11) | `database/**`, `engine/gst_types.py`, `services/gst_hooks.py` (stub), `api/main.py` router registration, `docs/PROGRESS.md`, `docs/DECISIONS.md` rows (agents give their rows in the report; main merges them: the Phase 2 conflict on those two files) | |
| A | `engine/gstin.py`, `engine/gst_masters.py`, `engine/parties.py` (only: P-01 hands over to G-01/G-02, `gst_registration_type` field), `rules/gst_rules.py` (all loaders, one module), `services/gst_registrations.py`, `services/gst_items.py`, `db/repositories_gst_masters.py`, `api/gst_masters.py`, `services/parties.py` (only the new `gst_registration_type` field), `tests/unit/engine/test_gstin.py`, `test_gst_masters.py`, `tests/unit/rules/test_gst_rules.py`, `tests/integration/test_gst_masters.py` | vouchers, bills |
| B | `engine/gst_tax.py`, `engine/gst_invoice.py`, `engine/models.py` (add optional `gst: InvoiceIn | None` to `VoucherDraft`; nothing else), `engine/validation.py` (only: call `gst_invoice.validate` when `draft.gst` is set), `services/gst_invoices.py`, `services/vouchers.py` (hook calls only), `services/gst_hooks.py` (real bodies of validate/persist/load), `db/repositories_gst_invoice.py`, `api/gst_invoices.py` and the `gst` extension of the voucher request/response in `api/vouchers.py`, `services/voucher_import.py` (optional item columns, see contract), their tests | ITC tables, 2B tables |
| C | `engine/gst_itc.py`, `services/gst_itc.py` (incl. `on_post` / `on_reverse` bodies), `db/repositories_gst_itc.py`, `api/gst_itc.py`, tests | vouchers.py |
| D | `importers/gstr2b.py`, `engine/gst_recon.py`, `services/gst_recon.py`, `db/repositories_gst_recon.py`, `api/gst_recon.py`, tests, `tests/fixtures/gstr2b/*` | itc tables' schema |
| E | `engine/gstr1.py`, `engine/gstr3b.py`, `engine/gst_tieout.py`, `engine/composition.py`, `services/gst_returns.py`, `services/gst_export.py` (JSON/Excel), `db/repositories_gst_returns.py`, `api/gst_returns.py`, tests | |
| F | `frontend/src/gst/**`, `frontend/src/api/gst.ts`, router/menu entry only | backend |
| G | `docs/test-packs/phase3-*/**`, `backend/tests/acceptance/pack_loader_p3.py`, `pack_runner_p3.py` | engine, services |

## New rule IDs (messages in accountant language, Indian number format, dd-mm-yyyy; each error carries `rule_id` and `line_no`; for an item line `line_no` is the item line number and `details.item_line_no` is set)

GSTIN, registration, masters (package A)
| ID | Rule |
| --- | --- |
| G-01 | GSTIN is exactly 15 characters in the GST format (supersedes the format-only P-01; same check on party and registration) |
| G-02 | GSTIN check character must be correct (mod-36 algorithm in PHASE3_LEGAL_VALUES.md section 2); message names the expected character |
| G-03 | The first two characters must be a state code in force on the date (rule table `gst_state_codes`); codes 96, 97 and 99 are not registration states (96 = foreign country, used only as place of supply of exports / imports of services) |
| G-04 | Registration / party state code must equal the GSTIN's first two digits; the PAN inside the GSTIN (characters 3-12) must equal the client's / party's PAN when both are known (extends P-03/P-04) |
| G-05 | Registration type must fit the client profile: client `gst_type` unregistered -> no registration; composition client -> composition registration only; regular -> regular; composition needs a category; QRMP only for regular |
| G-06 | The same GSTIN cannot have overlapping registration periods; a voucher's invoice date must fall inside the registration's period |
| G-07 | HSN must be 4, 6 or 8 digits, SAC 6 digits starting 99; goods item needs a UQC from the UQC table |
| G-08 | GST ledger roles: every ledger of a role must sit in the right group (Output/Input/RCM tax ledgers under Duties & Taxes, round-off under Indirect Expenses/Income, ITC reversal under Indirect Expenses) and belong to the client; all roles an invoice needs must be mapped before invoice mode is used |

Rates and tax engine (package B)
| ID | Rule |
| --- | --- |
| G-10 | A rate rule must exist for the HSN/SAC on the supply date (longest prefix in force); none -> rejected with the code and date. The `default` rule (services only) is used only when no prefix matches and produces a warning "default rate applied" |
| G-11 | The rate must be a slab in force on the date (`gst_rate_slabs`); special rates only through a rule row |
| G-12 | Place of supply is required and must be a valid state code; for goods default = recipient state, for services default = recipient location, never silently: the draft carries `place_of_supply` explicitly (the form prefills from the party state, the user sees it) |
| G-13 | Supplier state = place of supply -> CGST + SGST (half each); different -> IGST. A voucher cannot carry the wrong head (engine builds the heads; a tax amount typed by a caller is rejected as G-14) |
| G-14 | Tax is computed only by the engine: any tax amount, tax ledger line or rate supplied in an invoice-mode request is rejected |
| G-15 | Rounding: `gross = round_half_up(qty x rate)`, `taxable = gross - discount`, each tax head of each item line `ROUND_HALF_UP` to paise via `engine.money.round_half_up`; CGST = SGST = round(taxable x rate / 200); IGST = round(taxable x rate / 100); cess = round(taxable x cess% / 100) + specific cess |
| G-16 | Invoice total is rounded to the nearest rupee (half up) only if the client option `round_off_invoices` is set (default off); the difference (less than 1, bound 0.50 for nearest) goes to the `round_off` ledger; never to a tax ledger |
| G-17 | Quantity > 0 (max 3 decimals); rate and discount non-negative, max 2 decimals (V-03); discount not above gross; at least one item line |
| G-18 | A composition or unregistered client cannot raise a tax invoice or charge tax: document kind is Bill of Supply and all tax is zero; a regular client uses a tax invoice unless every line is exempt/nil/non-GST (then Bill of Supply) |
| G-19 | Export / SEZ: with payment -> IGST; without payment (LUT) -> zero rated; place of supply of an export is `96` (foreign country), the voucher carries `supply_category`; B2B to a GSTIN requires the party GSTIN (party type regular/sez/composition) |
| G-20 | Reverse charge: category must be in force (`gst_rcm_rules`) and consistent with the supplier (e.g. 9(4) needs an unregistered supplier); books Dr Input tax + Cr RCM payable (both lines engine-built); the supplier invoice carries no tax |
| G-21 | Exempt / nil-rated / non-GST / zero-rated lines carry zero tax and are shown separately (GSTR-1 table 8, 3B 3.1(c)/(e)); treatment comes from the rate rule, not from the user |
| G-22 | Buyer GSTIN: B2B needs a valid GSTIN (G-01/G-02) ; B2C large vs small is decided by `b2cl_invoice_value` and inter/intra-state |
| G-23 | At posting, a GST document's voucher number must be 16 characters or fewer using only letters, digits, `/` and `-` (threshold `invoice_number_max_length`); a number that would exceed it blocks posting with the reason |
| G-24 | Credit Note / Debit Note must carry the original invoice number and date, the date not after the note date, and a reason from the list |
| G-25 | Purchase: supplier invoice number (V-14 reference), supplier invoice date (not after the voucher date) and, for ITC, the supplier GSTIN are required; purchase from a composition or unregistered supplier carries no ITC |
| G-26 | The booked voucher lines must equal what the engine builds from the item lines (party Dr/Cr = invoice value, taxable lines, tax lines, round-off): checked again at approve and post, so a tampered draft cannot post |

ITC (package C)
| ID | Rule |
| --- | --- |
| G-30 | ITC status per purchase item line: `blocked` when the accountant tagged a Section 17(5) category in force on the date and did not claim an exception (exception needs a written note); the tax is then part of the cost (Dr expense includes it) |
| G-31 | `eligible` needs all Section 16(2) evidence recorded: tax document held, goods/services received (with date), supplier tax paid (in 2B or confirmed manually with note); missing evidence keeps the line `pending` with `pending_reason = evidence_missing` |
| G-32 | A line not found in the GSTR-2B of its period is `pending` (`not_in_2b`); IMS rejected/pending status keeps it pending; it moves to `eligible` when a 2B document is linked or the accountant confirms manually with a reason |
| G-33 | Claim deadline (Section 16(4), rule table): a line whose deadline passed without a claim is flagged; claiming it in 3B is refused (report, not silent) |
| G-34 | 180 days: for an invoice not paid within 180 days of its date the unpaid share of the tax (by bill allocation, proportionate) is proposed for reversal; the tool creates a DRAFT Journal (Dr ITC Reversal, Cr Input CGST/SGST/IGST/Cess) and never posts it |
| G-35 | Re-claim: when the unpaid part is paid, a DRAFT Journal reverses the reversal; only up to the amount reversed, only once per payment |
| G-36 | A reversed entry cannot be claimed again except through G-35; an entry cannot be reversed twice for the same amount |
| G-37 | Status changes are append-only events with who/when/why; amounts of an entry never change |

Reconciliation (package D)
| ID | Rule |
| --- | --- |
| G-40 | 2B file integrity: recipient GSTIN equals the registration's GSTIN, period is a month, each document has supplier GSTIN (valid format), number, date, non-negative 2-decimal amounts; any failure rejects the whole file naming the row |
| G-41 | Same file (hash) cannot be imported twice for the client; a new 2B for the same period is allowed (a later generation) and supersedes the older for reconciliation, never deleting it |
| G-42 | Result classes (deterministic, no guessing): `matched` (same supplier GSTIN, same document number normalised, same document date, taxable value and each tax head equal within the tolerance), `value_mismatch` (same key, an amount differs), `gstin_mismatch` (same number+date+taxable value but a different supplier GSTIN), `period_mismatch` (same document in the books but in a 2B of another period), `only_in_books`, `only_in_2b`; ambiguity (two candidates) is reported, not resolved |
| G-43 | A manual link or an accepted difference is stored with a mandatory note; one document links to one voucher only |
| G-44 | A 2B document marked `itc_available = no` does not make a line eligible; IMS `rejected` is shown as a risk |

Returns (package E)
| ID | Rule |
| --- | --- |
| G-50 | Every posted invoice-mode voucher of the period falls in exactly one GSTR-1 section by fixed rules (B2B, B2CL, B2CS, CDNR, CDNUR, exports, SEZ, nil/exempt/non-GST) and every credit note in CDNR/CDNUR |
| G-51 | HSN summary totals (quantity, value, taxable, taxes) equal the invoice item totals of the period |
| G-52 | GSTR-3B 3.1 outward figures equal the sales register; 4 ITC equals the ITC register by status; any difference is shown, never forced |
| G-53 | Tie-out: for each head, Books (ledger movement) vs GSTR-1 working vs GSTR-3B working vs filed figures (if entered); every difference with its cause list (unposted drafts, other-period documents, manual journals on tax ledgers) |
| G-54 | Composition client: no tax on sales, no tax lines, no ITC claimed; quarterly working = turnover x rate by category (rule table) split CGST/SGST; turnover limit check (flag) |
| G-55 | Outputs state their rule statuses; any `pending` rule in use is listed at the top of every working and export |
| G-56 | A working is saved as a version (draft/final); a final working is immutable; figures come from posted vouchers only |

Existing rules extended: V-05 (GST ledger roles), V-14 (Purchase reference), P-01 (format only) is kept for non-GST parties and delegates to G-01/G-02 when a GSTIN is given. Voucher types and the V-08 table do not change: an invoice-mode Sales voucher still needs a Cr line to Sales Accounts.

## Design decisions (to be copied into DECISIONS.md by main)
- **Tax lines are built, never typed.** A voucher request in invoice mode carries `gst` (header + item lines: ledger, item or description, HSN/SAC, qty, rate, discount, ITC tags). The service ignores/rejects ledger lines from the caller (G-14), loads the rule data for the voucher date, runs `engine.gst_tax`, and writes ordinary `voucher_lines` plus `voucher_item_lines` and `voucher_gst_line_roles`. Existing V-01..V-15, B-01 (party line bill allocation), D-01 etc. then run on the generated lines exactly as for manual vouchers. Non-invoice vouchers are unchanged (a plain Sales voucher with manual ledger lines still works for clients that do not use GST).
- **Booking of lines.** Sales: Dr party (invoice value) / Cr sales ledger per item (taxable value) / Cr Output CGST, SGST, IGST, cess / +- round-off. Purchase: Dr purchase/expense/asset ledger per item (taxable value, plus the tax when blocked: `tax_in_cost`) / Dr Input CGST, SGST, IGST, cess / Cr party / +- round-off. RCM purchase: Dr expense (taxable) / Dr Input tax / Cr supplier (taxable only) / Cr RCM payable (tax). Credit Note / Debit Note: the same lines with sides swapped. Exempt/nil/non-GST: no tax lines. Composition: no tax lines. Cr/Dr side is derived from the voucher type by the engine.
- **Bill-wise (Phase 2) still applies**: the party line of a bill-wise party carries a `new_ref` allocation for the full invoice value, due date as before. The prefill (Reference No) is done by the service, as the screen did in Phase 2.
- **Rate precision.** `quantity` 3 decimals, `unit_rate` 2 decimals (V-03 unchanged: amounts with more than 2 decimals are rejected, prices included), so `gross = round_half_up(qty x rate)` is the only rounding before tax; the database re-checks it with `round()` (half away from zero equals half up for non-negative values). Discount is an amount, not a percentage, in Phase 3 (a percentage input converts in the screen, shown to the user, rounded half up; suggestion).
- **Invoice-level round-off** is optional per client (column `clients.round_off_invoices`, migration 0009; default off) so no silent rounding of the party balance happens.
- **ITC state lives outside the voucher.** Posted vouchers stay immutable; `itc_entries` (identity and amounts immutable by trigger) holds status and evidence; `itc_status_events` is append-only; reversals are separate draft Journals linked in `itc_reversals`. Books record the input tax in the Input ledgers when the purchase posts; GSTR-3B 4(A) takes only `eligible` entries (claimed), the rest is shown as a reconciling item "credit in books not claimed" so the Input ledger to ITC register tie is visible.
- **No guessing of 17(5) or RCM.** The accountant tags the purchase line (the item master offers a default to pre-fill, always shown). Untagged = not blocked, not RCM, and the working lists "lines with no category tag" for review only when the item master marks a default.
- **Period of an invoice** for GSTR-1 = invoice date (voucher date for sales); for ITC = month in which the claim is made (`claimed_in_period`), default the 2B month where linked, else the voucher month; the accountant can change before the 3B working is made final.
- **Return period kinds**: monthly clients use month; QRMP clients use quarter for GSTR-3B (Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar) and monthly PMT-06 is out of scope; composition CMP-08 quarterly, GSTR-4 yearly.
- **Reconciliation matching**: document number normalisation = upper-case, strip spaces, leading zeros and the characters `/ - . \`; date equal; tolerance configurable (`GST_RECON_TOLERANCE`, default 0.00, not law).
- **Outputs.** Always an Excel working (openpyxl, one sheet per table, numbers as numbers). JSON: GSTR-1 and GSTR-3B in the portal offline-tool shape **as understood**; because no official schema could be read, JSON export is flagged "not validated against the portal schema" in the response and in the file's `_meta` key only if the portal ignores it (to be confirmed with a real sample); the owner supplies a sample before this is declared official.
- **Database changes by agents**: not allowed; report to main.
- **Voucher delete for drafts** relies on `ON DELETE CASCADE` of the GST child tables (0010); `itc_entries` exist only for posted vouchers.

## Package details

### A — registrations, GSTIN, masters, rule loaders (3.1)
Builds: `engine/gstin.py` (`validate_gstin(text, state_codes, on_date) -> list[ValidationError]`, `gstin_check_char(first14)`, PAN extraction; pure), `engine/gst_masters.py` (`validate_registration`, `validate_item`, ledger-role validation G-08), `rules/gst_rules.py` (loader functions returning the frozen dataclasses of `gst_types.py`: `state_codes(conn, on)`, `rate_for(conn, hsn_sac, supply_kind, on)` -> (RateRule, is_default) via pure `pick_rate(rules, ...)`, `slabs`, `rcm_rule(key, on)`, `blocked_rule(key, on)`, `itc_condition(key, on)`, `threshold(key, on)`, `composition_rule(category, on)`, `rule_status_summary(...)`; overlap detection of periods per key, unit-tested), services and API for registrations (CRUD, deactivate, ledger roles), item master (CRUD, search by HSN), `GET` of the rule tables for the screens (read-only), party `gst_registration_type`.
Tests (red first): check digit with the synthetic GSTINs of PHASE3_LEGAL_VALUES.md and the sample `27AAPFU0939F1ZV`; one wrong character per position; names `test_G02_wrong_check_character_rejected`; state-code table by date (28 and 99 refused for a registration); G-05 matrix; longest-prefix pick by date (3004 on 2025-09-21 = 12%, on 2025-09-22 = 5%; 851712 on 2020-03-31 / 2020-04-01); default rule warning; overlap detection; integration: seeds load, all rows have a status, registrations CRUD with DB constraints.

### B — tax engine and invoice-mode vouchers (3.2, 3.3)
Builds: `engine/gst_tax.py` (pure: `place_of_supply_head`, `compute_item`, `compute_invoice`, RCM, treatments, cess; uses `engine.money.round_half_up` only), `engine/gst_invoice.py` (turns `InvoiceIn` + rule data into voucher lines + roles + item rows; validates G-10..G-26), models extension, hooks in `services/vouchers.py`, `services/gst_invoices.py` (create/update draft in invoice mode, preview endpoint without saving), voucher response extended with `gst`, Excel voucher import with optional item columns (`item_name|description, hsn_sac, qty, rate, discount, itc_category`, one row per item line, rows grouped by voucher_ref).
Tests: hand-calculated literals: intra-state 18% on 1,000.00 -> 90.00 + 90.00; inter-state -> 180.00; odd paise: taxable 0.05 at 5% -> half-up cases; qty 3 x rate 10.01 = 30.03; qty 2.5 x 10.25 = 25.625 -> 25.63 (half up); discount; mixed rates in one invoice (each line rounded, header total is the sum of lines, never re-rounded); 12/28% before 22-09-2025 vs 5/18% after on the same HSN; cess; RCM lines; export LUT zero rated; round-off option; composition client refused tax; typed tax rejected (G-14); tampered lines at approve rejected (G-26); voucher number over 16 chars blocked at post (G-23); integration: draft -> approve -> post -> reverse of an invoice-mode voucher keeps item lines and the reversal mirrors tax lines; DB CHECK rejects a forged tax amount.

### C — ITC (3.4, 3.5)
Builds: `engine/gst_itc.py` (pure: `classify(entry, conditions, blocked_rules, doc_2b_state, on_date)`, `claim_deadline`, `unpaid_share(entry, payments)`, `reversal_amounts`), `services/gst_itc.py` (`on_post` creates `itc_entries` for each purchase/debit note/credit note GST item line, `on_reverse` marks them reversed through an event, evidence update, manual confirm, status refresh from 2B links, list/aging of 180-day exposure, create reversal draft journal via `services/vouchers.create_draft` with `ledger roles`, re-claim draft), API. Payment amounts for the 180-day rule come from Phase 2 bill allocations (`against_ref` on the supplier's reference) via `services/bills`; no new payment table.
Tests: 17(5) tagging with and without exception; evidence matrix (one missing condition each) -> pending; 2B missing -> pending; day-180 boundary (invoice 1-4-2026: 179, 180 and 181 days; payment on day 180 counts, day 181 does not: rule text to be confirmed by CA, recorded in DECISIONS); proportionate reversal on part payment with paise (hand-computed, half up, last head takes the remainder so heads add to the total); re-claim cap; draft journal lines balance; entries and events immutable (DB test).

### D — GSTR-2B / IMS import and reconciliation (3.6)
Builds: `importers/gstr2b.py` (JSON in the portal's GSTR-2B structure: `data.docdata.b2b/cdnr/...`; Excel as downloaded from the portal; IMS Excel/JSON; written against fixtures; **needs a real sample file from the owner**, until then fixtures are hand-made from the documented structure and marked as such), `engine/gst_recon.py` (pure matcher with the six classes, normalisation, tolerance), `services/gst_recon.py` (import with integrity checks and hash, reconciliation report for a registration and period, links, accept difference, effect on ITC entries: set `supplier_tax_paid` / pending reason through C's service function `gst_itc.apply_2b_result`, defined by C in step 3.4 and called by D only after C is merged; until then D returns the results without side effects).
Tests: each class with hand-made cases (document number `INV-001` vs `inv/001`; GSTIN differs by one character; amount 1.00 off; invoice in the next month's 2B; two candidates -> reported ambiguous); tolerance zero; wrong recipient GSTIN file rejected; duplicate import refused; one-to-one link rule.

### E — GSTR-1, GSTR-3B, tie-out, composition, outputs (3.7, 3.8)
Builds: pure `engine/gstr1.py` (classification G-50, tables, HSN summary G-51, documents issued from voucher number ranges incl. cancelled/reversed counts), `engine/gstr3b.py`, `engine/gst_tieout.py`, `engine/composition.py`, services for saving versions, filed-figure entry, Excel and JSON exporters, API.
Tests: hand-calculated month: 12 invoices over B2B/B2CL/B2CS/exports/nil, 2 credit notes, one RCM purchase, blocked and pending credits; expected 3B figures typed literally; tie-out with a deliberately posted manual journal on an output tax ledger; QRMP quarter; composition quarter with limit crossing; exporters produce numbers equal to the working (round trip from the file).

### F — screens (3.9)
Registrations + ledger-role map, item master, rule-table viewer (status badges: pending shown in amber on every screen that uses a rule), invoice-mode voucher entry (items grid; tax lines shown read-only as the engine's preview; place of supply visible and editable; warnings for default rate; ITC tag per purchase line), ITC register with evidence panel and 180-day exposure, 2B import + reconciliation (six tabs), GSTR-1 working, GSTR-3B working, tie-out, composition working, downloads. Dense, table-first; no float arithmetic (BigInt paise helpers as in 1.9); no tax calculation in the frontend.

### G — test pack and runner (3.10, after merge)
Pack `docs/test-packs/phase3-<name>/` (client.yaml, rules snapshot note, registrations.csv, items.csv, vouchers.csv in invoice mode, gstr2b_*.json/xlsx, expected answers: invoice-wise tax, GSTR-1 tables, GSTR-3B figures, ITC status per line, reconciliation classes, 180-day list) + hand-worked `WORKING.md` + `VERIFICATION_SHEET.xlsx` for the accountant + runner `pack_runner_p3.py` as in 2.9. Deliberately wrong items to be caught: bad GSTIN, bad check digit, state/GSTIN mismatch, wrong head (IGST instead of CGST+SGST typed), blocked credit claimed, invoice missing in 2B, GSTIN mismatch in 2B, value mismatch, 181-day unpaid invoice, composition client charging tax, unknown HSN. Acceptance (Phase 3 prompt): all caught, GSTR-1 and 3B numbers equal the accountant's.

## Acceptance check for Phase 3 (step 3.11)
Full suite (`pytest -m "integration or not integration"`), `ruff check .`, all rules G-xx have named tests, pack runner green except documented NOTES, DB guards (immutable item lines after post, forged tax rejected by CHECK, itc entry amounts immutable, 2B documents not editable), grants test (anon/authenticated hold nothing on the new tables and functions), legal-values report to the owner (what is still `pending`).

## Suggestions (not built)
Value-conditional rate rules (per unit value bands); discount percentage and tax-inclusive pricing; e-invoice IRN/QR and e-way bill; import of goods (bill of entry) ITC; ISD; Rule 42/43 common-credit reversal; interest on late ITC reversal and late tax payment (Section 50); GSTR-9/9C; ITC-04; PMT-06 for QRMP; due-date calendar; cancelled-invoice handling beyond reversal; multi-GSTIN stock transfers (Rule 54 / own-GSTIN supplies); TCS by e-commerce operators under GST (Section 52); portal API integration (filing stays manual).
