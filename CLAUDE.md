# LedgerMind AI — Project Rules for Claude

Read this file fully at the start of every session. These rules override any default habit.
The approved requirements live in `docs/REQUIREMENTS.md` (exported from the requirements doc).
If anything here conflicts with a prompt, STOP and ask the owner.

## 1. What we are building

An accountant's calculator for Indian CA-office work. An accountant gives client data
(vouchers, bills, bank statements); the tool applies accounting rules and produces
ledgers, Trial Balance, final accounts, GST and TDS workings, and audit checks.
Every number must come from a deterministic rule, never from a guess.

User: a CA-office accountant handling many clients of every type
(trading, service, manufacturing; proprietor, partnership, LLP, company).
Jurisdiction: India only. Currency: INR. Financial year: 1 April – 31 March.

## 2. Non-negotiable principles

1. **AI understands, Python calculates.** No LLM ever computes an amount, a tax, or a balance,
   and no LLM output is ever posted directly. AI output is only a *draft* that passes the rule engine
   and an accountant's approval.
2. **Draft → Approved → Posted → (Reversed).** Posted vouchers are immutable. Corrections happen
   only through a linked reversal voucher. Never UPDATE or DELETE a posted voucher or its lines.
3. **No guessing.** Missing or ambiguous data → reject with a clear reason or send to review. Never fill
   a default silently.
4. **Exact money.** Python `decimal.Decimal` only (never float). DB type `NUMERIC(18,2)`.
   Amounts with more than 2 decimal places are rejected, not rounded. Where rounding is legally
   required (tax), use `ROUND_HALF_UP` in one shared helper and test it.
5. **Law is data, not code.** Tax rates, thresholds, section numbers, limits live in rule tables with
   `effective_from`, `effective_to`, `source_reference`, `verification_status`. Pick the rule by
   transaction date. Never hardcode a rate in business logic. Mark any rule you could not verify from
   an official source as `verification_status = 'pending'` and tell the owner.
6. **Engine independent of AI and of the web.** The accounting engine (`backend/app/engine/`) is pure
   Python: no FastAPI, no DB, no LLM imports. It takes plain data and returns results/errors.
7. **Every change is logged.** Create, approve, post, reverse, lock, unlock → `audit_log` row with
   who, when, what, old value, new value.
8. **Build only what accounting needs.** No features outside the current phase. No speculative
   abstractions. If something seems useful but is not in the phase prompt, list it as a suggestion
   at the end — do not build it.

## 3. Tech stack (fixed — do not swap without asking)

| Layer | Choice |
| --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (Core), psycopg 3 |
| Database | PostgreSQL hosted on Supabase (free plan for dev/test) |
| Migrations | Plain SQL files in `database/migrations/NNNN_name.sql`, applied in order |
| Tests | pytest; engine tests need no DB |
| Frontend | React + Vite + TypeScript + Tailwind; simple, dense, table-first screens |
| Imports | openpyxl / pandas (only for reading files; never for ledger maths) |
| AI (Phase 7+) | LLM via OpenRouter, model name in config; OCR via PaddleOCR or Tesseract |

Not used unless the owner asks: LangGraph or any agent framework, Supabase Auth,
Supabase Edge Functions, Supabase client SDK in the frontend.

## 4. Supabase rules

- Treat Supabase as **plain PostgreSQL**. No Supabase-only feature in accounting logic,
  so the DB can move to any Postgres by changing `DATABASE_URL`.
- **One project, two schemas** (project `hdrkkbtcqzaoptgdimhr`, called ledgermind-dev):
  schema `public` = dev data; schema `ledgermind_test` = automated tests only (wiped freely).
  `DATABASE_URL` and `TEST_DATABASE_URL` are the same session-pooler string; the code selects the schema
  (`SET search_path`), see `backend/app/db/connection.py`.
- **Schema guard:** test fixtures and `migrate --target test` refuse to run unless
  `current_schema() = 'ledgermind_test'`. Test cleanup is `TRUNCATE` of tables inside `ledgermind_test`
  only (never the migrations table); never `DROP` or `TRUNCATE` anything outside it.
- **SQL files are schema-agnostic:** no `public.` or `ledgermind_test.` and no `CREATE SCHEMA` /
  `SET search_path` in `database/migrations/` or `database/seeds/`. The connection's search_path decides
  where objects go; each schema has its own `schema_migrations` table. A unit test enforces this.
- Schema changes: write the SQL file in `database/migrations/` first (the file in git is the source of
  truth), then apply it with the migration CLI from `backend/`:
  `python -m app.db.migrate --target test` first, run the tests, then `--target dev`.
  The CLI creates `ledgermind_test` if missing, then applies `database/seeds/*.sql` (idempotent, recorded as
  `seeds/<file>` in `schema_migrations`). Seeds hold system data only (the account groups). The Supabase MCP in
  `.mcp.json` is **read-only**
  (`read_only=true`) and is not used to apply migrations.
- Use the Supabase MCP for: listing tables, running **read-only** checks, and reading advisors
  (security/performance). Do not hand-edit data through MCP.
- **Security:** Supabase exposes the tables of its API schemas through its public API. Every table gets
  `ALTER TABLE ... ENABLE ROW LEVEL SECURITY;` with **no** policies for `anon`/`authenticated`
  (deny all). `ledgermind_test` is closed to the API roles (`REVOKE ALL ON SCHEMA` from `PUBLIC`, `anon`,
  `authenticated`) and must **never** be added to the Supabase API "exposed schemas". Only the FastAPI
  backend connects, using the Postgres connection string from `.env`. Never put a Supabase key or DB
  password in frontend code or in git.
- **Database guards (migration 0003):** the database itself rejects what the app must never do: posted/reversed
  vouchers cannot be edited or deleted; `voucher_lines` change only while the voucher is `draft`; `audit_log` is
  append-only; a client's vouchers can only use that client's ledgers (composite foreign keys). Do not weaken
  these triggers to make a test or an import pass; fix the caller.
- **Go-live cleanup** (before real client data; also move to a Pro project with backups):
  `DROP SCHEMA ledgermind_test CASCADE;`
- Free projects pause after 7 days idle — if the DB is unreachable, ask the owner to resume it.
- Only synthetic or anonymised data in Supabase Free (no backups on free plan).

## 5. Accounting model (Indian / Tally-style)

### Account groups (seeded, fixed nature)

| Group | Parent | Nature | Report |
| --- | --- | --- | --- |
| Capital Account | — | Liability (equity) | Balance Sheet |
| Reserves & Surplus | Capital Account | Liability (equity) | Balance Sheet |
| Loans (Liability) | — | Liability | Balance Sheet |
| Current Liabilities | — | Liability | Balance Sheet |
| Sundry Creditors | Current Liabilities | Liability | Balance Sheet |
| Duties & Taxes | Current Liabilities | Liability | Balance Sheet |
| Provisions | Current Liabilities | Liability | Balance Sheet |
| Fixed Assets | — | Asset | Balance Sheet |
| Investments | — | Asset | Balance Sheet |
| Current Assets | — | Asset | Balance Sheet |
| Sundry Debtors | Current Assets | Asset | Balance Sheet |
| Bank Accounts | Current Assets | Asset | Balance Sheet |
| Cash-in-hand | Current Assets | Asset | Balance Sheet |
| Stock-in-hand | Current Assets | Asset | Balance Sheet |
| Loans & Advances (Asset) | Current Assets | Asset | Balance Sheet |
| Deposits (Asset) | Current Assets | Asset | Balance Sheet |
| Sales Accounts | — | Income | P&L (Trading) |
| Direct Incomes | — | Income | P&L (Trading) |
| Indirect Incomes | — | Income | P&L |
| Purchase Accounts | — | Expense | P&L (Trading) |
| Direct Expenses | — | Expense | P&L (Trading) |
| Indirect Expenses | — | Expense | P&L |
| Suspense A/c | — | Liability | Balance Sheet |

Ledgers belong to a group; a ledger's nature comes from its group. Drawings is a ledger under
Capital Account (normally debit balance).

### Voucher types and their rules

| Type | Must have | Must not have |
| --- | --- | --- |
| Contra | Only Cash-in-hand / Bank Accounts ledgers, on both sides | Any other ledger |
| Payment | At least one Cr line to Cash-in-hand / Bank Accounts | Only cash/bank on both sides (that is Contra) |
| Receipt | At least one Dr line to Cash-in-hand / Bank Accounts | Only cash/bank on both sides |
| Sales | At least one Cr line to Sales Accounts | — |
| Purchase | At least one Dr line to Purchase Accounts, Fixed Assets, Direct Expenses or Indirect Expenses | — |
| Credit Note | At least one Dr line to Sales Accounts (sales return) | — |
| Debit Note | At least one Cr line to Purchase Accounts (purchase return) | — |
| Journal | Any non-cash/bank ledgers | Cash-in-hand / Bank Accounts lines |

### Rules on every voucher (rule IDs are used in error messages and tests)

| ID | Rule |
| --- | --- |
| V-01 | At least 2 lines |
| V-02 | Each line: exactly one of debit/credit > 0; the other = 0 |
| V-03 | No negative amounts; max 2 decimal places |
| V-04 | Sum of debits = sum of credits exactly |
| V-05 | Every ledger exists, belongs to the same client, and is active |
| V-06 | Voucher date inside an existing financial year of the client |
| V-07 | Voucher date's period is open (not locked) |
| V-08 | Voucher-type rules (table above) |
| V-09 | Narration is required |
| V-10 | Possible duplicate (same client + type + party ledger + reference no + total) → block unless the user confirms with a reason (stored) |
| V-11 | Only Approved vouchers can be posted; posted vouchers cannot be edited or deleted |
| V-12 | Reversal creates a new voucher with every line's Dr/Cr swapped, linked both ways; original becomes Reversed; a voucher can be reversed only once |

Numbering: drafts get an internal ID only. The voucher number is assigned **at posting**, sequential
per client + financial year + voucher type, no gaps, e.g. `SAL/2026-27/0001`.

### Balances

Debit balance positive, credit balance negative internally; reports show "Dr"/"Cr" with positive amounts.
Opening balances per ledger per financial year: total Dr must equal total Cr, otherwise show the
difference and block posting for that client until fixed.

## 6. How to work on a phase

1. Read `CLAUDE.md`, `docs/REQUIREMENTS.md`, and the current phase prompt.
2. Restate the task in 5–10 lines and list anything ambiguous. If anything is ambiguous, ask before coding.
3. Write tests first (red), then code (green), then clean up.
4. Each test for an accounting rule names the rule ID, e.g. `test_V04_unbalanced_voucher_rejected`.
5. Expected values in tests are typed literally (hand-calculated), never computed by the code under test.
6. Run the full test suite before saying a step is done. Paste the summary line.
7. End every step with: what was built, files changed, test result, open questions, next step.
8. Never start the next phase. The owner moves to the next phase after the accountant sign-off.

## 7. Repository layout

```
ledgermind-ai/
  CLAUDE.md
  docs/REQUIREMENTS.md
  docs/PHASE_PROMPTS.md
  docs/test-packs/            # human-readable test packs + expected answers for accountants
  database/migrations/        # NNNN_name.sql, source of truth for schema
  database/seeds/
  backend/app/engine/         # pure accounting engine (no DB/web/AI)
  backend/app/rules/          # rule-table loaders (tax rules etc.)
  backend/app/db/             # SQLAlchemy Core tables + repositories
  backend/app/services/       # use-cases: create/approve/post/reverse voucher, reports
  backend/app/api/            # FastAPI routers
  backend/app/importers/      # Excel/CSV/Tally/bank importers
  backend/app/ai/             # Phase 7+: OCR + LLM extraction (draft only)
  backend/tests/unit/  backend/tests/integration/  backend/tests/acceptance/
  frontend/src/
```

## 8. Environment

Owner works on Windows (PowerShell). Give PowerShell commands.
`.env` (never committed): `DATABASE_URL`, `TEST_DATABASE_URL`, later `OPENROUTER_API_KEY`, `LLM_MODEL`.
Commit `.env.example` with placeholder values only.
