# LedgerMind AI

An accountant's calculator for Indian CA-office work. See [CLAUDE.md](CLAUDE.md) for the project rules and
[docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) for the approved requirements.

All commands are PowerShell, run from the repository root (`C:\temp\Account`) unless stated.

## One-time setup

```powershell
# 1. Python 3.12 virtual environment + backend dependencies
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".\backend[dev]"

# 2. Environment file (never committed)
Copy-Item .env.example .env
# edit .env: set DATABASE_URL and TEST_DATABASE_URL to the SAME Supabase session-pooler string
# from Supabase dashboard -> Project -> Connect

# 3. Frontend dependencies
cd frontend
npm install
cd ..
```

## Run the backend

```powershell
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
# check: http://127.0.0.1:8000/health  ->  {"status":"ok","db":"ok"}
```

`db` is `"error"` until `DATABASE_URL` in `.env` is valid and the Supabase project is awake
(free projects pause after 7 days idle).

## API

The FastAPI app serves the endpoints of [docs/API_CONTRACT.md](docs/API_CONTRACT.md); interactive docs are at
`http://127.0.0.1:8000/docs` while the backend runs.

- **No login in Phase 1.** Every request that changes data must send the header `X-User: <name>`; that name is written to
  the audit log as the actor. A missing or blank header gives `400 invalid_actor`. Reads do not need it. Real login and
  roles come before anyone besides the owner uses the tool.
- Amounts travel as **strings** with 2 decimals (`"12500.00"`); a JSON number for an amount is refused with 422.
- Each request is one database transaction: committed when the handler finishes, rolled back on any error.
- Rule failures of a voucher answer `422 {"errors": [{"rule_id", "message", "line_no"}]}`; other refusals answer
  `{"code", "message", "details"}` (404 not found, 409 conflict, 422 invalid input).

## Run the tests

```powershell
cd backend
..\.venv\Scripts\python -m pytest                                  # fast: unit tests only, no database
..\.venv\Scripts\python -m pytest -m integration                   # database tests (ledgermind_test schema), ~2 min
..\.venv\Scripts\python -m pytest -m "integration or not integration"   # everything: required before every commit
..\.venv\Scripts\python -m ruff check .                            # lint
```

Database tests carry the `integration` marker and only ever run in the `ledgermind_test` schema.

## Database migrations

**One Supabase project, two schemas:** `public` holds dev data; `ledgermind_test` is for automated tests only.
`DATABASE_URL` and `TEST_DATABASE_URL` are the same string; the code selects the schema.

SQL files in `database/migrations/` are applied in name order, one transaction per file, and each schema has its
own `schema_migrations` table:

```powershell
cd backend
..\.venv\Scripts\python -m app.db.migrate --target test   # schema ledgermind_test (created if missing)
..\.venv\Scripts\python -m app.db.migrate --target dev    # schema public
```

- After the migrations, `database/seeds/*.sql` are applied the same way (recorded as `seeds/<file>`); seeds are safe
  to run twice. The test cleanup (`TRUNCATE`) re-runs them.
- Migration files are schema-agnostic: they never write `public.` or `ledgermind_test.`; a unit test checks this.
- Schema guard: test fixtures and `--target test` refuse to run unless `current_schema() = 'ledgermind_test'`.
  Test cleanup only runs `TRUNCATE` on tables inside `ledgermind_test`; nothing is ever dropped or truncated outside it.
- `ledgermind_test` is closed to the Supabase API roles and must **not** be added to the API "exposed schemas".
- Use the **Session pooler** connection string (port 5432) from Supabase -> Connect. The "Direct connection"
  host is IPv6-only on free projects and does not resolve on many networks.
- Percent-encode special characters in the password (`@` becomes `%40`).
- **Go-live cleanup** (before real client data, together with moving to a Pro project with backups):

```sql
DROP SCHEMA ledgermind_test CASCADE;
```

## Run the frontend

```powershell
cd frontend
npm run dev
# open the URL it prints (http://localhost:5173); /health calls are proxied to the backend on port 8000
```

## Notes

- Supabase is used as plain PostgreSQL. Only the backend connects to the database; no database key or password
  goes into frontend code or git.
- `.mcp.json` connects Claude Code to the Supabase project, read-only. It holds no secrets.
