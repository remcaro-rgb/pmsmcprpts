#!/bin/bash
# Creates the read-only role used by the MCP server. Runs once on first container start.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v ro_password="${PMS_READONLY_PASSWORD:?PMS_READONLY_PASSWORD is required}" <<'SQL'
CREATE ROLE pms_readonly LOGIN PASSWORD :'ro_password';
ALTER ROLE pms_readonly SET search_path = pms;
ALTER ROLE pms_readonly SET statement_timeout = '15s';
ALTER ROLE pms_readonly SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE :"DBNAME" TO pms_readonly;
GRANT USAGE ON SCHEMA pms TO pms_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA pms TO pms_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA pms GRANT SELECT ON TABLES TO pms_readonly;
SQL
