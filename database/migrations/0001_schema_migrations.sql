-- 0001: bookkeeping table for the migration runner (backend/app/db/migrate.py).
-- Schema-agnostic: created in whatever schema the connection's search_path selects.
CREATE TABLE schema_migrations (
    filename   text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- Supabase exposes the tables of its API schema through the REST API; deny all by enabling RLS with
-- no policies. Only the backend's direct Postgres connection (table owner) reads/writes this table.
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
