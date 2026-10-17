-- Per-hotel access, enforced by PostgreSQL row-level security.
--
-- Each query from the MCP server runs in a transaction that sets pms.allowed_hotels to the
-- hotel codes its user may see ('LIS,OPO'), or '*' for all hotels. Rows of other hotels are
-- invisible to the pms_readonly role in every table and view; with the setting unset or empty,
-- it sees no hotel data at all. The table owner (the seeder) is not affected.
--
-- Safe to re-run on an existing database:
--   docker compose exec -T db psql -U pms -d pms < db/init/04_hotel_access.sql

SET search_path = pms;
SET client_min_messages = warning;

-- Ids of the allowed hotels. SECURITY DEFINER so it can read hotels past the policy below.
CREATE OR REPLACE FUNCTION allowed_hotel_ids() RETURNS integer[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pms AS $$
    SELECT coalesce(array_agg(id), '{}')
    FROM hotels, (SELECT coalesce(current_setting('pms.allowed_hotels', true), '') AS s) setting
    WHERE s = '*' OR code = ANY (string_to_array(upper(replace(s, ' ', '')), ','))
$$;

-- Queries must not be able to change the setting. SET is a separate statement, which the MCP
-- server never runs from user SQL (one prepared statement); set_config() would work inside a
-- SELECT, so only superusers may call it.
REVOKE EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) FROM PUBLIC;

-- (SELECT allowed_hotel_ids()) is evaluated once per query, not per row; the cast makes ANY take
-- the array it returns rather than treat the subquery as a set of rows.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['hotels', 'room_types', 'rooms', 'rate_plans', 'reservations',
                             'reservation_nights', 'folios', 'folio_charges', 'payments', 'staff',
                             'housekeeping_tasks', 'reviews', 'guests'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS hotel_access ON %I', t);
    END LOOP;
END $$;

CREATE POLICY hotel_access ON hotels FOR SELECT USING (id = ANY ((SELECT allowed_hotel_ids())::integer[]));
CREATE POLICY hotel_access ON room_types FOR SELECT USING (hotel_id = ANY ((SELECT allowed_hotel_ids())::integer[]));
CREATE POLICY hotel_access ON rooms FOR SELECT USING (hotel_id = ANY ((SELECT allowed_hotel_ids())::integer[]));
CREATE POLICY hotel_access ON rate_plans FOR SELECT USING (hotel_id = ANY ((SELECT allowed_hotel_ids())::integer[]));
CREATE POLICY hotel_access ON reservations FOR SELECT USING (hotel_id = ANY ((SELECT allowed_hotel_ids())::integer[]));
CREATE POLICY hotel_access ON staff FOR SELECT USING (hotel_id = ANY ((SELECT allowed_hotel_ids())::integer[]));
CREATE POLICY hotel_access ON housekeeping_tasks FOR SELECT USING (hotel_id = ANY ((SELECT allowed_hotel_ids())::integer[]));
-- Tables without hotel_id follow their reservation (whose own policy applies inside these).
CREATE POLICY hotel_access ON reservation_nights FOR SELECT USING (reservation_id IN (SELECT id FROM reservations));
CREATE POLICY hotel_access ON folios FOR SELECT USING (reservation_id IN (SELECT id FROM reservations));
CREATE POLICY hotel_access ON reviews FOR SELECT USING (reservation_id IN (SELECT id FROM reservations));
CREATE POLICY hotel_access ON folio_charges FOR SELECT USING (folio_id IN (SELECT id FROM folios));
CREATE POLICY hotel_access ON payments FOR SELECT USING (folio_id IN (SELECT id FROM folios));
-- Guest profiles: only guests who stayed or booked at an allowed hotel.
CREATE POLICY hotel_access ON guests FOR SELECT USING (id IN (SELECT guest_id FROM reservations));
-- companies, travel_agents and system_settings are shared reference data.

-- Views run with the querying role's permissions, so the policies apply through them too.
ALTER VIEW v_daily_kpis SET (security_invoker = true);
ALTER VIEW v_pickup SET (security_invoker = true);
ALTER VIEW v_channel_mix SET (security_invoker = true);
ALTER VIEW v_guest_stays SET (security_invoker = true);
