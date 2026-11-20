# Phase 7 plan - Document input and AI (Tally import / export, documents, OCR, LLM extraction, draft builder, narration suggestions, approval queue, security)

Written 2026-11-20 (planning agent, branch `p7-plan`) under the working mode of CLAUDE.md section 6. Scope: `docs/PHASE_PROMPTS.md` Phase 7. Interfaces: `docs/PHASE7_API_CONTRACT.md`. Decisions: `docs/decisions_parts/P7.md`.
Schema (migration **0018**) is written FIRST and is the shared contract: **agents never edit it**; a needed change goes to the main agent. Step 7.0 (this commit) wrote migration, rule catalogue (`engine/doc_types.py`), the LLM interface and fake (`ai/llm.py`, `ai/fake.py`), service hooks (`services/ai_hooks.py`), config getters, seven empty routers and tests; it applied 0018 to the TEST schema only and ran the schema test once.
**Nothing in this phase changes how vouchers work.** Every proposal (an extracted invoice, a Tally voucher) becomes a DRAFT voucher created through `services/vouchers.py` (V-01..V-15 and the GST / TDS / inventory rules apply unchanged), and waits in the approval queue. Approve and post stay the normal, explicit voucher actions, and the database refuses them while the queue item is not accepted.

## Decisions that shape the design (details in `docs/decisions_parts/P7.md`)
1. **AI reads, Python calculates, a person decides.** The model returns only what is *printed* (strings with page / position / confidence). Every amount the draft carries is recomputed by the existing GST engine from taxable value, HSN and date; printed tax and totals are used only for comparison. A draft is never built while an `error` or `review` finding exists, so a draft never carries data we know is inconsistent.
2. **One queue for everything proposed** (`approval_queue_items`, kind `invoice` or `tally_voucher`). Bank-narration suggestions are advice shown on the bank screen, not queued, because they never create anything.
3. **Evidence is immutable.** The model's answer (`llm_calls.response_raw`, `extractions.payload`) never changes. Edits by the accountant live in `approval_queue_items.edited_payload`; each edit re-runs the engine and rebuilds the draft in place. A tally voucher's proposal is stored in `edited_payload` at creation (the XML stays the original).
4. **The database enforces the acceptance gate** (`vouchers_ai_queue_guard`, `approval_queue_accepted_complete`): the strongest answer to "nothing wrong is ever posted" is that a queued draft cannot be approved or posted, even by a buggy caller, until a person accepted its item with zero blocking findings.
5. **No LLM unless the client's switch is on** (`client_ai_settings`, default off, enabling needs who / when / data class / note). Without a model the same screens work with a *manual* extraction typed by the accountant (same schema, same engine checks).
6. **Mask before sending, restore locally.** PAN, Aadhaar, bank account numbers and GSTINs are replaced by numbered tokens (`<PAN_1>`...) before any call; tokens in the answer are replaced back by Python from an in-memory map that is never stored. A final scan refuses to send if anything of those kinds is left.
7. **Expected failures are results, not exceptions.** The request transaction rolls back when a handler raises (`api/deps.py`), which would erase the audit row of a blocked / invalid / failed model call. Services return a result object for: LLM disabled, provider error, invalid JSON, schema-invalid answer, engine findings; the endpoint answers with a normal JSON response (200 or 409 / 422 via `JSONResponse`), so `llm_calls` and the invalid `extractions` row are committed. Services raise `ServiceError` only for bad requests (unknown id, wrong client, terminal state).
8. **Files are private.** Stored under `DOCUMENT_STORE_DIR` (absolute, outside the repo), file name generated from client id + SHA-256 (never from the upload name), resolved and checked to stay inside the root, served only through an authenticated API call (`X-User`), never by a URL or static mount.
9. **Tally masters are suggested, then confirmed, then applied.** The import never creates a ledger on its own and never applies opening balances (D-33). Vouchers are queued only after the masters they use are mapped.
10. **Learning only from the accountant.** Party / line mappings and narration rules are written when a person accepts (queue accept, suggestion accept), from the *final* values, never from the model's output.

## Data flow
```
upload (A) --> documents (hash, private file) --> text (A: pdf text | OCR) --> [client LLM switch on?]
   no: accountant types the extraction (manual)          yes: mask (C) -> OpenRouter (C) -> llm_calls (raw) -> schema (D)
        \_____________________________ extractions (immutable payload) ______________________________/
   engine checks (D: D-05..D-19) -> mappings (E: D-20..D-24) -> no blocking finding? -> draft voucher via voucher service (E)
   approval_queue_items (pending: findings, edited_payload, draft_voucher_id)  <-- F: claim / edit (re-run D+E) / accept / reject
   accept (needs draft + 0 blocking, warnings acknowledged) -> learn mappings, link document -> voucher (source)
   -> THEN the normal voucher approve -> post (database refuses both before accept)
Tally XML (B): documents(tally_xml) -> parse -> mapping report + tally_master_map (suggested) -> accountant confirms -> apply masters
   -> vouchers: all ledgers mapped -> draft via voucher service + queue item (tally_voucher) ; else queue item with D-3x review finding
Tally export (B): posted vouchers + masters -> XML -> documents(tally_export) + tally_exports
```

## Database (migration 0018; 14 tables, no money column)
| Table | Role | Key guards |
| --- | --- | --- |
| `client_ai_settings` | per-client LLM switch (absent = off) with data class, who / when / why | enabling needs `enabled_by`, `enabled_at`, note |
| `documents` | one row per stored file: type, client, FY, name, content type, size, SHA-256, storage key, page count, status | unique (client, sha256) = D-02; storage key CHECK (no `..`, no leading `/`, no drive letter, no `//`); file identity immutable; never deleted; doc type frozen once an extraction exists |
| `document_texts` | text per page and method (pdf_text / tesseract / paddleocr / manual), optional word boxes + confidence | insert only |
| `document_vouchers` | document <-> voucher links (source / supporting) | no update; delete only while the voucher is a draft; composite client FKs |
| `llm_calls` | every call incl. refused ones: purpose, provider, model, prompt version, MASKED prompt + hash, masking counts (never values), raw answer, status, tokens, latency | insert only; CHECK a sent call carries a masked prompt (`masking_applied`); CHECK blocked calls hold no prompt / answer; CHECK no `sk-or-` key text anywhere |
| `extractions` | validated JSON of one extraction (llm or manual), version per document, schema version, valid / invalid + reason | immutable (only `superseded_at`, once, and only when no live queue item uses it) |
| `party_mappings`, `line_mappings` | saved supplier -> party ledger (by GSTIN or normalised name), line -> ledger / item (by HSN or description, optionally scoped to a supplier) | normalised keys by CHECK; composite client FKs (a client's mapping can only use its own ledgers) |
| `narration_rules`, `narration_suggestions` | learned narration -> ledger counts; suggestions (rule / llm) with reason and decision | rule key normalised by CHECK; suggestion changes only once (accepted / rejected), never deleted |
| `tally_imports`, `tally_master_map`, `tally_exports` | one import per document + mapping report; persistent Tally name -> group / ledger / stock item decisions; export log | confirmed needs a target; created ledger needs its group; confirmed / create need a person and a time; exports insert only |
| `approval_queue_items` | the queue: kind, document, extraction or Tally import + source ref, status, edited payload, findings, blocking / warning counts, draft voucher, reviewer, acknowledgements, accept / reject facts | created pending; path pending <-> in_review -> accepted / rejected (terminal); accepted needs person + draft + `blocking_count = 0` + draft voucher still a draft; rejected needs reason and no live draft; identity immutable; never deleted; one live item per extraction; one live item per Tally voucher ref |
| trigger on `vouchers` | `vouchers_ai_queue_guard` | a voucher in the queue cannot move to approved / posted unless its item is accepted |
Every table: RLS enabled, no policies; function privileges revoked at the end (0004 pattern); functions pin `search_path`; schema-agnostic.

## Rules (IDs used in finding messages, queue findings, test names)
| ID | Rule |
| --- | --- |
| D-01 | File type is checked by content, not by name: PDF, PNG, JPEG, TIFF (documents) or XML (Tally); size within the limit |
| D-02 | The same file (SHA-256) is never stored twice for a client; the existing document is shown instead |
| D-03 | Possible duplicate invoice: same supplier GSTIN (or name) + invoice no (+ date / total) already in a voucher or another extraction |
| D-04 | The model's answer is not valid JSON or does not fit the schema: extraction is invalid, nothing is drafted, never repaired silently |
| D-05 | Every extracted field carries a page / position source and a confidence; a required field that is missing is an error; confidence below the configured minimum is a warning |
| D-06 | Amounts must be plain decimals with at most 2 places and not negative; dates must parse; otherwise error (rejected, not rounded) |
| D-07 | Supplier / buyer GSTIN must be valid (format, state code, check character) |
| D-08 | For a purchase the buyer GSTIN must be one of the client's registrations; for a sale the supplier GSTIN must be; else error |
| D-09 | Direction cannot be decided (client GSTIN on neither side, or on both) or differs from the type chosen at upload: review |
| D-10 | Line taxable value recomputed (quantity x rate - discount) differs from the printed taxable value |
| D-11 | Tax recomputed by the GST engine from the rate table (HSN, date) differs from the printed tax amount, or the printed rate differs from the table |
| D-12 | Tax type does not fit the place of supply (CGST+SGST on an inter-state supply, IGST on an intra-state one) |
| D-13 | Printed totals (taxable, each tax, grand total with round-off) differ from the sum recomputed from the lines |
| D-14 | Invoice date outside the client's financial years, in a locked period, or in the future (the voucher service's V-06 / V-07 remain the authority) |
| D-15 | Printed rate is not a rate of the rate table on that date (rate table gap is reported as pending, never filled in) |
| D-16 | Line has no HSN / SAC, or an HSN not in the item master where the rate rule needs it: review |
| D-17 | Printed line sum and printed lines count disagree with the lines extracted (a line was probably missed) |
| D-18 | Bank statement: printed running balance (or closing balance) differs from opening balance + credits - debits |
| D-19 | Bank statement: a row has both a debit and a credit amount, or neither |
| D-20 | Supplier / buyer not mapped to a party ledger: review (never auto-created) |
| D-21 | A line has no saved ledger mapping: review |
| D-22 | Party GSTIN on the document differs from the GSTIN saved on the mapped party ledger: error |
| D-23 | Place of supply cannot be determined from the document (and the party master has no state): review |
| D-24 | Mapping is ambiguous (one key points to several ledgers): review, no choice is made |
| D-25 | Draft was built through the voucher service; its own rules (V-01..V-15, B-xx, G-xx, T-xx, S-xx) are returned as findings unchanged |
| D-26 | A mapping is saved only from the accountant's accepted values (never from the model's output) |
| D-27 | Draft already exists for this queue item: it is rebuilt in place while the item is open, never duplicated |
| D-30 | Tally XML must be well-formed and contain no DTD / entities; encoding (UTF-8 / UTF-16) and illegal character references handled; else the import fails with the reason |
| D-31 | Tally group maps to a system or client group: predefined Tally groups by table, custom groups by their parent chain; unknown -> suggested, accountant confirms |
| D-32 | Tally ledger whose name already exists in another group (or under another mapping) is not overwritten: review |
| D-33 | Opening balances in the Tally file are REPORTED in the mapping report and never applied by the import |
| D-34 | Voucher types: Sales, Purchase, Payment, Receipt, Contra, Journal, Credit Note, Debit Note are drafted; every other type is skipped and listed with the reason |
| D-35 | Tally debit / credit sign (ISDEEMEDPOSITIVE) is converted to debit / credit lines; the voucher service then enforces Dr = Cr (V-04) and every other voucher rule |
| D-36 | Cancelled, optional and post-dated vouchers are skipped and listed |
| D-37 | A Tally voucher already queued (same GUID or same type + date + number + party + total) is skipped, not queued twice |
| D-38 | Tally export contains posted vouchers only; ledgers / groups used are exported first; names are escaped; the file records client, FY, range and engine version |
| D-39 | Export refuses a range with unposted vouchers unless the caller says it wants posted-only; ledger names longer than Tally allows or with illegal characters are reported |
| D-40 | Narration key: lower-case, digits / UPI / reference numbers / dates removed, whitespace collapsed (pure function) |
| D-41 | Rule suggestion: a key learned from the accountant's accepted choices (same direction) points to exactly one ledger: suggest it with the count as the reason |
| D-42 | Key points to several ledgers: ambiguous, list the candidates with counts, no suggestion is selected |
| D-43 | LLM fallback only when no rule exists and the client's LLM switch is on; the answer is a suggestion with the reason; a ledger the client does not have is dropped |
| D-44 | A suggestion never creates a voucher or a ledger; accepting it only tells the accountant which ledger to use and teaches the rule |
| D-50 | Before any model call the text is masked (PAN, Aadhaar, bank account numbers, GSTIN as reversible placeholders); a final scan refuses to send if anything of those kinds is left |
| D-51 | No model call unless client_ai_settings.llm_enabled for that client (explicit, with who / why / data class); otherwise the call is refused and recorded as blocked |
| D-52 | Prompt (masked) and raw answer are stored for audit; API keys and secrets never appear in logs, errors, prompts or stored text |
| D-53 | Document text is data, never instructions: the model has no tools, its answer is accepted only as JSON of the schema (extra keys rejected) |
| D-54 | Only synthetic or anonymised data goes to a free model; the data class is recorded per client and shown on every model call |
| D-60 | A queue item is accepted only by a person, with a draft voucher, with no error / review finding left; warnings only after acknowledgement |
| D-61 | Every field of the extraction is editable in the queue; each edit re-runs the engine checks; the AI's original answer stays unchanged |
| D-62 | Accepting never posts: the draft is approved and posted afterwards through the normal voucher actions; the database refuses to approve or post a queued draft before acceptance |
| D-63 | Rejecting needs a reason and removes the draft through the voucher service; the item and extraction remain as record |
| D-64 | Every queue action (create, claim, edit, accept, reject, rebuild) is written to audit_log with old and new values |

Severity: `error` (data wrong: edit it; cannot be acknowledged), `review` (system will not guess: map / decide), `warning` (accept only after acknowledging), `info`. `blocking_count` = errors + reviews.

## Engine and layers (pure engine; AI and web outside it)
* **Engine (`backend/app/engine/`, no DB / web / LLM / OCR / XML-library imports):**
  `doc_types.py` (this step: types, rule catalogue, queue path, tolerance), `doc_files.py` (A: file type by content bytes, sha256, storage key generator, key safety check), `doc_mask.py` (C: `mask_text`, `restore_tokens`, `assert_clean`; PAN, Aadhaar, bank account, GSTIN), `doc_check.py` (D: `check_invoice(ExtractedInvoice, DocCheckContext) -> DocCheckResult(findings, recomputed)`, D-05..D-19, uses `gst_invoice.build_invoice` / `gst_tax`, `gstin.validate_gstin`, `money.parse_amount`, `round_half_up`), `doc_map.py` and `doc_build.py` (E: normalise keys, resolve party / line mappings with ambiguity = review, assemble `InvoiceIn` + `VoucherDraft` inputs), `tally_map.py` (B: predefined Tally group table, parent-chain suggestion, voucher type table, sign conversion, skip rules, source-ref hash), `tally_export.py` (B: plain data -> XML text), `narration.py` (F: `narration_key`, `suggest(key, direction, rules) -> Suggestion | Ambiguous | None`).
* **AI layer (`backend/app/ai/`, no accounting):** `llm.py`, `fake.py` (this step), `openrouter.py` (C, httpx, 60 s timeout, key from config only), `prompts.py` (D, versioned, fixed text; document text is passed only as data), `schemas.py` (D, Pydantic v2, `extra="forbid"`, amounts as strings), `storage.py` (A), `ocr.py` (A).
* **Importers (`backend/app/importers/`):** `tally_xml.py` (B, uses `defusedxml`; pure parse to dataclasses).
* **Services (take a SQLAlchemy `Connection`, never commit, audit-log every change):** `documents` (A), `tally_import`, `tally_export` (B), `ai_settings`, `llm_gateway` (C), `extractions` (D), `doc_mappings`, `doc_drafts` (E), `approval_queue`, `narration` (F), `ai_hooks` (this step).
* **Draft building (E)** builds `VoucherDraft` in GST invoice mode (`gst=InvoiceIn`, item lines with ledger / item ids from the mappings, `place_of_supply`, counterparty GSTIN) and calls `vouchers.create_draft` / `update_draft` (rebuild in place, D-27). The voucher service's own `ValidationError`s (V-xx, G-xx, T-xx, S-xx, B-xx) come back as `error` findings tagged D-25 with their original rule id in the message.
* **Tally vouchers** are drafted in plain-lines mode (ledger lines), voucher type by table (D-34); whatever the voucher service refuses (V-04 unbalanced, V-09 narration, V-14 reference, B-01 bill allocation, G-xx tax-ledger rules) becomes a finding on the queue item for the accountant to fix. Package B must check how the Phase 3 / 4 rules treat tax ledger lines in plain-lines mode and report gaps instead of bypassing them.
* **Narration (F):** rule suggestion first (D-41 / D-42), LLM only when no rule exists and the switch is on (D-43; the prompt holds the masked narration, direction and the client's ledger names, no amounts or balances; the answer must pick a ledger id from the list given). Always stored as `narration_suggestions` with its reason; accepting teaches the rule (D-44).

## How "nothing wrong is ever posted" is enforced, and tested
Layers, from the inside out (each has its own test, and G proves them together):
1. **Reading is untrusted:** schema-invalid or non-JSON answers produce an `invalid` extraction and no draft (D-04); tokens that are not in the map, extra keys, wrong types, amounts with more than 2 decimals, impossible dates are rejected (D-06, D-53). Tests: Pydantic schema tests with injected bad answers.
2. **Engine recomputes** tax and totals with the GST engine and compares with printed values (D-10..D-13, D-15); the draft uses recomputed values only. Tests D package: hand-calculated invoices with an injected wrong tax, wrong total, wrong rate, missed line, wrong GSTIN, wrong direction; each yields exactly the expected rule id and severity.
3. **Mapping never guesses** (D-20..D-24): unknown party / ledger, ambiguous mapping, missing place of supply -> `review`, no draft, nothing created.
4. **No draft while blocking findings exist** and the voucher service validates the draft again (V-xx etc., D-25). Tests E.
5. **Queue acceptance** needs a person, a draft, zero blocking findings, every warning acknowledged by rule id + field (D-60); edits re-run everything (D-61). Tests F with the real services.
6. **Database gate:** `approval_queue_accepted_complete` (accept needs `blocking_count = 0` and a draft) and `vouchers_ai_queue_guard` (a queued voucher cannot be approved or posted before acceptance), plus the older guards (posted immutable, balanced). Tests: `test_documents_schema.py` (this step) tries to approve a queued draft and to accept with a blocking count, and must be refused by the database itself.
7. **Hook with a friendly message:** `ai_hooks.guard_voucher_change` is wired by F into `vouchers.approve` / `vouchers.post` (so the API returns `queue_not_accepted` before the trigger fires); F also wires the delete-draft path (unlink first via reject).
8. **Acceptance pack (G):** sample invoices and bank statements with injected extraction errors fed through `FakeLlmClient` scripted answers (and one pack run with a manual extraction): the runner asserts, for every sample, that the expected finding appears with the expected rule id, that no voucher with status approved / posted exists that came from a queue item that has a blocking finding, that the count of posted vouchers equals the count of accepted items, and that every posted voucher equals the engine's recomputation to the paisa. It also proves the security rules: the fake client's recorded requests contain no PAN / Aadhaar / account number, a client with the switch off makes zero calls, `llm_calls` holds the masked prompt for each call and no key text.

## Dependencies per package (python packages and binaries)
Added now to `backend/pyproject.toml` (all pure Python): **`pypdf`** (text PDFs, package A), **`defusedxml`** (safe parsing of Tally XML: the standard library parser expands entities; package B), **`httpx`** (OpenRouter client; was dev-only, package C). The owner must run `pip install -e .` (or `pip install pypdf defusedxml httpx`) in the project venv once; nothing imports them at module load in the engine, and tests that need them use `pytest.importorskip` so the fast suite still runs without them.
| Package | Python packages | Binaries |
| --- | --- | --- |
| A documents | `pypdf` (required); `reportlab` (already present) builds test PDFs. OCR extras, optional: `pytesseract`, `Pillow`, `pypdfium2` or `paddleocr`, `paddlepaddle`, `pypdfium2` | none for text PDFs. Scanned PDFs / photos need an OCR engine (below) |
| B Tally | `defusedxml` | none |
| C gateway | `httpx` | none |
| D, E, F, G | none new | none |
**What the owner must install for OCR (only to read scanned PDFs and photos; text PDFs and Tally need none of it):** Option 1, Tesseract (light): install the Tesseract program for Windows (UB Mannheim build), add its folder to `PATH` or set `TESSERACT_CMD`, then `pip install -e ".[ocr-tesseract]"`; English plus Hindi language data if needed. Option 2, PaddleOCR (heavier, better on tables): `pip install -e ".[ocr-paddle]"` (hundreds of MB; first run downloads models). Tests never need either: `app/ai/ocr.py` defines an `OcrEngine` interface and the tests use fakes; a missing engine raises `ocr_unavailable` with these instructions.
Environment (placeholders in `.env.example`; key and model are set in `.env`, `DOCUMENT_STORE_DIR` is not yet): `DOCUMENT_STORE_DIR`, `OPENROUTER_API_KEY`, `LLM_MODEL`, optional `AI_MIN_CONFIDENCE`, `MAX_UPLOAD_BYTES`.

## Security checklist (D-50..D-54)
* Masking function is pure and tested with literal examples (valid and near-miss PAN / Aadhaar / account / GSTIN, adjacent text, repeated values get one token, restore round-trip, an invoice number of 12 digits is masked and restored without loss). `assert_clean` is a second, independent scan; the gateway calls both and refuses to send otherwise.
* `llm_calls` records masked prompt, raw answer, model, prompt version, data class of the client; the key is read inside the OpenRouter client only; error messages are built from status code and a fixed text; a unit test greps stored rows and log output for the key text; the DB CHECK `llm_calls_no_secret` is a tripwire.
* Prompts treat the document as data (fixed system prompt, delimiters, no tools, JSON only, `extra="forbid"`), so text such as "ignore previous instructions" in a PDF cannot change anything but the extracted strings, which are then checked by the engine and a person (D-53). G contains one such sample.
* Only synthetic or anonymised data goes to free models (CLAUDE.md 4); `data_class` is stored per client and shown with each call; the dev database is synthetic only.

## Packages and file ownership (parallel agents never collide)
After 7.0 nobody edits `main.py`, `database/**`, `engine/doc_types.py` signatures (add optional fields at the end via the main agent), `services/ai_hooks.py` bodies, `ai/llm.py`, `config.py`, `api/errors.py`. `services/vouchers.py` is edited **only by package F** (the `guard_voucher_change` hook calls and delete-draft handling). Decision rows go to `docs/decisions_parts/<pkg>7.md`, status to `docs/progress_parts/<pkg>7.md`; tests in new files named for the area. Database runs through `scripts/dbrun.sh`.
| Pkg | Creates / edits | Never touches | Depends on |
| --- | --- | --- | --- |
| A documents, storage, OCR | `engine/doc_files.py` (D-01), `ai/storage.py` (`PrivateStore`: save / open / exists, traversal-safe), `ai/ocr.py` (`OcrEngine` interface, `PdfTextReader` via pypdf, lazy `TesseractOcr`, `PaddleOcrEngine`, `ocr_for`), `services/documents.py` (`register` upload with hash + duplicate check D-02, `read_bytes`, `extract_text`, `link_voucher` / `unlink`, list, get), `db/repositories_documents.py`, `api/documents.py`, `api/schemas_documents.py` | Tally, extraction, queue | none |
| B Tally import / export | `importers/tally_xml.py`, `engine/tally_map.py`, `engine/tally_export.py` (D-30..D-39), `services/tally_import.py` (parse, report, master map decisions, apply masters through the existing group / ledger / item services, queue vouchers via `ai_hooks.add_queue_item`), `services/tally_export.py`, `db/repositories_tally.py`, `api/tally.py`, `api/schemas_tally.py` | extraction, mappings, queue logic | A for `read_bytes` / `register` (integration only; units use literal XML) |
| C LLM gateway, masking, switch | `engine/doc_mask.py` (D-50), `ai/openrouter.py`, `services/ai_settings.py` (D-51, D-54), `services/llm_gateway.py` (`call(...) -> GatewayResult`, writes `llm_calls`, D-52), `db/repositories_ai.py`, `api/ai_settings.py`, `api/schemas_ai.py` | prompts, schemas | none (`ai/llm.py`, `ai/fake.py` exist) |
| D extraction + engine checks | `ai/schemas.py`, `ai/prompts.py`, `engine/doc_check.py` (D-04..D-19), `services/extractions.py` (`run_llm_extraction(conn, ..., gateway)`, `enter_manual`, `check`, versions, supersede), `db/repositories_extractions.py`, `api/extractions.py`, `api/schemas_extractions.py` | gateway internals, builder | C only for the `gateway.call` signature (injected; fake in tests); A for page text (injected) |
| E mappings + draft builder | `engine/doc_map.py`, `engine/doc_build.py` (D-20..D-24, D-27), `services/doc_mappings.py` (CRUD of party / line mappings, resolve), `services/doc_drafts.py` (D-25, D-27: build / rebuild / delete draft through the voucher service, GST invoice mode), `db/repositories_doc_mappings.py`, `api/doc_mappings.py`, `api/schemas_doc_mappings.py` | extraction, queue | none (literal `ExtractedInvoice` data; Phase 3 services read-only) |
| F approval queue + narration | `engine/narration.py` (D-40..D-42), `services/approval_queue.py` (list, get, claim / release, edit -> re-run D + E, accept with learning D-26 and document link, reject D-63, audit D-64), `services/narration.py` (D-41..D-44, uses C gateway for the fallback), `db/repositories_queue.py`, `api/approval_queue.py`, `api/narration.py`, schemas, **and the hook calls in `services/vouchers.py`** | engines of A..E | D, E (re-run on edit), C (fallback), B / D (items already created through `ai_hooks.add_queue_item`) |
| G test pack + acceptance | `docs/test-packs/phase7-*/**` (synthetic text-PDF invoices built by script with reportlab, scripted extractions with injected errors, bank statements, a Tally XML with traps), `backend/tests/acceptance/pack_loader_p7.py`, `pack_runner_p7.py`, `scripts/build_verification_sheet_p7.py`, `docs/PHASE7_SIGNOFF.md` | engines, services | A..F merged |
| UI (separate, later) | `frontend/src/screens/` approval queue (document image beside the draft, editable fields, accept / reject), documents, Tally import report, AI settings | backend | contract; F for the final shapes |

**Parallel split.** Wave 1 (no dependencies between them): **A, B, C, D, E** (five agents; D and C meet only through the injected gateway signature, B and A only through `read_bytes`). Wave 2: **F** (needs D and E merged; C for the narration fallback). Wave 3: **G** acceptance, then the UI package. Shared-file conflicts: only `services/vouchers.py` (F only); `main.py` / config / migrations are closed.

## Steps
7.0 plan + schema + rule catalogue + LLM interface + hooks + stubs (this commit). 7.1 A + B + C + D + E (parallel; tests first, targeted test runs, one locked DB run per package). 7.2 F. 7.3 G acceptance and the owner's report. Each package: tests first, `ruff check .`, targeted tests only (owner's limit); the full suite is run by the main agent at merge; 5-line status per package.

## Pending items for the owner before go-live of AI
1. `.env` needs `DOCUMENT_STORE_DIR` (folder outside the repo). `OPENROUTER_API_KEY` and `LLM_MODEL` are now set by the owner (model `inclusionai/ling-3.2-flash:free`; free models may retain prompts, so masking and the per-client switch stay mandatory; the model name lives only in config; a later optional fallback model setting, e.g. `nvidia/nemotron-3.5-super-vl:free`, is not built). Everything else works without them (manual extraction, Tally, documents).
2. `pip install -e .` once for `pypdf`, `defusedxml`, `httpx`. OCR engine only if scanned documents must be read (see above).
3. Decisions to confirm at sign-off: rounding tolerance 1.00 between printed and recomputed values (warning up to it, error above); minimum confidence 0.85; Tally voucher types drafted (list in D-34); opening balances and bill-wise allocations of a Tally file are reported, not imported (D-33; allocations only where the voucher service accepts them).
4. The legal values this phase touches (GST rates, ITC blocks) are read from the existing rule tables by date; a missing rate is reported as pending (D-15), never invented. No new legal value is introduced.

## Suggestions (not built)
Import of Tally opening balances, godown / unit masters and stock journals; bank-statement-to-voucher bulk drafting from suggestions; email / WhatsApp intake; masking of phone numbers, e-mail and UPI IDs; GSTR-2B based duplicate-invoice and ITC cross-check of extracted purchase invoices; table detection (OCR boxes) feeding the schema directly; per-field accuracy statistics per supplier; PDF text-layer vs OCR comparison; Tally export of Phase 6 closing entries.
