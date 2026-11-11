-- 0004: (1) money is rejected, never rounded, at database level; (2) the Supabase API roles hold nothing.
-- Schema-agnostic: the connection's search_path decides the schema (current_schema() below).

-- =====================================================================================================
-- 1. Money: an amount with more than 2 decimals must FAIL. NUMERIC(18,2) silently rounds 10.005 to 10.01.
--    NUMERIC(18,4) keeps what was sent, and the CHECK refuses anything that is not a whole number of paise.
--    (scale() cannot be used: a NUMERIC(18,4) column stores 10.5 as 10.5000, whose scale is 4.)
--    Values read back have 4 decimals (10.5000); callers quantize to 2 places.
-- =====================================================================================================
ALTER TABLE voucher_lines
    ALTER COLUMN debit  TYPE numeric(18, 4),
    ALTER COLUMN credit TYPE numeric(18, 4),
    ADD CONSTRAINT voucher_lines_debit_two_decimals  CHECK (debit  = round(debit, 2)),
    ADD CONSTRAINT voucher_lines_credit_two_decimals CHECK (credit = round(credit, 2));

ALTER TABLE opening_balances
    ALTER COLUMN debit  TYPE numeric(18, 4),
    ALTER COLUMN credit TYPE numeric(18, 4),
    ADD CONSTRAINT opening_balances_debit_two_decimals  CHECK (debit  = round(debit, 2)),
    ADD CONSTRAINT opening_balances_credit_two_decimals CHECK (credit = round(credit, 2));

-- =====================================================================================================
-- @@ section: close default grants
-- 2. Supabase grants new tables, sequences and functions to anon and authenticated by default.
--    Row-level security already denies row access; this removes the privileges as well, for the objects
--    that exist now and for future ones created by the migration role. Functions are also revoked from
--    PUBLIC, because the API roles inherit PUBLIC's EXECUTE. The backend connects as the table owner
--    (postgres), which keeps full access. service_role is not touched (the project never uses it).
--    On a PostgreSQL without these roles this does nothing.
-- =====================================================================================================
DO $$
DECLARE
    s text := current_schema();
    r text;
BEGIN
    EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM PUBLIC', s);
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I', s, r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %I', s, r);
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM %I', s, r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM %I', s, r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM %I', s, r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON FUNCTIONS FROM %I', s, r);
        END IF;
    END LOOP;
END $$;
