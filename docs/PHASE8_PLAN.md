# Phase 8 plan - Audit assistant (audit checks, working papers, sampling, Form 3CD / Form 26 data, AI summary)

Written 2026-11-20 (planning agent, branch `p8-plan`) under the working mode of CLAUDE.md section 6. Scope: `docs/PHASE_PROMPTS.md` Phase 8. Interfaces: `docs/PHASE8_API_CONTRACT.md`. Legal values: `docs/PHASE8_LEGAL_VALUES.md`. Decisions: `docs/decisions_parts/P8.md`.
Schema (migration **0019**, seeds **0014**, **0015**) is written FIRST and is the shared contract: **agents never edit it**; a needed change goes to the main agent. Step 8.0 (this commit) wrote the migration, the seeds, the pure types and check catalogue (`engine/audit_types.py`), hooks (`services/audit_hooks.py`), stub check modules, seven empty routers and tests; it applied 0019 and the seeds to the TEST schema only and ran the schema test once.

## Principles specific to this phase
1. **Read-only on the books.** The audit service reads vouchers, ledgers, bills, returns, documents and never inserts, updates or deletes a books table (`audit_hooks.READ_ONLY_TABLES`; a unit test in package G scans every `audit_*` service for SQL writes to them). Fixing a finding is done by the accountant through the normal voucher actions (reversal etc.); the audit only reports.
2. **Python finds, a person concludes.** Every finding is a deterministic rule over plain facts. The LLM may only SUMMARISE exceptions in plain language (a suggestion stored as `audit_ai_summaries`, `is_suggestion` forced true); it never classifies a finding, never clears or confirms one, never writes a conclusion. `conclusion` on a paper is the reviewer's own text.
3. **No guessing.** If no legal limit row covers a date, the check does not invent one: it skips that date and says so in `CheckResult.notes` (and the report shows "limit not available for dd-mm-yyyy"). A limit whose status is `pending` is still applied (the accountant needs the flag) but every finding carries `rule_status`, and the report prints "limit pending verification".
4. **Law is data.** Cash limits, the disallowance percentage and the comparison word (`above` for s.40A(3), `at_or_above` for s.269ST) are rows in `audit_rule_limits` with effective dates, source and status; MSME days, GST and TDS rules are read from their existing rule tables by the reused engines. Judgement parameters (round unit, windows, variance band) are NOT law: they are `AuditParams`, stored on the run.
5. **Evidence or nothing.** A finding without evidence is refused by the database (`audit_findings_evidence_present`): voucher ids, ledger id, document ids and the figures used.
6. **Immutable once signed.** Runs, findings, AI summaries and notes are insert-only; a working paper that is signed off, its items and its notes cannot change; a finalised Form set cannot change. Re-auditing means a new run and a new paper.
7. **Every action is audit-logged** (`audit_hooks.log_action`: run, paper create / review / sign-off, item decision, note, holiday, related-party flag, form entry / finalise, AI summary) with old and new values.
8. **Reproducible sampling.** The seed is stored; the population digest (SHA-256 of sorted ids) is stored; the same seed and population give the same sample on any machine (own SplitMix64 generator, not the `random` module).

## Data flow
```
accountant: financial year (+ params) -> POST run (A)
  loaders (read only SELECTs, per package) -> plain facts (VoucherFact, LedgerFact, ...) -> pure checks (B, C, D) -> CheckResult (findings, population)
  -> audit_runs + audit_findings (insert only, evidence) -> report (A: per check population, exceptions, evidence, rule status)
working paper per run + check (E): population count + digest, sample (random / systematic / value, seed), exception items (open -> cleared | confirmed with a reason),
  notes, status open -> in_review -> signed_off (immutable)
AI summary (F, optional, client AI switch): masked exception list -> gateway (audit_summary) -> text stored as a suggestion
Tax audit data (F): run + books -> derived Form 3CD (FY <= 2025-26) / Form 26 (FY >= 2026-27) entries, others typed by hand; finalise (immutable)
```

## Database (migration 0019; 14 tables)
| Table | Role | Key guards |
| --- | --- | --- |
| `audit_rule_limits` | system rule table: cash payment daily limit (and transport limit), cash receipt limit; amount, `breach_when`, `disallow_percent`, `effective_from/to`, `source_reference`, `verification_status` | amount 2 decimals; unique (key, law, from); period check |
| `audit_checks` | system catalogue of A-01..A-18: title, description, rule text, severity, category, evidence query name, rule key | id format `A-nn` |
| `audit_form_defs`, `audit_form_clauses` | Form 3CD (to 31-03-2026) and Form 26 (from 01-04-2026) and the clauses that can be derived from books (`books` / `partly_books` / `manual`) | statuses; Form 26 clauses added by package F after reading the official form |
| `audit_holidays` | per client holiday calendar (Sundays are computed, not stored) | unique (client, date) |
| `audit_related_parties` | ledgers the accountant flags as related (relationship text) | composite FK to the client's ledger; never deleted (deactivate) |
| `audit_runs` | one execution: client, FY, period, check ids, params, rules used (with statuses), engine version, status, summary | insert only; failed needs a reason |
| `audit_findings` | the exceptions: check, deterministic `finding_key`, severity, subject (voucher / ledger / party / document / return / period / stock_item / bill), amount, `disallowance_amount`, message, `evidence` jsonb | insert only; evidence mandatory; unique (run, key); money 2 decimals |
| `audit_working_papers` | one per run + check: population count / digest / amount, sample method + seed + params + ids, reviewer `conclusion`, status | sample needs seed; sign-off needs who / when / conclusion and no open exception; signed_off immutable; never deleted |
| `audit_paper_items` | the exceptions of a paper: status open / cleared / confirmed, reviewer note, decided by / at | decision needs who, when, why; finding must belong to the paper's run and check; frozen when signed off; never deleted |
| `audit_paper_notes` | reviewer notes | insert only; refused after sign-off |
| `audit_ai_summaries` | AI plain-language summary of a run or paper, linked to the `llm_calls` row | insert only; `is_suggestion` must be true |
| `audit_form_sets`, `audit_form_entries` | tax audit form data per client + FY + form; entries `derived` (names the run) or `manual` | finalised set and its entries immutable |
| `llm_calls` (changed) | `audit_summary` added to the allowed purposes | - |
Every table: RLS enabled, no policies; function privileges revoked at the end (0004 pattern); functions pin `search_path`; schema-agnostic. No foreign key or trigger lets an audit table change a voucher.

## Check catalogue (IDs, severity, rule, evidence; text lives in seed 0014)
Severity: `error` = a breach the books show, must be answered; `review` = needs judgement; `warning` = probable problem; `info` = listed for the file. Parameters are in `AuditParams`, limits in `audit_rule_limits`.
| ID | Check | Sev | Rule (short) | Evidence | Reuse |
| --- | --- | --- | --- | --- | --- |
| A-01 | Duplicate bills | warning | same party + normalised reference no on more than one live voucher (reversed pairs ignored) | voucher ids, reference, amounts | `engine/duplicates` key |
| A-02 | Duplicate payments | warning | same party + same total within N days (default 7) on live Payment vouchers | voucher ids, dates, amount | - |
| A-03 | Missing supporting document | warning | Purchase / Payment / Debit Note (parameter) without a `document_vouchers` link | voucher id, type, amount | Phase 7 documents |
| A-04 | Voucher number gap | error | posted numbers per client + FY + type are not 1..N, or counter differs | type, missing numbers | - |
| A-05 | Cash payment above the daily limit | error | per person per day, sum of cash payments above limit of that date: disallowance = day total x percent | voucher ids, party, date, day total, limit, rule status | rule table |
| A-06 | Cash receipt above the legal limit | error | per person per day (and per voucher) cash receipts at or above limit of that date | voucher ids, party, date, total, limit | rule table |
| A-07 | MSME dues past the legal days | error | open bill of micro / small party older than the rule's days (agreement flag) | bill / voucher, due date, days late | `engine/msme` |
| A-08 | GST books versus returns | error | any tie-out difference of a period with its cause | period, form, books vs filed | `engine/gst_tieout` |
| A-09 | TDS not deducted | error | computed tax > 0, no deduction item | voucher, section, computed | `engine/tds_calc` |
| A-10 | TDS short deducted | error | deducted < computed (lower-deduction certificate honoured) | voucher, deducted, computed | `engine/tds_calc` |
| A-11 | TDS late deposited | error | challan after due date of the deduction month, or none | item, due date, challan date | `engine/tds_challan` |
| A-12 | Round-amount entries | info | voucher total multiple of the round unit (default 1,000.00) and not below the minimum (default 10,000.00) | voucher id, total | - |
| A-13 | Entries on Sundays / holidays | info | `voucher_date` is a Sunday or in `audit_holidays` | voucher id, date, holiday name | - |
| A-14 | Entries after the period was locked | warning | posted after a lock of its period (from `audit_log` lock / unlock) or more than N days after period end (default 30) | voucher id, dates, audit_log id | - |
| A-15 | Unusual ledger movement | review | ledger year total vs previous year: change >= minimum amount and ratio outside the band (default +/-50%) | ledger id, both totals, change, percent | - |
| A-16 | Negative cash history | error | any day-end cash balance < 0 | ledger, date, balance | `engine/cash_rules` |
| A-17 | Negative stock history | error | item / godown running quantity < 0 on a date | item, date, quantity | Phase 5 valuation |
| A-18 | Related-party transactions | info | postings on active flagged ledgers in the period | voucher ids, party, totals | - |

## Worked examples (hand-calculated; tests copy these literally)
* **A-05.** Limit row (10,000.00, `above`, 100%) pending. Party Sharma Traders, 14-08-2026: cash Payment vouchers of 6,000.00 and 5,000.00 -> day total 11,000.00 > 10,000.00 -> one finding (`A-05:<party>:2026-08-14`), disallowance 11,000.00 x 100% = 11,000.00, message "Cash payments to Sharma Traders on 14-08-2026 total 11,000.00, above the daily limit of 10,000.00 (limit pending verification); expenditure of 11,000.00 may be disallowed". Same party on 15-08-2026: 10,000.00 -> not flagged (not above). A bank payment of 20,000.00 the same day is ignored (only Cash-in-hand lines count).
* **A-06.** Limit 2,00,000.00 `at_or_above`. Mehta & Co, 03-09-2026: cash receipts 1,50,000.00 + 50,000.00 = 2,00,000.00 -> finding. 1,99,999.99 -> none.
* **A-04.** Purchase vouchers posted PUR/2026-27/0001, 0002, 0004 -> missing 0003; counter says 4 -> finding "number 0003 missing".
* **A-01.** Two live purchase vouchers, party Kumar Steel, reference "INV-17" and "inv 17 " (normalised equal) -> one finding listing both ids. If the first is reversed, none.
* **A-12.** Totals 50,000.00 (flag), 50,000.50 (no), 9,000.00 (below minimum, no).
* **A-13.** 22-11-2026 is a Sunday -> finding; 20-10-2026 listed in `audit_holidays` -> finding with the holiday name.
* **A-15.** Sales ledger 12,00,000.00 this year, 7,00,000.00 last year: change 5,00,000.00 >= minimum 1,00,000.00; ratio 500000 / 700000 = 71.43% > 50% -> finding. 8,00,000.00 vs 7,00,000.00 -> 14.29%, no finding.
* **Sampling (package E).** Population ids sorted `v01..v10`, systematic n = 3: interval floor(10 / 3) = 3; with start offset 1 (explicit in the test) -> indexes 1, 4, 7 -> `v02, v05, v08`. Value sample: threshold 50,000.00 on amounts 80,000 / 49,999.99 / 50,000.00 / 10,000 -> key items are the 80,000 and 50,000.00 ones (at or above).

## Working paper rules (IDs for messages and tests)
| ID | Rule |
| --- | --- |
| W-01 | One paper per run + check; its population count and digest come from the run's `CheckResult.population`; the paper never changes the findings |
| W-02 | A sample records method, seed, parameters and the chosen ids; the same seed and population give the same ids (SplitMix64, population sorted by string id) |
| W-03 | Exceptions are the run's findings of that check; each is open until the reviewer clears or confirms it with a reason (who, when, why) |
| W-04 | A paper moves open -> in_review -> signed_off; back from in_review to open is allowed; signed_off is terminal |
| W-05 | Sign-off needs every exception decided and a conclusion written by the reviewer; after sign-off nothing on the paper, its items or notes changes |
| W-06 | Notes are insert only; refused after sign-off |
| W-07 | Every action is written to `audit_log` with old and new values |
| W-08 | An AI summary is stored as a suggestion; it is never copied into the conclusion automatically |

## Tax audit data (Form 3CD / Form 26) - package F
Form 3CD applies to FY 2025-26 and earlier; **Form 26** (Income-tax Act 2025 section 63, Rules 2026 rule 47) replaces Forms 3CA / 3CB / 3CD from tax year 2026-27 (secondary sources and the CBDT FAQ title found; the form itself NOT read: see legal values). The engine chooses the form by the FY end date. Only clauses derivable from books are derived (seed 0015 lists them: 18 depreciation, 21 inadmissible amounts incl. cash payments, 22 MSME interest, 23 related parties, 26 s.43B, 27 GST, 31 cash loans / receipts, 34 TDS, 35 quantities, 40 ratios, 44 GST break-up of expenditure); each derived entry names its run and reads the same engines as the checks (A-05, A-07, A-18 ...). All other clauses are typed by the accountant (`origin = manual`). Package F first reads the official Form 26 (incometaxindia.gov.in `fn-26` / `form-26-faqs`), adds its clauses to `audit_form_clauses` through a seed file proposed to the main agent (still `pending` until the owner confirms), and marks everything it cannot verify.

## Sampling (package E) - interface
`engine/audit_sampling.py`, pure: `SplitMix64(seed)`; `random_sample(ids, n, seed) -> list` (population sorted by string id, partial Fisher-Yates with the generator, result in population order); `systematic_sample(ids, n, seed, start=None)` (interval `N // n`, start = first draw mod interval unless `start` is given); `value_sample(items, threshold, n_rest, seed)` (every item with amount >= threshold, plus `n_rest` random from the rest; amounts Decimal). Each returns the chosen ids; the service stores method, seed, params and ids on the paper. SplitMix64 test vector (to be verified by hand-calculation in the package): seed 0, first output 0xE220A8397B1DCDAF.

## Layers and file ownership (parallel agents never collide)
Engine files import only `engine/audit_types.py`, `engine/money.py` and earlier pure engines. Services take a SQLAlchemy `Connection`, never commit, never write to a books table, audit-log through `audit_hooks.log_action`. After 8.0 nobody edits `main.py`, `database/**`, `engine/audit_types.py` signatures (add optional fields at the end via the main agent), `services/audit_hooks.py`, `config.py`, `api/errors.py`. `services/vouchers.py` is NOT touched in this phase. Decision rows go to `docs/decisions_parts/<pkg>8.md`, status to `docs/progress_parts/<pkg>8.md`; tests in new files named for the area. Database runs through `scripts/dbrun.sh`.
| Pkg | Creates / edits | Never touches | Depends on |
| --- | --- | --- | --- |
| A framework, runs, report | `engine/audit_registry.py` (aggregates the three `CHECKS` dicts, builds the `CheckResult` list, summary), `services/audit_runs.py` (create run: load rules, call loaders of B / C / D, persist run + findings, audit-log; list / get), `services/audit_load_common.py` (shared read-only loaders: vouchers + lines + ledgers + groups -> facts, limit rules), `services/audit_report.py` (JSON report, Excel via openpyxl, rule status lines), `db/repositories_audit.py`, `api/audit_checks.py`, `api/schemas_audit_checks.py` | check logic | stubs of B / C / D (`CHECKS = {}`) |
| B books checks | `engine/audit_checks_books.py` (A-01..A-06, A-12, A-13, A-14), `services/audit_load_books.py` (document links, number sequences, audit_log lock events, holidays), `services/audit_holidays.py`, `api/audit_holidays.py`, `api/schemas_audit_holidays.py` | MSME / GST / TDS engines | `engine/audit_types.py`, `engine/duplicates.py` |
| C compliance checks | `engine/audit_checks_compliance.py` (A-07..A-11, A-16, A-17; thin adapters that call the Phase 2 to 5 engines and turn their results into findings), `services/audit_load_compliance.py` (bills, MSME rules, GST tie-out inputs, TDS items / challans, cash and stock movements) | books checks | existing engines (read only) |
| D analytical + related party | `engine/audit_checks_analytic.py` (A-15, A-18), `services/audit_load_analytic.py` (ledger totals this and previous year, flagged ledgers), `services/audit_related.py`, `api/audit_related.py`, `api/schemas_audit_related.py` | other checks | `engine/audit_types.py` |
| E working papers + sampling | `engine/audit_sampling.py`, `engine/audit_papers.py` (W-rules, transitions, digest use), `services/audit_papers.py` (create from run + check, sample, items, decide, notes, review, sign-off; audit-log), `db/repositories_audit_papers.py`, `api/audit_papers.py`, `api/audit_sampling.py`, `api/schemas_audit_papers.py` | checks, runs | tables only (reads findings); no code dependency |
| F tax audit data + AI summary | `engine/audit_form.py` (form selection by FY end, derivation of clauses from findings / book totals), `services/audit_form.py`, `services/audit_summary.py` (masked prompt built from findings text, gateway purpose `audit_summary`, stores `audit_ai_summaries`; returns a result object when the AI switch is off), `ai/prompts_audit.py` (fixed text, summarise only, no conclusions), `api/audit_tax.py`, `api/audit_summary.py`, schemas; proposes seed `0016` for Form 26 clauses to the main agent | checks, gateway internals | gateway signature (`services/llm_gateway.py`, injected / fake in tests); run + findings tables |
| G acceptance pack | `docs/test-packs/phase8-*/**` (synthetic books built by script with injected errors, one per check), `backend/tests/acceptance/pack_loader_p8.py`, `pack_runner_p8.py` (headline property: every injected error appears in the report with its evidence; no books table changed by the audit), `scripts/build_verification_sheet_p8.py`, `docs/PHASE8_SIGNOFF.md` | engines, services | A..F merged |
| UI (separate, later) | `frontend/src/screens/` audit run list, findings with evidence links, working paper with sampling and sign-off, holiday / related-party masters, tax audit form data | backend | contract; A..F final shapes |

**Parallel split.** Wave 1 (no code dependency between them, each tested with literal facts / plain tables): **A, B, C, D, E, F** (six agents; A integrates the others only through the `CHECKS` registries, so the order of merge does not matter). Wave 2: **G** acceptance, then the UI package. Shared-file conflicts: none by construction (`main.py`, migrations, seeds, types, hooks are closed; each package owns its files above). Integration runs (database) go through `scripts/dbrun.sh`, own test files only, one locked run per package.

## Acceptance (package G)
A synthetic client with injected errors, one set per check: two cash payments to one party summing above the limit (A-05), 2,00,000 of cash receipts (A-06), a voucher-number gap created by direct SQL in the test schema (A-04; the voucher service cannot create one), duplicate bill numbers (A-01) and duplicate payments (A-02), a posted purchase without a document (A-03), an MSME bill 60 days old (A-07), a GST tie-out difference (A-08), TDS missing / short / late (A-09..A-11), round totals (A-12), a Sunday voucher (A-13), a voucher posted after a period lock (A-14), a ledger that doubled (A-15), a cash overdraft day and a negative stock date (A-16 / A-17), a flagged related party (A-18). Headline property: **every injected error appears in the audit report with its evidence, nothing else is reported as an error, the books are unchanged after the run (row counts and a hash of vouchers and lines), the same seed gives the same sample, a signed-off paper rejects every change, and an AI summary run with the fake client is stored as a suggestion while a disabled switch makes no call.**

## Steps
8.0 plan + schema + catalogue + hooks + stubs (this commit). 8.1 A..F (parallel; tests first, targeted test runs, one locked DB run per package). 8.2 G acceptance and the owner's report. Each package: tests first, `ruff check .`, targeted tests only (owner's limit); the full suite is run by the main agent at merge; 5-line status per package.

## Pending items for the owner (details in `docs/PHASE8_LEGAL_VALUES.md`)
1. Confirm the cash payment limit (s.40A(3) successor in the 2025 Act: section number NOT found), the transport limit, the 100% disallowance and the receipt limit against the official text; until then the checks run and every finding says "limit pending verification".
2. Confirm Form 26 clause numbering and the clause list that can be derived (Form 3CD clause numbers are recalled, all `pending`).
3. Judgement parameters to confirm at sign-off: duplicate window 7 days, round unit 1,000 / minimum 10,000, late posting 30 days, variance band 50% and minimum 1,00,000.
4. Holiday calendars: no national / state holiday list is seeded (not invented); the accountant enters each client's holidays.

## Suggestions (not built)
Cash loans and deposits over 20,000 (s.269SS / 269T successors 185 / 188), related-party fair-value checks, Benford-style digit analysis, bank-statement vs cash-book unusual round deposits, GSTR-2B ITC mismatch as an audit check, scheduled periodic runs, audit-trail export of the whole `audit_log`, management-letter generator.
