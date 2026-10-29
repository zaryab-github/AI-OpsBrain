#!/bin/sh
# Runs once, when the PostgreSQL data volume is first initialised.
# Creates a non-superuser owner role (migrations) and a least-privilege runtime role (API/worker).
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_pw="$OPSBRAIN_DB_OWNER_PASSWORD" -v app_pw="$OPSBRAIN_DB_APP_PASSWORD" <<'EOSQL'
CREATE ROLE opsbrain_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE opsbrain_app LOGIN PASSWORD :'app_pw';
ALTER DATABASE opsbrain OWNER TO opsbrain_owner;
ALTER SCHEMA public OWNER TO opsbrain_owner;
REVOKE ALL ON DATABASE opsbrain FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE opsbrain TO opsbrain_owner, opsbrain_app;
CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -f /docker-entrypoint-initdb.d/grants.sql.inc
