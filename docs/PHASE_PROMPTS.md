# LedgerMind AI — Phase-wise Implementation Prompts

## Kaise use karna hai (padh lo pehle)

1. Ek folder banao `ledgermind-ai`. Usmein `CLAUDE.md` root par rakho, aur ye file `docs/PHASE_PROMPTS.md` par.
   Requirements doc ko Markdown mein export karke `docs/REQUIREMENTS.md` par rakho.
2. Supabase mein ek hi project (`hdrkkbtcqzaoptgdimhr`) aur do schemas: `public` (dev data) aur `ledgermind_test` (sirf automated tests). Migration CLI test schema khud bana deta hai.
3. Claude Code us folder mein kholo (Supabase MCP connected ho).
4. Har session ki shuruaat mein **Session Start prompt** do, phir us step ka prompt copy-paste karo.
5. **Ek time par ek hi prompt.** Step ka result aur test output check karo, tabhi agla prompt do.
6. Phase ke end mein **Acceptance prompt** chalao. Accountant sign-off ke baad hi agla phase.
7. Prompts English mein hain kyunki code ke liye ye zyada exact rehta hai. Claude ke jawab Hinglish mein maangne ho to prompt ke end mein likh do "Reply in Hinglish".

Phase 1 ke prompts poore detail mein hain (1.1 se 1.10). Phase 2–9 ke prompts phase-level par hain; har phase
shuru karne se pehle unka **Phase Breakdown prompt** chalao, jo usse Phase 1 jaise chhote steps mein todega
aur tumhe approval ke liye dikhayega.

---

## Session Start prompt (har naye session mein sabse pehle)

```text
Read CLAUDE.md and docs/REQUIREMENTS.md fully. Then read docs/PHASE_PROMPTS.md up to the step I give you next.
Tell me in 5 lines: which phase/step we are on (check git log and the repo), what is already done,
what the test suite currently reports (run it), and anything that looks broken.
Do not write any code in this message.
```

---

# PHASE 0 — Project skeleton and test pack format

### Prompt 0.1 — Repository and tooling setup

```text
Phase 0, Step 0.1. Follow CLAUDE.md.

Create the repository skeleton exactly as in CLAUDE.md section 7 (empty folders get a .gitkeep).

Backend:
- backend/pyproject.toml for Python 3.12 with: fastapi, uvicorn, pydantic>=2, sqlalchemy>=2, psycopg[binary]>=3,
  python-dotenv, openpyxl, pandas; dev: pytest, pytest-cov, ruff, httpx.
- backend/app/main.py with a FastAPI app and GET /health returning {"status":"ok","db":"ok|error"}
  (db check = SELECT 1 using DATABASE_URL).
- backend/app/config.py reading .env (DATABASE_URL, TEST_DATABASE_URL).
- .env.example with placeholders only. .gitignore covering .env, .venv, node_modules, __pycache__.
- backend/tests/unit/test_smoke.py with one passing test.

Frontend:
- frontend/ with Vite + React + TypeScript + Tailwind. One page that calls /health and shows the result.

Docs:
- README.md with PowerShell commands: create venv, install, run backend, run tests, run frontend.

Do NOT create any accounting tables or code yet.
Finish with: files created, the exact PowerShell commands I should run, and the pytest summary line.
```

### Prompt 0.2 — Supabase connection and migration runner

```text
Phase 0, Step 0.2. Follow CLAUDE.md section 4.

1. (Done differently: one project, two schemas public + ledgermind_test — see CLAUDE.md section 4.) Using the Supabase MCP (read-only), confirm the project URL and schemas. Tell me which
   connection strings I must put in .env (do not print secrets; tell me where to copy them from in the dashboard).
2. Create database/migrations/0001_schema_migrations.sql that creates table schema_migrations
   (filename text primary key, applied_at timestamptz default now()) and enables RLS on it with no policies.
3. Create backend/app/db/migrate.py: a small CLI that applies every not-yet-applied file in database/migrations
   in name order, inside one transaction per file, and records it in schema_migrations.
   Usage: python -m app.db.migrate --target dev|test
   This lets the same SQL run on any PostgreSQL, not only Supabase.
4. Apply 0001 to both projects (MCP apply_migration or the CLI — say which you used) and verify with a read-only query.
5. Run Supabase MCP security advisors on both projects and report findings.

No accounting tables yet.
```

### Prompt 0.3 — Test pack format

```text
Phase 0, Step 0.3.

Design the human-readable test pack format that my accountant team will check and fill.
Create docs/test-packs/README.md explaining it, and a template folder docs/test-packs/_template/ with:
- client.yaml        (name, entity_type, business_type, fy_start, gst_type)
- ledgers.csv        (ledger_name, group_name, opening_dr, opening_cr)
- vouchers.csv       (ref_id, date, voucher_type, ledger_name, debit, credit, narration, reference_no)
                     one row per voucher line; rows with the same ref_id form one voucher
- invalid_vouchers.csv  (same columns + expected_rule_id + expected_message_contains)
- expected_ledger_balances.csv  (ledger_name, closing_dr, closing_cr)  as on the pack's end date
- expected_trial_balance.csv    (group_name, ledger_name, dr, cr) + a TOTAL row
- SIGNOFF.md         (who verified, date, notes)

Rules: amounts as plain numbers with 2 decimals, dates as YYYY-MM-DD, ledger names must match ledgers.csv.
Also create backend/tests/acceptance/pack_loader.py that reads a pack folder and validates its own format
(unknown ledgers, bad dates, unbalanced expected TB) with clear errors. Test the loader on the template.
Do not create the actual ABC Traders data yet.
```

---

# PHASE 1 — Accounting core

Goal: one client's vouchers → correct ledgers and a balanced Trial Balance; every invalid voucher rejected with
the right rule ID. No GST/TDS calculation in this phase (GST ledgers are ordinary ledgers; amounts typed by the user).

### Prompt 1.1 — Database schema for the accounting core

```text
Phase 1, Step 1.1. Follow CLAUDE.md sections 2, 4 and 5.

Write database/migrations/0003_accounting_core.sql (0002 is 0002_revoke_rls_auto_enable.sql) creating:

clients(id uuid pk, name, legal_name, entity_type check in ('proprietorship','partnership','llp','company'),
        business_type check in ('trading','service','manufacturing'), pan, state_code, gst_type
        check in ('regular','composition','unregistered'), books_begin_date date, is_active, created_at)
financial_years(id, client_id fk, start_date, end_date, unique(client_id,start_date), check end = start + 1 year - 1 day)
periods(id, financial_year_id fk, period_start, period_end, status check in ('open','locked'), locked_at, locked_by)
account_groups(id, code unique, name unique, parent_id fk null, nature check in ('asset','liability','income','expense'),
               report check in ('balance_sheet','trading','profit_loss'), is_system bool)
ledgers(id, client_id fk, group_id fk, name, is_active, created_at, unique(client_id, lower(name)))
opening_balances(id, ledger_id fk, financial_year_id fk, debit numeric(18,2) >=0, credit numeric(18,2) >=0,
                 check not (debit>0 and credit>0), unique(ledger_id, financial_year_id))
vouchers(id, client_id fk, financial_year_id fk, voucher_type check in
         ('contra','payment','receipt','sales','purchase','credit_note','debit_note','journal'),
         voucher_number text null, voucher_date, narration not null, reference_no null,
         party_ledger_id fk null, status check in ('draft','approved','posted','reversed'),
         reverses_voucher_id fk null, reversed_by_voucher_id fk null,
         duplicate_override_reason text null,
         created_by, created_at, approved_by, approved_at, posted_by, posted_at,
         unique(client_id, financial_year_id, voucher_type, voucher_number))
voucher_lines(id, voucher_id fk, line_no, ledger_id fk, debit numeric(18,2) >=0, credit numeric(18,2) >=0,
              check exactly one of debit/credit > 0)
voucher_number_sequences(client_id, financial_year_id, voucher_type, last_number, pk on the three)
audit_log(id bigserial, client_id, actor, action, entity, entity_id, old_data jsonb, new_data jsonb, created_at)

Database-level protection (defence in depth, the app also enforces these):
- Trigger: block UPDATE/DELETE on voucher_lines whose voucher status is 'posted' or 'reversed'.
- Trigger: on vouchers, block any change to a posted voucher except status 'posted'→'reversed' together with
  setting reversed_by_voucher_id.
- Trigger: block DELETE on audit_log and on posted/reversed vouchers.
- Deferred constraint trigger: when a voucher becomes 'posted', sum(debit) must equal sum(credit) for its lines.
- Enable RLS on every table with no policies.
- Indexes for: ledgers(client_id), vouchers(client_id, voucher_date), voucher_lines(voucher_id), voucher_lines(ledger_id).

Write database/seeds/0001_account_groups.sql seeding the groups exactly as in CLAUDE.md section 5 (is_system = true).

Apply both to the ledgermind_test schema first (migrate --target test), write integration tests in backend/tests/integration/test_schema_guards.py
proving each trigger blocks what it should, then apply to dev (migrate --target dev).
Report advisor output after applying.
```

### Prompt 1.2 — Pure engine: money, voucher validation

```text
Phase 1, Step 1.2. Follow CLAUDE.md sections 2, 5, 6. Pure Python only: backend/app/engine/ must not import
FastAPI, SQLAlchemy or anything AI.

Create:
- engine/money.py: parse_amount(value) -> Decimal. Accepts str/int/Decimal, rejects float, rejects
  negative, rejects >2 decimal places, rejects NaN/inf. One helper round_half_up(d, places=2) for later tax use.
- engine/models.py: frozen dataclasses: Group(code, name, nature, report), Ledger(id, name, group_code,
  is_active, client_id), VoucherLine(ledger_id, debit, credit), VoucherDraft(client_id, voucher_type, date,
  narration, reference_no, party_ledger_id, lines), ValidationError(rule_id, message, line_no|None).
- engine/validation.py: validate_voucher(draft, ledgers_by_id, groups_by_code, fy_ranges, period_status_for_date)
  -> list[ValidationError]. Return ALL errors, not just the first. Implement V-01..V-09, V-13 and V-14 from CLAUDE.md (messages in plain accountant language, Indian amount format, rule_id and line_no on every error).
  For V-08 resolve a ledger's group up the parent chain (a ledger under "Sundry Debtors" is in "Current Assets").
- engine/duplicates.py: find_possible_duplicate(draft, existing_vouchers) implementing V-10 matching rule.

Tests first (backend/tests/unit/engine/): at least one passing and one failing test per rule ID, plus:
- owner invests 1,00,000 cash (Cash Dr / Capital Cr) → valid
- rent 10,000 Dr vs cash 9,000 Cr → V-04
- a line with both Dr and Cr → V-02
- 10.005 → V-03
- Contra with a party ledger → V-08
- Journal touching Bank → V-08
- Payment with cash on both sides → V-08 (must be Contra)
- Sales voucher without a Sales Accounts line → V-08
- locked period → V-07; date outside FY → V-06; empty narration → V-09; inactive ledger → V-05
Run pytest and paste the summary.
```

### Prompt 1.3 — Pure engine: ledger and Trial Balance

```text
Phase 1, Step 1.3. Pure engine, no DB.

Create engine/reports.py:
- ledger_statement(ledger, opening, posted_lines_for_ledger, from_date, to_date) -> rows with
  date, voucher_number, voucher_type, narration, counter-ledger name(s) ("By"/"To" style, or "(as per details)"
  when several), debit, credit, running balance with Dr/Cr side; plus opening and closing rows.
- trial_balance(ledgers, groups, openings, posted_lines, as_on_date) -> list of rows
  (group path, ledger, debit, credit) using closing balances, grouped by primary group with group subtotals,
  and totals. If total Dr != total Cr, return the difference explicitly (never hide it).
- Balances are computed only from posted (and reversed) vouchers; drafts and approved vouchers never count.
  A reversed voucher and its reversal both count (they cancel out).

Tests with literal expected numbers. Use this mini case and compute expected values by hand in the test:
Opening: Cash 50,000 Dr; Bank 3,00,000 Dr; Stock-in-hand 1,00,000 Dr; Capital 4,50,000 Cr.
1) Rent paid in cash 20,000 (Payment: Rent Dr / Cash Cr)
2) Goods purchased on credit from Sharma Suppliers 50,000 (Purchase: Purchases Dr / Sharma Cr)
3) Goods sold on credit to Rahul Enterprises 80,000 (Sales: Rahul Dr / Sales Cr)
4) Received 30,000 from Rahul into bank (Receipt: Bank Dr / Rahul Cr)
5) Paid Sharma 15,000 from bank (Payment: Sharma Dr / Bank Cr)
6) Cash 10,000 deposited into bank (Contra: Bank Dr / Cash Cr)
7) Owner withdrew 5,000 cash (Payment: Drawings Dr / Cash Cr)
Expected closing: Cash 15,000 Dr; Bank 3,25,000 Dr; Stock-in-hand 1,00,000 Dr; Rahul 50,000 Dr;
Sharma 35,000 Cr; Capital 4,50,000 Cr; Drawings 5,000 Dr; Rent 20,000 Dr; Purchases 50,000 Dr; Sales 80,000 Cr.
TB totals: Dr 5,65,000 = Cr 5,65,000.
Also test: reversing voucher 1 leaves Cash at 35,000 Dr and Rent at 0.
Run pytest and paste the summary.
```

### Prompt 1.4 — Chart of Accounts templates and client setup service

```text
Phase 1, Step 1.4.

Create backend/app/engine/coa_templates.py returning the default ledgers for a client, by entity and business type:
- All: Cash (Cash-in-hand), Suspense A/c (Suspense A/c).
- proprietorship: "<Proprietor> Capital A/c", "Drawings A/c" (Capital Account). Year-end profit goes to Capital (Phase 6).
- partnership / llp: for each partner given at setup: "<Name> Capital A/c" and "<Name> Current A/c" (Capital Account).
- company: "Share Capital" (Capital Account), "Surplus in Profit & Loss" (Reserves & Surplus).
- trading: Purchases (Purchase Accounts), Sales (Sales Accounts), Purchase Returns (Purchase Accounts),
  Sales Returns (Sales Accounts), Opening Stock (Stock-in-hand).
- service: Service Income (Sales Accounts).
- manufacturing: same as trading for now plus "Raw Material Purchases" (Purchase Accounts) — full manufacturing is Phase 9.
- Common expense ledgers: Rent, Salary, Electricity, Telephone & Internet, Printing & Stationery, Travelling,
  Repairs & Maintenance, Bank Charges, Office Expenses (Indirect Expenses).
If anything in this list looks wrong for Indian practice, tell me before coding.

Then backend/app/services/client_setup.py (uses DB):
create_client(profile, partners=None, fy_start) → inserts client, the financial year, 12 monthly open periods,
template ledgers, audit_log rows — all in ONE transaction.
add_ledger, deactivate_ledger (blocked if it has a non-zero balance or draft vouchers), set_opening_balance
(only before any posted voucher in that FY; logged), opening_balance_difference(client, fy).
Integration tests against the ledgermind_test schema (guarded fixtures in tests/integration/conftest.py).
```

### Prompt 1.5 — Voucher lifecycle service

```text
Phase 1, Step 1.5.

backend/app/services/vouchers.py (uses DB + engine; engine does all rule checks):
- create_draft(draft) → runs validate_voucher; if errors, return them and save nothing.
  On success saves status 'draft'. Duplicate check (V-10) runs here: if a possible duplicate exists, return a
  V-10 error with the matching voucher unless draft.duplicate_override_reason is given.
- update_draft / delete_draft → only while status = 'draft'.
- approve(voucher_id, user) → re-validates; draft → approved.
- post(voucher_id, user) → re-validates (period may have been locked since), blocks if the client's opening balances
  differ (Dr ≠ Cr), assigns the next number from voucher_number_sequences using SELECT ... FOR UPDATE, format
  "<TYPE>/<YYYY-YY>/<NNNN>" with TYPE codes CON, PAY, REC, SAL, PUR, CRN, DBN, JRN; approved → posted.
- reverse(voucher_id, reversal_date, reason, user) → V-12: new voucher, same type, all lines Dr/Cr swapped,
  narration "Reversal of <number>: <reason>", goes through approve+post immediately, links both,
  original → reversed. reversal_date must be in an open period.
- Every state change writes audit_log with old/new data. Each operation is one DB transaction.

Integration tests: full lifecycle; posting assigns gapless numbers even when drafts are deleted; two concurrent posts
never get the same number; posted voucher cannot be edited (service and DB trigger both); reversal twice → error;
posting into a period locked after approval → V-07.
```

### Prompt 1.6 — Period lock and reports service

```text
Phase 1, Step 1.6.

- services/periods.py: lock_period, unlock_period (unlock requires a reason), both audit-logged.
  A period can be locked only if it has no draft/approved vouchers (list them if any).
- services/reports.py: ledger_statement(client, ledger, from, to) and trial_balance(client, as_on) that load data
  from DB and call the pure engine functions from Step 1.3. No accounting maths in this file.
- Integration test: load the Step 1.3 mini case through the services (create → approve → post) and assert the
  same literal expected TB.
```

### Prompt 1.7 — API

```text
Phase 1, Step 1.7.

FastAPI routers in backend/app/api/:
clients (create, list, get), ledgers (list with group & balance, create, deactivate, set opening),
groups (list tree), vouchers (create draft, update draft, delete draft, approve, post, reverse, get, list with filters:
date range, type, status, ledger), periods (list, lock, unlock), reports (ledger statement, trial balance),
audit log (list by entity).
- Request/response models in Pydantic; amounts travel as strings ("12500.00"), never as JSON floats.
- Validation failures return 422 with a list of {rule_id, message, line_no}.
- For now a fixed header X-User: <name> identifies the actor (no login in Phase 1; note this in README).
- API tests with httpx TestClient against the ledgermind_test schema.
```

### Prompt 1.8 — Excel import of vouchers

```text
Phase 1, Step 1.8.

backend/app/importers/voucher_excel.py + an API endpoint + a downloadable template (.xlsx) with the same columns as
docs/test-packs vouchers.csv.
- Rows with the same ref_id = one voucher. Ledger names matched case-insensitively to existing ledgers;
  an unknown ledger is an error (never auto-create).
- Import is two-step: (1) dry run → returns per-voucher result: OK or the list of rule errors with Excel row numbers;
  (2) commit → creates drafts only for the vouchers the user selects (default: all OK ones). Never posts.
- Amount cells: accept numbers or text; reject formulas that evaluate to more than 2 decimals.
Tests with small fixture files including bad rows.
```

### Prompt 1.9 — Web screens

```text
Phase 1, Step 1.9.

Frontend screens (simple, fast, table-first, keyboard friendly):
1. Clients: list + create (entity type, business type, partners if needed, FY start, opening balances grid
   showing the live Dr/Cr difference).
2. Ledgers: tree by group with closing balances; create/deactivate ledger.
3. Voucher entry: choose type; grid of lines (ledger search, Dr, Cr); live Dr/Cr totals and difference;
   narration; Save Draft shows rule errors next to the exact line. Buttons Approve / Post with confirmation.
4. Voucher list: filters; status badges; open a voucher; Reverse with reason and date.
5. Ledger statement: date range, Dr/Cr columns, running balance, export to Excel.
6. Trial Balance: as-on date, group/ledger toggle, totals, difference highlighted in red if not zero, export to Excel.
7. Periods: lock/unlock. 8. Excel import with dry-run result table.
Indian number format everywhere (1,00,000.00). No business rules in the frontend — it only shows what the API returns.
```

### Prompt 1.10 — ABC Traders test pack and Phase 1 acceptance

```text
Phase 1, Step 1.10.

1. Create docs/test-packs/abc-traders-apr-2026/ in the Phase 0 format:
   - Proprietorship trading business, FY 2026-27, GST regular (GST ledgers exist but GST is typed as plain amounts).
   - Opening balances + about 30 vouchers across all 8 types for April 2026 (capital, purchases, sales, returns,
     rent, salary, electricity, bank deposits/withdrawals, customer receipts, supplier payments, drawings,
     one journal for an outstanding expense, one reversal).
   - invalid_vouchers.csv with at least 10 cases covering V-01..V-10.
   - expected_ledger_balances.csv and expected_trial_balance.csv: compute these BY HAND in a working sheet
     docs/test-packs/abc-traders-apr-2026/WORKING.md showing every ledger's T-account step by step,
     NOT by running our engine.
   - A printable verification sheet (Excel) for my accountants: vouchers with Dr/Cr, ledger-wise workings, expected TB.
2. Write backend/tests/acceptance/test_pack_runner.py: loads any pack folder into the ledgermind_test schema through the
   services (create → approve → post), compares every ledger balance and TB line to the expected files, and checks
   each invalid voucher is rejected with the expected rule ID. Output a clear diff report.
3. Run it and report. If our engine disagrees with WORKING.md, do not "fix" the expected file — show me both
   so the accountant decides which is right.
```

### Prompt — Phase 1 acceptance check

```text
Run the full test suite and the acceptance runner on every pack in docs/test-packs (except _template).
Give me a Phase 1 completion report: each item from REQUIREMENTS.md Section 9 "Phase 1 done kab" as
Pass/Fail with evidence, list of known gaps, and anything pending for the accountants' SIGNOFF.md.
Do not start Phase 2.
```

---

## Phase Breakdown prompt (Phase 2 se har phase ke shuru mein)

```text
We are starting Phase <N>. Read CLAUDE.md, docs/REQUIREMENTS.md and the Phase <N> prompt in docs/PHASE_PROMPTS.md.
Break Phase <N> into numbered steps like Phase 1 (schema → pure engine → services → API → import → screens →
test pack → acceptance). For each step give: what it builds, rules it implements (with new rule IDs),
tests it needs, and which law-based values must be verified from official sources.
List every legal rate/threshold/section you plan to put in rule tables with the official source you will use.
Do not write code. Wait for my approval.
```

---

# PHASE 2 — Parties, bill-wise, cash and bank, Bank Reconciliation

```text
Phase 2 scope (run the Phase Breakdown prompt first):
- Party master on ledgers under Sundry Debtors/Creditors: GSTIN (format only for now), PAN, state, credit days,
  MSME status (micro/small/medium/none + Udyam no.).
- Bill-wise allocation on Sales/Purchase/Receipt/Payment/Credit/Debit note lines for party ledgers:
  New Ref, Against Ref, Advance, On Account (Tally semantics). Party ledger balance must equal sum of open bills.
- Outstanding reports: receivables/payables bill-wise with ageing buckets 0-30, 31-60, 61-90, 90+ days by due date.
- Cash Book and Bank Book reports (per cash/bank ledger, daily totals).
- Cash balance can never go negative on any date (rule; block posting that causes it).
- Bank statement import (Excel/CSV; column mapping saved per bank format), stored separately from books.
- Bank reconciliation: auto-match by amount + date window + reference/UTR/cheque no; one-to-many matches;
  manual match/unmatch; unmatched lists both sides; BRS report (balance as per books → cheques issued not presented →
  cheques deposited not cleared → bank-only items → balance as per bank) that must tie exactly, else show difference.
- Bank charges/interest found only in the bank statement → create DRAFT vouchers for the accountant (never post).
- Duplicate payment detection (same party + amount within N days).
- MSME payment-due flag: purchases from micro/small suppliers unpaid beyond the legal days (store days + legal reference
  in the rule table, verify the provision under Income-tax Act 2025 and MSMED Act).
Acceptance: an accountant-made bank statement + books pack where BRS ties to the rupee and ageing matches by hand.
```

# PHASE 3 — GST

```text
Phase 3 scope (run the Phase Breakdown prompt first; every rate/threshold goes into rule tables with source + effective dates):
- GST registrations per client (GSTIN, state, regular/composition, monthly/QRMP). GSTIN validation: format +
  check digit; state code ↔ state.
- Item/service master with HSN/SAC; tax rule table: HSN/SAC → rate by effective date (current slabs 0/5/18/40 from
  22 Sep 2025; older rates kept for older dates). Cess support only as a rule-table field.
- Tax engine (pure): place of supply → intra-state CGST+SGST (half each) or inter-state IGST; line-level
  calculation with ROUND_HALF_UP; invoice-level round-off ledger; RCM supplies (rule table of RCM categories);
  exempt / nil / non-GST supplies.
- Sales and Purchase vouchers in "invoice mode": items, qty, rate, discount, taxable value, tax lines auto-built by the
  engine into the voucher (Output/Input CGST, SGST, IGST ledgers under Duties & Taxes). User never types tax amounts.
- ITC eligibility status per purchase line: eligible / blocked (Section 17(5) categories in a rule table) /
  pending (not yet in GSTR-2B) / reversed. Conditions of Section 16 checked with evidence fields.
- 180-day rule: unpaid supplier invoices past 180 days → ITC reversal draft voucher + re-claim on payment.
- Import GSTR-2B (JSON/Excel from portal) and IMS status; reconcile with purchase register:
  matched / only in books / only in 2B / value mismatch / GSTIN mismatch / period mismatch.
- GSTR-1 working (B2B, B2C Large, B2C Small, CDNR, CDNUR, exports, nil/exempt, HSN summary, documents issued) and
  GSTR-3B working (3.1, 3.2, 4, 5, 6.1) from books; Books ↔ GSTR-1 ↔ GSTR-3B tie-out report.
- Composition clients: no tax collected on sales, quarterly turnover-based working, no ITC.
- Output: working sheets + portal-uploadable JSON/Excel where formats are official. Filing stays manual.
Acceptance: an accountant-prepared month with known GSTR-1/3B numbers and deliberately wrong invoices
(bad GSTIN, wrong IGST vs CGST, blocked credit claimed, invoice missing in 2B) all caught.
```

# PHASE 4 — TDS

```text
Phase 4 scope (run the Phase Breakdown prompt first):
- Law selection by date: the earlier of payment or credit decides the Act — on/before 31-03-2026 → Income-tax Act 1961
  sections (194C, 194J, 194I, 194H, 194Q, ...); on/after 01-04-2026 → Income-tax Act 2025 (Section 392 salary,
  Section 393 table entries for others, Section 394 TCS). Keep a mapping table old ↔ new with payment codes.
- Rule table: nature of payment → section/table entry, rate by deductee type (individual/HUF/others), single-payment
  and annual aggregate thresholds, effective dates, source reference. Verify every value from incometaxindia.gov.in /
  CBDT notifications; mark unverified as pending.
- Deductee master: PAN, PAN status, deductee type, lower-deduction certificate (number, rate, limit, validity).
- When posting Payment/Purchase/Journal to a TDS-applicable expense: engine computes TDS (threshold tracking per
  deductee per FY), builds TDS payable line under Duties & Taxes; higher rate when PAN missing (rule table).
- TDS register, challan entry and matching (deposit by due date; interest working for late deduction/deposit
  from rule table), quarterly return data in the current official return format (verify form names under the
  Income-tax Rules 2026), certificate data, reconciliation with 26AS/AIS import.
- TCS where applicable (Section 394) as rule-table entries.
Acceptance: accountant cases across both Acts incl. threshold crossing mid-year, missing PAN, lower-deduction certificate.
```

# PHASE 5 — Inventory (trading)

```text
Phase 5 scope (run the Phase Breakdown prompt first):
- Item master (SKU, name, unit, HSN, godown), opening stock qty + value.
- Stock movements created only from Sales/Purchase/Credit Note/Debit Note invoice lines and Stock Journals
  (transfer, damage/write-off with reason). No negative stock (block, configurable warning).
- Valuation per client policy: FIFO or Weighted Average (periodic and moving average options), computed by the pure
  engine; AS 2 rule: closing stock at lower of cost and NRV — NRV entered per item at period end, write-down shown.
- Closing stock valuation report and stock register (opening, inward, outward, closing qty & value per item).
- Accounting stays periodic: closing stock value flows into final accounts (Phase 6), not posted per sale.
Acceptance: accountant-computed FIFO and weighted average valuations for a multi-purchase, multi-sale month.
```

# PHASE 6 — Period-end and Final Accounts

```text
Phase 6 scope (run the Phase Breakdown prompt first):
- Adjustment helpers that create DRAFT journals: outstanding expenses, prepaid expenses, accrued income,
  income received in advance, provisions, bad debts and provision for doubtful debts, interest on capital/drawings
  (partnership as per deed), partners' remuneration.
- Fixed Asset Register: asset, block, purchase date, put-to-use date, cost, additions, disposals.
  Two depreciation books: (a) Companies Act Schedule II (SLM/WDV over useful life, residual value) for book
  accounts; (b) Income-tax block-wise WDV with the half-rate rule for assets used under 180 days — rates from rule
  table (verify under Income-tax Act 2025). Book depreciation posts a draft journal; tax depreciation is a working only.
- Closing stock from Phase 5. Trading A/c, P&L A/c, Balance Sheet:
  proprietorship/partnership vertical and horizontal formats; company: Schedule III (Division I for AS companies;
  Division II for Ind AS companies as a later option) with notes and previous-year comparatives.
- Cash Flow Statement (AS 3, indirect method) where required.
- Year-end close: transfer net profit to Capital (proprietor), partners' accounts per profit-sharing ratio
  (partnership), or Reserves & Surplus (company); carry forward balance-sheet ledgers and open bills; lock the year.
- Excel and PDF export of every statement with ledger drill-down references.
Acceptance: a full-year accountant-prepared client where every statement matches to the rupee.
```

# PHASE 7 — Document input and AI

```text
Phase 7 scope (run the Phase Breakdown prompt first):
- Tally import: masters (groups, ledgers, items) and vouchers from Tally XML export; mapping report; nothing posts
  automatically. Also export to Tally-importable XML.
- Documents table (file hash for duplicate detection, type, client, linked vouchers). Files in private storage,
  never public URLs.
- OCR (PaddleOCR/Tesseract) for PDFs/images; text PDFs read directly.
- LLM via OpenRouter (model in config) returns STRICT JSON validated by a Pydantic schema: supplier name, GSTIN,
  invoice no, date, line items, taxable values, tax amounts AS PRINTED, totals, each field with page/position
  source and confidence. The engine then recomputes tax and totals; any mismatch with printed values → flagged.
- Draft voucher builder: maps extracted data to ledgers using saved party/item mappings; unknown party/ledger → review,
  never auto-create.
- Bank narration → ledger suggestion: rule-based mappings learned from the accountant's past approvals first, LLM
  only as fallback, always as a suggestion with the reason shown.
- Approval queue screen: document image beside the draft, every field editable, accept/reject.
- Security: only synthetic/anonymised data to free models; PAN/Aadhaar/bank numbers masked before any LLM call.
Acceptance: a set of sample invoices and statements where extraction errors are caught by the engine or the review
queue and nothing wrong is ever posted.
```

# PHASE 8 — Audit assistant

```text
Phase 8 scope (run the Phase Breakdown prompt first):
- Audit checks engine (each check = ID, description, rule, severity, evidence query):
  duplicate bills/payments, missing supporting documents, voucher number gaps, cash payment above the daily
  limit per party (disallowance flag), cash receipts above the legal limit, MSME dues past the legal days,
  GST books vs returns mismatches, TDS not deducted/short deducted/late deposited, round-amount entries,
  entries on Sundays/holidays, expenses booked after period lock dates, unusual ledger movements vs previous
  year (ratio and variance analysis), negative cash/stock history, related-party transactions (flagged parties).
  Limits and sections in rule tables with sources (verify under Income-tax Act 2025).
- Audit working papers: per check — population, sample, exceptions, evidence links, reviewer notes, status.
- Sampling helpers (random/systematic/value-based) with recorded seeds for reproducibility.
- Tax audit (Form 3CD) data-point schedules derived from books (verify the current form under the new Act).
- LLM may summarise exceptions in plain language; it never decides an audit conclusion.
Acceptance: a pack with injected errors — every one appears in the audit report with evidence.
```

# PHASE 9 — Payroll, loans, manufacturing

```text
Phase 9 scope (run the Phase Breakdown prompt first; split into 9A payroll, 9B loans, 9C manufacturing):
- 9A Payroll: employees, salary structure, attendance/LOP, PF/ESI/Professional Tax (rates and wage ceilings in rule
  tables per state, verified), salary TDS under Section 392 (regime choice, declarations), payroll journal draft,
  payslips, salary register, statutory challans data.
- 9B Loans: loan master, EMI schedule (reducing balance), interest vs principal split per EMI, accrued interest at
  period end, outstanding confirmation report.
- 9C Manufacturing: raw material / WIP / finished goods godowns, BOM, production (manufacturing) journal consuming
  materials at valuation cost, labour and overhead absorption, by-product/scrap, WIP and finished goods valuation
  for final accounts (Manufacturing A/c section).
Acceptance per sub-phase with accountant-computed cases.
```
