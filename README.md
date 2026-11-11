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

## Run the tests

```powershell
cd backend
..\.venv\Scripts\python -m pytest            # all tests
..\.venv\Scripts\python -m pytest tests\unit # engine/unit tests only (no database)
..\.venv\Scripts\python -m ruff check .      # lint
```

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
