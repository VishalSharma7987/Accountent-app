# Phase 8 API contract (Audit assistant) (extends docs/API_CONTRACT.md and the PHASE2-PHASE7 contracts; same conventions)

All paths are under `/clients/{client_id}` unless stated. Amounts are 2-decimal strings, dates `YYYY-MM-DD`, `X-User` on writes, `ServiceError` -> `{code, message, details}`. Findings carry `check_id` (A-01..A-18), `severity` (`error|review|warning|info`), `subject_kind`, `subject_id`, `subject_ref`, `finding_date`, `amount`, `disallowance_amount`, `message`, `evidence` (object: ids and figures as strings), `rule_status` inside `evidence.rule` when a legal limit was used.
New error codes: `unknown_check` (422), `no_period` (422, FY missing), `paper_signed_off` (409, any change to a signed-off paper / items / notes), `open_exceptions` (409, sign-off while an exception is open), `decision_reason_required` (422), `sample_invalid` (422), `form_finalised` (409), `ai_disabled` (409, `llm_disabled` of Phase 7 reused), `duplicate_holiday` (409).
**The audit never changes a voucher.** No endpoint of this phase writes to vouchers, lines, ledgers, bills, returns or documents.
**Convention (as Phase 7):** expected failures (AI switch off, provider error) come back as normal JSON bodies so the gateway row commits.

## Catalogue, runs, findings, report (package A) - `api/audit_checks.py`
- `GET /audit/checks` (not client scoped) -> `[{check_id, title, description, rule_text, severity, category, evidence_query, rule_key, active}]`; `GET /audit/rules` -> `[{rule_key, law, section_ref, amount, breach_when, disallow_percent, effective_from, effective_to, source_reference, verification_status, notes}]`.
- `POST /audit/runs` body `{financial_year_id, from_date?, to_date?, check_ids?: ["A-05", ...], params?: {duplicate_window_days?, doc_required_types?, doc_min_amount?, round_unit?, round_min_amount?, late_posting_days?, variance_min_amount?, variance_band_percent?}}` -> `201 {id, status:"completed", finding_count, summary:{by_check:{"A-05":{findings:int, population:int, notes:[...]}}, by_severity:{...}}}` | `422 unknown_check` | `422 no_period`. Defaults: the whole FY, every active check. A failing check does not stop the run: it is listed in `summary.by_check[...].error` and the run is still stored (status `completed`; `failed` only when nothing could be loaded).
- `GET /audit/runs` -> `[{id, financial_year_id, from_date, to_date, check_ids, finding_count, status, created_by, created_at}]`; `GET /audit/runs/{id}` adds `{params, rules_used:[{rule_key, law, verification_status, ...}], engine_version, summary}`.
- `GET /audit/runs/{id}/findings?check_id=&severity=&subject_id=` -> findings (see above).
- `GET /audit/runs/{id}/report` -> `{run, rules_pending:[...], checks:[{check_id, title, severity, population, findings:[...], notes}], totals}`; `GET /audit/runs/{id}/report?format=xlsx` -> workbook (one sheet per check with evidence columns; limit pending lines on the first sheet).

## Holidays (package B) - `api/audit_holidays.py`
- `GET /audit/holidays?year=` -> `[{id, holiday_date, name, kind, note}]`; `POST /audit/holidays` body `{holiday_date, name, kind?: "national"|"state"|"local"|"client", note?}` -> `201 {id}` | `409 duplicate_holiday`; `DELETE /audit/holidays/{id}` -> `{"ok":true}` (audit-logged). Sundays are never stored.

## Related parties (package D) - `api/audit_related.py`
- `GET /audit/related-parties` -> `[{id, ledger_id, ledger_name, relationship, active, flagged_by, flagged_at, note}]`; `POST /audit/related-parties` body `{ledger_id, relationship, note?}` -> `201 {id}` (`409` if already flagged: reactivate instead); `PUT /audit/related-parties/{id}` body `{relationship?, active?, note?}` (never deleted).

## Working papers (package E) - `api/audit_papers.py`
- `POST /audit/papers` body `{run_id, check_id}` -> `201 {id, status:"open", population_count, population_digest, items:int}` (items = the findings of that check in the run); `GET /audit/papers?run_id=&check_id=&status=` -> list (rows add `item_count`, `open_count`); `409 paper_exists` when the run + check already has a paper; `GET /audit/papers/{id}` -> `{..., population_amount, sample:{method, seed, params, ids}, conclusion, items:[{id, finding, status, reviewer_note, decided_by, decided_at}], notes:[...], signed_off_by, signed_off_at}`.
- `PUT /audit/papers/{id}/items/{item_id}` body `{status: "cleared"|"confirmed", reviewer_note}` -> `{"ok":true}` | `422 decision_reason_required` | `409 paper_signed_off`.
- `POST /audit/papers/{id}/notes` body `{note}` -> `201 {id}` | `409 paper_signed_off`.
- `POST /audit/papers/{id}/review` (open -> in_review) and `POST /audit/papers/{id}/reopen` (in_review -> open); `POST /audit/papers/{id}/sign-off` body `{conclusion}` -> `{"ok":true, signed_off_at}` | `409 open_exceptions` | `422` empty conclusion. Everything audit-logged with old and new values.

## Sampling (package E) - `api/audit_sampling.py`
- `POST /audit/papers/{id}/sample` body `{method: "random"|"systematic"|"value", size?: int, seed: int, threshold?: "amount" (value), rest_size?: int, start?: int (systematic, tests only)}` -> `{method, seed, params, ids:[...], population_count, population_digest}`; stores it on the paper (`409 paper_signed_off`, `422 sample_invalid`: size larger than the population, zero size, missing seed). `POST /audit/sampling/preview` body `{ids:[...], method, size?, seed, ..., amounts?: {id: amount} (value method)}` -> `{ids}` without storing (pure; used by tests and the UI). The same seed and population always give the same ids.

## Tax audit form data (package F) - `api/audit_tax.py`
- `GET /audit/forms?financial_year_id=` -> `{form_key, title, law, section_ref, verification_status, clauses:[{clause_no, title, derivability, data_source, verification_status}]}` (form chosen by FY end date: Form 3CD up to 2025-26, Form 26 from 2026-27).
- `POST /audit/forms/sets` body `{financial_year_id}` -> `201 {id, form_key, status:"draft"}`; `POST /audit/forms/sets/{id}/derive` body `{run_id, clause_nos?}` -> `{entries:[{clause_no, field_key, value, origin:"derived", run_id}]}` (only `books` / `partly_books` clauses; a clause whose source check is missing from the run is reported, not guessed); `PUT /audit/forms/sets/{id}/entries` body `{clause_no, field_key, value}` -> manual entry; `GET /audit/forms/sets/{id}`; `POST /audit/forms/sets/{id}/finalise` -> `{"ok":true}` | `409 form_finalised` on any later change. Export (`?format=xlsx`) marks every `pending` clause "not verified against the official form".

## AI summary (package F) - `api/audit_summary.py`
- `POST /audit/runs/{id}/summary` body `{paper_id?, check_id?}` -> `200 {status:"ok", id, summary_text, is_suggestion:true, llm_call_id}` | `200 {status:"blocked", reason:"llm_disabled"}` (client AI switch off: nothing sent, a blocked `llm_calls` row) | `200 {status:"error", message}`. The text is a suggestion; there is no endpoint that turns it into a conclusion. `GET /audit/runs/{id}/summaries` -> stored summaries.
