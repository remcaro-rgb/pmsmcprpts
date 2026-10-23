-- Data imported every day from the FNSrooms PMS API (fns_sync/), one hotel per FNS
-- alojamiento_id. Tables live in schema pms next to the sample tables, so the MCP server's tools
-- see them, and each has hotel_id with the same row-level security as the rest: a user sees only
-- the hotels assigned to them. Amounts are in the hotel's currency (hotels.currency), net of tax
-- unless the column says otherwise.
--
-- Runs on first database start and again every time the fns-sync service starts (safe to re-run).

SET search_path = pms;
SET client_min_messages = warning;

-- Master data of the hotel (maestros/alojamiento.php): room types (th), cost centres (cc), offers,
-- channels, segments, agencies... one row per item.
CREATE TABLE IF NOT EXISTS fns_master_items (
    hotel_id   integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    kind       text NOT NULL,
    item_id    text NOT NULL,
    name       text,
    data       jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hotel_id, kind, item_id)
);
COMMENT ON TABLE fns_master_items IS 'FNS master data per hotel. kind: th (room types), cc (cost centres), ofertas (offers/rates), canales (channels), subcanales, segmentos (market segments), agencias (travel agencies), agentes, empresas (companies), paises (countries), usuarios, sucursales, salones (event rooms), pv (points of sale), servicios, habitaciones (rooms), th_completo, clientes, alojamientos. item_id is the FNS id used in other fns_* tables (e.g. fns_production_cc.cc_id = item_id where kind = ''cc'').';

-- Daily exchange rates (maestros/cambio.php): 1 unit of from_moneda_id = rate units of to_moneda_id.
CREATE TABLE IF NOT EXISTS fns_exchange_rates (
    rate_date      date NOT NULL,
    from_moneda_id integer NOT NULL,
    to_moneda_id   integer NOT NULL,
    rate           numeric NOT NULL,
    PRIMARY KEY (rate_date, from_moneda_id, to_moneda_id)
);
COMMENT ON TABLE fns_exchange_rates IS 'Daily FNS exchange rates: amount_in_to = amount_in_from * rate. FNS currency ids: 1 = EUR, 2 = USD; hotels.currency is the hotel''s own currency.';

-- Revenue report per stay date (ventas/revenue.php): past days are actuals, future days are
-- on-the-books business.
CREATE TABLE IF NOT EXISTS fns_revenue_daily (
    hotel_id          integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    stay_date         date NOT NULL,
    rooms_total       integer,  -- num_hab_tot: rooms available that day (blocked rooms excluded)
    rooms_blocked     integer,  -- bloqueadas: rooms out of order / blocked
    rooms_sold        integer,  -- ocupadas: occupied rooms that generate revenue
    rooms_occupied    integer,  -- ocupadas_totales: occupied rooms including complimentary
    rooms_complimentary integer,  -- ocupadas_sinprecio: complimentary (free) rooms
    rooms_unsold      integer,  -- disponibles: rooms still available to sell
    day_use           integer,
    group_rooms       integer,  -- habitaciones_grupo
    room_revenue      numeric,  -- precio_total_act: room revenue
    commission        numeric,  -- comision: commissions paid on the room revenue
    adr               numeric,  -- precio_medio: room_revenue / rooms_sold
    occupancy_pct     numeric,  -- porc_cos_ocu: rooms_sold / rooms_total * 100
    occupancy_all_pct numeric,  -- porc_gen_ocu: rooms_occupied / rooms_total * 100
    revpar            numeric,  -- room_revenue / rooms_total
    arrivals          integer,  -- checkin
    departures        integer,  -- checkout
    avg_length_of_stay numeric, -- estancia_media
    extra_beds        integer,
    cribs             integer,
    guests            integer,  -- pax: guests in paying rooms
    guests_total      integer,  -- pax_totales: guests including complimentary rooms
    adults            integer,
    teens             integer,
    children          integer,
    babies            integer,
    no_shows          integer,  -- reservas_noshow
    cancellations     integer,  -- canceladas: reservations cancelled
    fetched_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hotel_id, stay_date)
);
COMMENT ON TABLE fns_revenue_daily IS 'FNS revenue report: one row per hotel and stay date with rooms, occupancy, ADR, RevPAR, arrivals, guests and cancellations (room revenue only, net of tax). Future dates are on-the-books. For a period: occupancy = sum(rooms_sold)/sum(rooms_total), ADR = sum(room_revenue)/sum(rooms_sold), RevPAR = sum(room_revenue)/sum(rooms_total); never average the daily *_pct, adr or revpar columns. Also in v_daily_kpis.';

-- Production (sales) per day and cost centre (ventas/produccion_cc.php).
CREATE TABLE IF NOT EXISTS fns_production_cc (
    hotel_id   integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    prod_date  date NOT NULL,
    cc_id      text NOT NULL,
    amount     numeric NOT NULL,
    PRIMARY KEY (hotel_id, prod_date, cc_id)
);
COMMENT ON TABLE fns_production_cc IS 'FNS production (revenue by service date) per day and cost centre, net of tax: rooms, food & beverage, events, spa... Cost centre names: fns_master_items kind = ''cc'' (item_id = cc_id). Total hotel revenue for a day = sum(amount).';

-- Production per day by channel and market segment (ventas/produccion.php grouped by canal_id,
-- segmento_id).
CREATE TABLE IF NOT EXISTS fns_production (
    hotel_id   integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    prod_date  date NOT NULL,
    channel_id text NOT NULL,  -- '' when not applicable
    segment_id text NOT NULL,  -- '' when not applicable
    amount     numeric NOT NULL,
    PRIMARY KEY (hotel_id, prod_date, channel_id, segment_id)
);
COMMENT ON TABLE fns_production IS 'FNS production (revenue by service date, all sources: rooms, events, F&B), net of tax, per day, sales channel and market segment. Names: fns_master_items kind = ''canales'' (channel_id) and ''segmentos'' (segment_id).';

-- Production per reservation and guest with a breakdown per stay day (custom/ventas1.php).
CREATE TABLE IF NOT EXISTS fns_sales_reservations (
    hotel_id        integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    reservation_id  bigint NOT NULL,
    guest_name      text NOT NULL,
    holder_name     text,
    holder_email    text,
    company         text,
    agency          text,
    agent           text,
    rate_name       text,
    nights          integer,
    booked_at       timestamp,
    arrival         date,
    departure       date,
    room_type       text,
    occupancy       integer,  -- people in the reservation
    segment         text,
    subsegment      text,
    channel         text,
    guest_age       integer,
    guest_gender    text,
    nationality     text,
    origin          text,     -- procedencia: where the guest travels from
    reason          text,     -- motivo: reason for the trip
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hotel_id, reservation_id, guest_name)
);
COMMENT ON TABLE fns_sales_reservations IS 'FNS reservations with their guests: one row per reservation and guest (a reservation with 2 guests has 2 rows) with channel, segment, rate, room type, dates and guest age, gender, nationality and origin. Revenue per day: fns_sales_reservation_days, or v_fns_reservation_revenue (one row per reservation and day, no duplicates).';

CREATE TABLE IF NOT EXISTS fns_sales_reservation_days (
    hotel_id        integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    reservation_id  bigint NOT NULL,
    guest_name      text NOT NULL,
    prod_date       date NOT NULL,
    room_revenue    numeric,  -- rrev
    other_revenue   numeric,  -- orev: other services charged to the reservation
    cost            numeric,
    courtesy        numeric,  -- cortesia: complimentary amount
    PRIMARY KEY (hotel_id, reservation_id, guest_name, prod_date),
    FOREIGN KEY (hotel_id, reservation_id, guest_name)
        REFERENCES fns_sales_reservations ON DELETE CASCADE
);
COMMENT ON TABLE fns_sales_reservation_days IS 'Revenue per reservation, guest and day. The amounts repeat on each guest of the same reservation: sum them per reservation from v_fns_reservation_revenue instead, or you will double count.';

CREATE OR REPLACE VIEW v_fns_reservation_revenue WITH (security_invoker = true) AS
SELECT DISTINCT ON (d.hotel_id, d.reservation_id, d.prod_date)
       d.hotel_id, h.code AS hotel_code, d.reservation_id, d.prod_date,
       d.room_revenue, d.other_revenue, d.cost, d.courtesy,
       r.channel, r.segment, r.subsegment, r.rate_name, r.room_type, r.company, r.agency,
       r.arrival, r.departure, r.nights, r.booked_at
FROM fns_sales_reservation_days d
JOIN fns_sales_reservations r USING (hotel_id, reservation_id, guest_name)
JOIN hotels h ON h.id = d.hotel_id
ORDER BY d.hotel_id, d.reservation_id, d.prod_date, d.guest_name;
COMMENT ON VIEW v_fns_reservation_revenue IS 'One row per FNS reservation and stay day with room and other revenue and the reservation''s channel, segment, rate, room type, company and agency. Use for revenue by channel, segment, rate or room type.';

-- Point-of-sale (restaurant, bar) sales per day and item (ventas/pos.php).
CREATE TABLE IF NOT EXISTS fns_pos_sales (
    hotel_id    integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    pos_id      text NOT NULL,   -- punto_de_venta_id; names in fns_master_items kind = 'pv'
    sale_date   date NOT NULL,
    recipe_id   text NOT NULL,
    code        text,
    name        text,
    quantity    numeric,
    value       numeric,         -- valor: sales value
    tax         numeric,
    cost        numeric,
    PRIMARY KEY (hotel_id, pos_id, sale_date, recipe_id)
);
COMMENT ON TABLE fns_pos_sales IS 'FNS point-of-sale (Gastro: restaurants, bars) sales per day, outlet and item: quantity sold, sales value, tax and cost. Outlet names: fns_master_items kind = ''pv''.';

-- Accounting (contabilidad/cobros.php, facturacion.php, produccion.php): entries with their debit
-- and credit lines, and the third parties (guests, companies) they belong to.
CREATE TABLE IF NOT EXISTS fns_accounting_entries (
    hotel_id         integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    book             text NOT NULL CHECK (book IN ('payments', 'invoices', 'production')),
    entry_id         text NOT NULL,   -- identificador
    entry_at         timestamp,
    operational_ref  text,            -- auxiliar_operativo, e.g. R12345 = reservation 12345
    origin           text,            -- origen: reservas, eventos, gastro
    moneda_id        integer,
    currency         text,
    tax_id           text,            -- cif: NIF/CIF of the third party
    document         text,
    invoice_id       text,
    invoice_code     text,
    invoice_type     text,
    payment_method_id text,
    payment_method   text,            -- fp_codigo, e.g. TARJETA (card), EFECTIVO (cash)
    account_type     text,            -- tipocuenta
    PRIMARY KEY (hotel_id, book, entry_id)
);
COMMENT ON TABLE fns_accounting_entries IS 'FNS accounting entries. book: payments (cobros: payments and deposits received), invoices (facturacion: invoices issued), production (produccion: revenue produced, invoiced or not). Lines in fns_accounting_lines; third party in fns_third_parties (tax_id).';

CREATE TABLE IF NOT EXISTS fns_accounting_lines (
    hotel_id      integer NOT NULL,
    book          text NOT NULL,
    entry_id      text NOT NULL,
    side          text NOT NULL CHECK (side IN ('debit', 'credit')),
    line_key      text NOT NULL,
    account       text,
    description   text,
    amount        numeric,   -- debit lines are negative, credit lines positive
    tax_base      numeric,
    tax_rate      numeric,   -- percent
    cc_id         text,
    cc_name       text,
    payment_method_id text,
    PRIMARY KEY (hotel_id, book, entry_id, side, line_key),
    FOREIGN KEY (hotel_id, book, entry_id) REFERENCES fns_accounting_entries ON DELETE CASCADE
);
COMMENT ON TABLE fns_accounting_lines IS 'Debit and credit lines of FNS accounting entries: ledger account, description, amount (debit negative, credit positive), tax base and rate, cost centre. Example: payments received by method = sum(credit amount) of book payments grouped by fns_accounting_entries.payment_method.';

CREATE TABLE IF NOT EXISTS fns_third_parties (
    hotel_id      integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    tax_id        text NOT NULL,
    name          text,
    full_name     text,
    document_type text,
    address       text,
    city          text,
    email         text,
    country_iso   text,
    PRIMARY KEY (hotel_id, tax_id)
);
COMMENT ON TABLE fns_third_parties IS 'Guests and companies in FNS accounting entries, by tax id (fns_accounting_entries.tax_id).';

-- Reservations (reservas/listado.php), by creation date.
CREATE TABLE IF NOT EXISTS fns_reservations (
    hotel_id        integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    localizador     text NOT NULL,    -- booking reference
    status          text,             -- estado: Confirmada, Cancelada, Modificada...
    channel_id      integer,
    channel         text,             -- channel_nombre: Booking, Expedia, fnsRooms (direct)...
    channel_reservation_id text,
    booking_code    text,             -- cod_res
    booking_type    text,             -- tipo: individual, grupo
    arrival         date,
    departure       date,
    nights          integer GENERATED ALWAYS AS (departure - arrival) STORED,
    guests          integer,
    arrival_time    time,
    payment_model   text,             -- e.g. Al Hotel (pay at hotel), Prepago
    total_price     numeric,
    paid_online     numeric,
    pay_on_arrival  numeric,
    amount_pending  numeric,
    commission      numeric,
    moneda_id       integer,
    booked_at       timestamp,        -- creation_date
    cancelled_at    timestamp,
    modified_at     timestamp,
    checked_in_at   timestamp,
    checked_out_at  timestamp,
    paid_at         timestamp,
    client_name     text,
    client_surname  text,
    client_email    text,
    client_phone    text,
    client_country  text,
    holder_name     text,
    holder_surname  text,
    holder_email    text,
    holder_phone    text,
    holder_country  text,
    special_conditions text,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hotel_id, localizador)
);
COMMENT ON TABLE fns_reservations IS 'FNS reservations: status, channel, dates, nights, guests, total price, commission, payment, check-in/out times and the client and holder (name, email, phone, country). Rooms per reservation in fns_reservation_rooms. Lead time = arrival - booked_at::date. Cancelled: status ILIKE ''cancel%'' or cancelled_at IS NOT NULL.';

CREATE TABLE IF NOT EXISTS fns_reservation_rooms (
    hotel_id     integer NOT NULL,
    localizador  text NOT NULL,
    detail_id    text NOT NULL,
    reservation_id bigint,          -- FNS internal id (fns_sales_reservations.reservation_id)
    room_type_id text,              -- names in fns_master_items kind = 'th'
    occupancy    integer,
    meal_plan_id text,              -- regimen_id
    offer_id     text,              -- oferta_id; names in fns_master_items kind = 'ofertas'
    price        numeric,
    price_after_tax numeric,
    client_name  text,
    arrival      date,
    departure    date,
    nights       integer,
    PRIMARY KEY (hotel_id, localizador, detail_id),
    FOREIGN KEY (hotel_id, localizador) REFERENCES fns_reservations ON DELETE CASCADE
);
COMMENT ON TABLE fns_reservation_rooms IS 'Rooms of each FNS reservation: room type, occupancy, meal plan, offer (rate), price before and after tax and dates.';

-- Rooms blocked (out of order / maintenance) (reservas/bloqueos.php).
CREATE TABLE IF NOT EXISTS fns_room_blocks (
    hotel_id     integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    block_id     text NOT NULL,
    room_type_id text,
    room_type    text,
    room_id      text,
    room         text,
    start_date   date,
    end_date     date,
    reason       text,
    created_at   timestamp,
    updated_at   timestamp,
    PRIMARY KEY (hotel_id, block_id)
);
COMMENT ON TABLE fns_room_blocks IS 'FNS room blocks (out of order, maintenance): room, room type, start and end date (inclusive) and reason.';

-- Availability, prices and restrictions for upcoming dates (disponibilidad/consulta.php), latest
-- values from the last sync.
CREATE TABLE IF NOT EXISTS fns_availability (
    hotel_id     integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    stay_date    date NOT NULL,
    room_type_id text NOT NULL,
    available    integer,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hotel_id, stay_date, room_type_id)
);
COMMENT ON TABLE fns_availability IS 'FNS rooms still available to sell per upcoming date and room type, as of the last daily sync (fetched_at). Room type names: fns_master_items kind = ''th''.';

CREATE TABLE IF NOT EXISTS fns_rates (
    hotel_id     integer NOT NULL REFERENCES hotels ON DELETE CASCADE,
    stay_date    date NOT NULL,
    room_type_id text NOT NULL,
    rate_id      text NOT NULL,     -- offer id; names in fns_master_items kind = 'ofertas'
    occupancy    integer NOT NULL,  -- people; 0 when the rate has no prices that day
    price        numeric,
    min_stay     integer,           -- minlos
    closed       boolean,           -- closerate
    closed_to_arrival boolean,
    closed_to_departure boolean,
    release_days integer,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hotel_id, stay_date, room_type_id, rate_id, occupancy)
);
COMMENT ON TABLE fns_rates IS 'FNS selling prices per upcoming date, room type, rate and occupancy, with restrictions (minimum stay, closed, closed to arrival/departure, release), as of the last daily sync.';

-- Sync bookkeeping, for the fns-sync service only.
CREATE TABLE IF NOT EXISTS fns_sync_runs (
    id           bigserial PRIMARY KEY,
    hotel_id     integer REFERENCES hotels ON DELETE CASCADE,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'partial', 'failed')),
    backfill     boolean NOT NULL DEFAULT false,
    calls        jsonb NOT NULL DEFAULT '[]'
);
COMMENT ON TABLE fns_sync_runs IS 'Daily FNS imports: when they ran, whether each API call succeeded and how many rows it stored.';

CREATE INDEX IF NOT EXISTS fns_reservations_arrival ON fns_reservations (hotel_id, arrival);
CREATE INDEX IF NOT EXISTS fns_reservations_booked ON fns_reservations (hotel_id, booked_at);
CREATE INDEX IF NOT EXISTS fns_sales_reservations_arrival ON fns_sales_reservations (hotel_id, arrival);
CREATE INDEX IF NOT EXISTS fns_accounting_entries_at ON fns_accounting_entries (hotel_id, entry_at);

-- Row-level security: the same per-hotel access as the other tables (04_hotel_access.sql).
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['fns_master_items', 'fns_revenue_daily', 'fns_production_cc',
                             'fns_production', 'fns_sales_reservations', 'fns_sales_reservation_days',
                             'fns_pos_sales', 'fns_accounting_entries', 'fns_accounting_lines',
                             'fns_third_parties', 'fns_reservations', 'fns_reservation_rooms',
                             'fns_room_blocks', 'fns_availability', 'fns_rates', 'fns_sync_runs'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS hotel_access ON %I', t);
        EXECUTE format('CREATE POLICY hotel_access ON %I FOR SELECT '
                       'USING (hotel_id = ANY ((SELECT allowed_hotel_ids())::integer[]))', t);
    END LOOP;
END $$;

-- The model's role reads the data but not the sync log; exchange rates are shared reference data.
GRANT SELECT ON fns_master_items, fns_exchange_rates, fns_revenue_daily, fns_production_cc,
    fns_production, fns_sales_reservations, fns_sales_reservation_days, v_fns_reservation_revenue,
    fns_pos_sales, fns_accounting_entries, fns_accounting_lines, fns_third_parties,
    fns_reservations, fns_reservation_rooms, fns_room_blocks, fns_availability, fns_rates
    TO pms_readonly;
REVOKE ALL ON fns_sync_runs FROM pms_readonly;

-- v_daily_kpis (02_views.sql) plus the FNS hotels' days from fns_revenue_daily, so get_kpis and
-- the reporting queries cover them too. The first part is the same as in 02_views.sql. FNS hotels
-- have no F&B/spa/other split by day here (NULL); see fns_production_cc.
CREATE OR REPLACE VIEW v_daily_kpis WITH (security_invoker = true) AS
WITH dates AS (
    SELECT h.id AS hotel_id, d::date AS stay_date
    FROM hotels h
    CROSS JOIN system_settings s
    CROSS JOIN generate_series(s.data_start,
        (SELECT max(stay_date) FROM reservation_nights), interval '1 day') d
),
inventory AS (
    SELECT hotel_id, count(*) AS rooms_available
    FROM rooms WHERE status = 'in_service' GROUP BY hotel_id
),
sold AS (
    SELECT r.hotel_id, n.stay_date, count(*) AS rooms_sold, sum(n.rate) AS room_revenue
    FROM reservation_nights n
    JOIN reservations r ON r.id = n.reservation_id
    WHERE r.status IN ('confirmed', 'checked_in', 'checked_out')
    GROUP BY r.hotel_id, n.stay_date
),
ancillary AS (
    SELECT r.hotel_id, (c.posted_at AT TIME ZONE h.timezone)::date AS stay_date,
           sum(c.amount) FILTER (WHERE c.department = 'fnb')     AS fnb_revenue,
           sum(c.amount) FILTER (WHERE c.department = 'spa')     AS spa_revenue,
           sum(c.amount) FILTER (WHERE c.department NOT IN ('room', 'fnb', 'spa')) AS other_revenue
    FROM folio_charges c
    JOIN folios f ON f.id = c.folio_id
    JOIN reservations r ON r.id = f.reservation_id
    JOIN hotels h ON h.id = r.hotel_id
    WHERE c.department <> 'room'
    GROUP BY 1, 2
)
SELECT d.hotel_id,
       h.code AS hotel_code,
       d.stay_date,
       d.stay_date < s.business_date AS is_actual,
       i.rooms_available,
       coalesce(so.rooms_sold, 0) AS rooms_sold,
       round(coalesce(so.rooms_sold, 0)::numeric / i.rooms_available, 4) AS occupancy,
       round(coalesce(so.room_revenue / nullif(so.rooms_sold, 0), 0), 2) AS adr,
       round(coalesce(so.room_revenue, 0) / i.rooms_available, 2) AS revpar,
       coalesce(so.room_revenue, 0) AS room_revenue,
       coalesce(a.fnb_revenue, 0) AS fnb_revenue,
       coalesce(a.spa_revenue, 0) AS spa_revenue,
       coalesce(a.other_revenue, 0) AS other_revenue,
       coalesce(so.room_revenue, 0) + coalesce(a.fnb_revenue, 0)
         + coalesce(a.spa_revenue, 0) + coalesce(a.other_revenue, 0) AS total_revenue
FROM dates d
JOIN hotels h ON h.id = d.hotel_id
JOIN inventory i ON i.hotel_id = d.hotel_id
CROSS JOIN system_settings s
LEFT JOIN sold so ON so.hotel_id = d.hotel_id AND so.stay_date = d.stay_date
LEFT JOIN ancillary a ON a.hotel_id = d.hotel_id AND a.stay_date = d.stay_date
UNION ALL
SELECT f.hotel_id,
       h.code,
       f.stay_date,
       f.stay_date < (now() AT TIME ZONE h.timezone)::date,
       f.rooms_total::bigint,
       coalesce(f.rooms_sold, 0)::bigint,
       round(coalesce(f.rooms_sold, 0)::numeric / nullif(f.rooms_total, 0), 4),
       round(coalesce(f.room_revenue / nullif(f.rooms_sold, 0), 0), 2),
       round(coalesce(f.room_revenue, 0) / nullif(f.rooms_total, 0), 2),
       coalesce(f.room_revenue, 0),
       NULL::numeric, NULL::numeric, NULL::numeric, NULL::numeric
FROM fns_revenue_daily f
JOIN hotels h ON h.id = f.hotel_id
WHERE f.rooms_total > 0;

COMMENT ON VIEW v_daily_kpis IS 'Per hotel per stay date: rooms_available, rooms_sold, occupancy (0-1), adr, revpar, room/fnb/spa/other/total revenue in the hotel''s currency. is_actual=false rows are on-the-books future business. For periods, aggregate rooms_sold, room_revenue and rooms_available and recompute ratios; never average daily occupancy/adr. Hotels imported from FNS (fns_revenue_daily) have NULL fnb/spa/other/total revenue: use fns_production_cc for revenue by cost centre.';
GRANT SELECT ON v_daily_kpis TO pms_readonly;
