-- Runtime-role privileges. Applied at first initialisation and again after every restore.
-- Idempotent. (The .inc extension stops the postgres entrypoint from running it on its own.)
GRANT USAGE ON SCHEMA public TO opsbrain_app;
ALTER DEFAULT PRIVILEGES FOR ROLE opsbrain_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO opsbrain_app;
ALTER DEFAULT PRIVILEGES FOR ROLE opsbrain_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO opsbrain_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO opsbrain_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO opsbrain_app;
DO $$
BEGIN
  IF to_regclass('public.audit_log') IS NOT NULL THEN
    REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM opsbrain_app;
  END IF;
  IF to_regclass('public.alembic_version') IS NOT NULL THEN
    REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM opsbrain_app;
  END IF;
END $$;
