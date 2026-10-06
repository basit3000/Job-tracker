#!/bin/bash
# Official PostgreSQL entrypoint runs this only for a fresh data directory.
set -e
: "${MIGRATOR_DB_PASSWORD:?Set MIGRATOR_DB_PASSWORD}"
: "${APP_DB_PASSWORD:?Set APP_DB_PASSWORD}"
for credential in "$MIGRATOR_DB_PASSWORD" "$APP_DB_PASSWORD"; do
  if [[ ! "$credential" =~ ^[a-fA-F0-9]{32,}$ ]]; then
    echo "Generate separate hexadecimal database passwords of at least 32 characters." >&2
    exit 1
  fi
done

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=migrator_password="$MIGRATOR_DB_PASSWORD" \
  --set=runtime_password="$APP_DB_PASSWORD" \
  --set=database_name="$POSTGRES_DB" <<'SQL'
BEGIN;
CREATE ROLE tracker_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'migrator_password';
CREATE ROLE tracker_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'runtime_password';
ALTER SCHEMA public OWNER TO tracker_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO tracker_runtime;
GRANT CONNECT ON DATABASE :"database_name" TO tracker_migrator, tracker_runtime;
COMMIT;
SQL
