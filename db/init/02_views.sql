-- Reporting views. They encode the hotel-industry KPI definitions once so that
-- queries (and the LLM) reuse them instead of re-deriving the formulas.

SET search_path TO pms;

-- Indexes supporting the views and common report queries.
CREATE INDEX ON reservations (hotel_id, arrival);
CREATE INDEX ON reservations (guest_id);
CREATE INDEX ON reservation_nights (stay_date);
CREATE INDEX ON folios (reservation_id);
CREATE INDEX ON folio_charges (folio_id);
CREATE INDEX ON folio_charges (posted_at);
CREATE INDEX ON housekeeping_tasks (hotel_id, task_date);
CREATE INDEX ON reviews (reservation_id);

-- Daily KPIs per hotel.
--   rooms_available = rooms in service
--   rooms_sold      = room nights of non-cancelled, non-no-show reservations
--   occupancy       = rooms_sold / rooms_available
--   adr             = room_revenue / rooms_sold     (Average Daily Rate)
--   revpar          = room_revenue / rooms_available (Revenue Per Available Room)
-- Ancillary revenue is by folio posting date and is only present for actual dates.
CREATE VIEW v_daily_kpis AS
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
LEFT JOIN ancillary a ON a.hotel_id = d.hotel_id AND a.stay_date = d.stay_date;

COMMENT ON VIEW v_daily_kpis IS 'Per hotel per stay date: rooms_available, rooms_sold, occupancy (0-1), adr, revpar, room/fnb/spa/other/total revenue. is_actual=false rows are on-the-books future business. For periods, aggregate rooms_sold, room_revenue and rooms_available and recompute ratios; never average daily occupancy/adr.';

-- One row per booked room night, with booking and cancellation dates, for pickup /
-- booking-pace analysis. Rooms on the books for stay_date as of day D:
--   booked_on <= D AND (cancelled_on IS NULL OR cancelled_on > D)
CREATE VIEW v_pickup AS
SELECT r.hotel_id,
       h.code AS hotel_code,
       n.stay_date,
       (r.booked_at AT TIME ZONE h.timezone)::date AS booked_on,
       (r.cancelled_at AT TIME ZONE h.timezone)::date AS cancelled_on,
       r.arrival - (r.booked_at AT TIME ZONE h.timezone)::date AS lead_days,
       r.status,
       r.channel,
       rp.code AS rate_plan_code,
       rt.code AS room_type_code,
       n.rate
FROM reservation_nights n
JOIN reservations r ON r.id = n.reservation_id
JOIN hotels h ON h.id = r.hotel_id
JOIN rate_plans rp ON rp.id = r.rate_plan_id
JOIN room_types rt ON rt.id = r.room_type_id;

COMMENT ON VIEW v_pickup IS 'One row per booked room night (including cancelled bookings) with booked_on, cancelled_on and lead_days. On-the-books as of day D: booked_on <= D AND (cancelled_on IS NULL OR cancelled_on > D).';

-- Channel performance by hotel and arrival month.
CREATE VIEW v_channel_mix AS
SELECT r.hotel_id,
       h.code AS hotel_code,
       date_trunc('month', r.arrival)::date AS arrival_month,
       r.channel,
       count(*) AS reservations,
       count(*) FILTER (WHERE r.status = 'cancelled') AS cancellations,
       round(count(*) FILTER (WHERE r.status = 'cancelled')::numeric / count(*), 4) AS cancellation_rate,
       count(*) FILTER (WHERE r.status = 'no_show') AS no_shows,
       coalesce(sum(r.nights) FILTER (WHERE r.status IN ('confirmed', 'checked_in', 'checked_out')), 0) AS room_nights,
       coalesce(sum(n.revenue) FILTER (WHERE r.status IN ('confirmed', 'checked_in', 'checked_out')), 0) AS room_revenue,
       round(coalesce(sum(n.revenue) FILTER (WHERE r.status IN ('confirmed', 'checked_in', 'checked_out'))
             / nullif(sum(r.nights) FILTER (WHERE r.status IN ('confirmed', 'checked_in', 'checked_out')), 0), 0), 2) AS adr,
       round(avg(r.arrival - (r.booked_at AT TIME ZONE h.timezone)::date), 1) AS avg_lead_days
FROM reservations r
JOIN hotels h ON h.id = r.hotel_id
JOIN LATERAL (SELECT sum(rate) AS revenue FROM reservation_nights WHERE reservation_id = r.id) n ON true
GROUP BY 1, 2, 3, 4;

COMMENT ON VIEW v_channel_mix IS 'Per hotel, arrival month and channel: reservations, cancellations, cancellation_rate (0-1), no_shows, room_nights and room_revenue of non-cancelled stays, adr, avg_lead_days.';

-- Guest-level stay history and spend (completed stays only).
CREATE VIEW v_guest_stays AS
SELECT g.id AS guest_id,
       g.first_name,
       g.last_name,
       g.country,
       g.loyalty_tier,
       count(r.id) AS stays,
       coalesce(sum(r.nights), 0) AS nights,
       coalesce(sum(sp.room_spend), 0) AS room_spend,
       coalesce(sum(sp.ancillary_spend), 0) AS ancillary_spend,
       coalesce(sum(sp.room_spend + sp.ancillary_spend), 0) AS total_spend,
       min(r.arrival) AS first_stay,
       max(r.arrival) AS last_stay,
       count(DISTINCT r.hotel_id) AS hotels_visited
FROM guests g
LEFT JOIN reservations r ON r.guest_id = g.id AND r.status = 'checked_out'
LEFT JOIN LATERAL (
    SELECT coalesce(sum(c.amount) FILTER (WHERE c.department = 'room'), 0) AS room_spend,
           coalesce(sum(c.amount) FILTER (WHERE c.department <> 'room'), 0) AS ancillary_spend
    FROM folios f JOIN folio_charges c ON c.folio_id = f.id
    WHERE f.reservation_id = r.id
) sp ON true
GROUP BY g.id;

COMMENT ON VIEW v_guest_stays IS 'Per guest: completed stays, nights, room/ancillary/total spend (net of tax), first/last stay, hotels_visited.';
