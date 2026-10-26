#!/bin/bash
# User accounts and their hotels (schema "app"), the hotels' external IDs, and the pms_app role
# the agent uses to manage them. Runs once on first container start; safe to re-run on an existing
# database:
#   docker compose exec -T db bash < db/init/05_users.sh
#
# Hotel access: when the MCP server runs with PMS_USER_DIRECTORY=true it passes the signed-in user
# (pms.user_email) with every query, and pms.allowed_hotel_ids() returns that user's hotels from
# app.user_hotels, or every hotel for an administrator. Anyone else (unknown, deactivated, or no
# user) sees no hotel data. Without a directory user the earlier pms.allowed_hotels rule applies.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_password="${PMS_APP_PASSWORD:?PMS_APP_PASSWORD is required}" <<'SQL'
SET client_min_messages = warning;

-- Hotels' IDs in other systems (already in 01_schema.sql for new databases).
ALTER TABLE pms.hotels ADD COLUMN IF NOT EXISTS alojamiento_id integer;
ALTER TABLE pms.hotels ADD COLUMN IF NOT EXISTS pms_id integer;
UPDATE pms.hotels SET alojamiento_id = 1000 + id WHERE alojamiento_id IS NULL;
UPDATE pms.hotels SET pms_id = 500 + id WHERE pms_id IS NULL;
ALTER TABLE pms.hotels ALTER COLUMN alojamiento_id SET NOT NULL, ALTER COLUMN pms_id SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'pms.hotels'::regclass
                   AND pg_get_constraintdef(oid) LIKE 'CHECK ((alojamiento_id > 0))') THEN
        ALTER TABLE pms.hotels ADD CHECK (alojamiento_id > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'pms.hotels'::regclass
                   AND pg_get_constraintdef(oid) LIKE 'CHECK ((pms_id > 0))') THEN
        ALTER TABLE pms.hotels ADD CHECK (pms_id > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'pms.hotels'::regclass
                   AND pg_get_constraintdef(oid) = 'UNIQUE (alojamiento_id)') THEN
        ALTER TABLE pms.hotels ADD UNIQUE (alojamiento_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'pms.hotels'::regclass
                   AND pg_get_constraintdef(oid) = 'UNIQUE (pms_id)') THEN
        ALTER TABLE pms.hotels ADD UNIQUE (pms_id);
    END IF;
END $$;
COMMENT ON COLUMN pms.hotels.alojamiento_id IS 'Lodging (alojamiento) ID of the hotel in external systems; integer > 0.';
COMMENT ON COLUMN pms.hotels.pms_id IS 'Property ID of the hotel in the PMS; integer > 0.';

CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE IF NOT EXISTS app.users (
    id            serial PRIMARY KEY,
    uniqueid      text UNIQUE,                     -- the person's ID in your organisation (optional)
    name          text NOT NULL CHECK (btrim(name) <> ''),
    email         text NOT NULL UNIQUE CHECK (email = lower(email) AND email LIKE '_%@_%'),
    phone         text,
    notes         text,
    password_hash text,                            -- NULL: no password sign-in (e.g. Google only)
    is_admin      boolean NOT NULL DEFAULT false,  -- administrators see every hotel
    active        boolean NOT NULL DEFAULT true,   -- deactivated users see no hotel data
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app.user_hotels (
    user_id  integer NOT NULL REFERENCES app.users ON DELETE CASCADE,
    hotel_id integer NOT NULL REFERENCES pms.hotels ON DELETE CASCADE,
    PRIMARY KEY (user_id, hotel_id)
);

-- The agent's login for user administration. BYPASSRLS so it can list every hotel; it only runs
-- fixed queries, never SQL written by the model.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pms_app') THEN
        CREATE ROLE pms_app LOGIN BYPASSRLS;
    END IF;
END $$;
ALTER ROLE pms_app PASSWORD :'app_password';
GRANT CONNECT ON DATABASE :"DBNAME" TO pms_app;
GRANT USAGE ON SCHEMA app, pms TO pms_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON app.users, app.user_hotels TO pms_app;
GRANT USAGE ON SEQUENCE app.users_id_seq TO pms_app;
GRANT SELECT ON pms.hotels TO pms_app;
GRANT UPDATE (alojamiento_id, pms_id) ON pms.hotels TO pms_app;
-- pms_readonly (the model's queries) gets nothing in schema app: no user list, no password hashes.
REVOKE ALL ON SCHEMA app FROM PUBLIC;

-- Hotel access for directory users; replaces the version in 04_hotel_access.sql.
CREATE OR REPLACE FUNCTION pms.allowed_hotel_ids() RETURNS integer[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pms AS $$
    WITH setting AS (
        SELECT coalesce(current_setting('pms.allowed_hotels', true), '') AS hotels,
               lower(btrim(coalesce(current_setting('pms.user_email', true), ''))) AS who
    ), member AS (
        SELECT u.id, u.is_admin FROM app.users u, setting s
        WHERE s.who <> '' AND u.email = s.who AND u.active
    )
    SELECT coalesce(array_agg(h.id ORDER BY h.id), '{}')
    FROM hotels h, setting s
    WHERE CASE
        WHEN EXISTS (SELECT 1 FROM member)
            THEN EXISTS (SELECT 1 FROM member WHERE is_admin)
                 OR h.id IN (SELECT uh.hotel_id FROM app.user_hotels uh JOIN member m ON m.id = uh.user_id)
        ELSE s.hotels = '*' OR h.code = ANY (string_to_array(upper(replace(s.hotels, ' ', '')), ','))
    END
$$;
SQL
