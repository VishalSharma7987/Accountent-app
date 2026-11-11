-- 0002: Supabase's helper function rls_auto_enable() is SECURITY DEFINER and, by default, callable by the
-- anon / authenticated API roles (security advisors 0028 / 0029). Nothing in this project needs that.
-- Schema-agnostic: the function is found through the connection's search_path, so this is a no-op in
-- any schema that does not contain it (e.g. the test schema, or a plain PostgreSQL database).
DO $$
BEGIN
    IF to_regprocedure('rls_auto_enable()') IS NOT NULL THEN
        REVOKE EXECUTE ON FUNCTION rls_auto_enable() FROM PUBLIC, anon, authenticated;
    END IF;
END $$;
