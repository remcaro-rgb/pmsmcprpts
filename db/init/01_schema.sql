-- Sample hotel property-management-system (PMS) schema.
-- All money columns are in the hotel's currency (EUR for the sample chain).

CREATE SCHEMA IF NOT EXISTS pms;
SET search_path TO pms;

-- PMS-wide settings. business_date is the PMS "today": stays before it are actuals,
-- stays on/after it are on-the-books (future) business.
CREATE TABLE system_settings (
    id            boolean PRIMARY KEY DEFAULT true CHECK (id),
    business_date date NOT NULL,
    data_start    date NOT NULL
);

CREATE TABLE hotels (
    id           serial PRIMARY KEY,
    code         text NOT NULL UNIQUE,
    name         text NOT NULL,
    city         text NOT NULL,
    country      text NOT NULL,
    star_rating  smallint NOT NULL CHECK (star_rating BETWEEN 1 AND 5),
    total_rooms  integer NOT NULL,
    currency     char(3) NOT NULL,
    timezone     text NOT NULL,
    opened_on    date NOT NULL
);

CREATE TABLE room_types (
    id            serial PRIMARY KEY,
    hotel_id      integer NOT NULL REFERENCES hotels,
    code          text NOT NULL,
    name          text NOT NULL,
    max_occupancy smallint NOT NULL,
    base_rate     numeric(10,2) NOT NULL,
    UNIQUE (hotel_id, code)
);

CREATE TABLE rooms (
    id           serial PRIMARY KEY,
    hotel_id     integer NOT NULL REFERENCES hotels,
    room_type_id integer NOT NULL REFERENCES room_types,
    number       text NOT NULL,
    floor        smallint NOT NULL,
    status       text NOT NULL DEFAULT 'in_service'
                 CHECK (status IN ('in_service', 'out_of_order')),
    UNIQUE (hotel_id, number)
);

CREATE TABLE guests (
    id           serial PRIMARY KEY,
    first_name   text NOT NULL,
    last_name    text NOT NULL,
    email        text NOT NULL,
    phone        text,
    country      char(2) NOT NULL,
    loyalty_tier text NOT NULL DEFAULT 'none'
                 CHECK (loyalty_tier IN ('none', 'silver', 'gold', 'platinum')),
    created_at   timestamptz NOT NULL
);

CREATE TABLE companies (
    id                  serial PRIMARY KEY,
    name                text NOT NULL,
    industry            text NOT NULL,
    country             char(2) NOT NULL,
    negotiated_discount numeric(4,3) NOT NULL DEFAULT 0
);

CREATE TABLE travel_agents (
    id             serial PRIMARY KEY,
    name           text NOT NULL,
    agent_type     text NOT NULL CHECK (agent_type IN ('ota', 'wholesaler', 'tmc')),
    commission_pct numeric(4,3) NOT NULL
);

CREATE TABLE rate_plans (
    id                 serial PRIMARY KEY,
    hotel_id           integer NOT NULL REFERENCES hotels,
    code               text NOT NULL,
    name               text NOT NULL,
    refundable         boolean NOT NULL,
    includes_breakfast boolean NOT NULL,
    price_factor       numeric(4,3) NOT NULL DEFAULT 1,  -- multiplier on the best available rate
    UNIQUE (hotel_id, code)
);

CREATE TABLE reservations (
    id              serial PRIMARY KEY,
    confirmation_no text NOT NULL UNIQUE,
    hotel_id        integer NOT NULL REFERENCES hotels,
    guest_id        integer NOT NULL REFERENCES guests,
    company_id      integer REFERENCES companies,
    travel_agent_id integer REFERENCES travel_agents,
    channel         text NOT NULL CHECK (channel IN
                    ('direct_web', 'phone', 'walk_in', 'ota', 'gds', 'corporate', 'wholesale')),
    rate_plan_id    integer NOT NULL REFERENCES rate_plans,
    room_type_id    integer NOT NULL REFERENCES room_types,
    room_id         integer REFERENCES rooms,  -- assigned room; NULL for cancellations
    booked_at       timestamptz NOT NULL,
    arrival         date NOT NULL,
    departure       date NOT NULL,
    nights          integer GENERATED ALWAYS AS (departure - arrival) STORED,
    adults          smallint NOT NULL,
    children        smallint NOT NULL DEFAULT 0,
    status          text NOT NULL CHECK (status IN
                    ('confirmed', 'checked_in', 'checked_out', 'cancelled', 'no_show')),
    cancelled_at    timestamptz,
    CHECK (departure > arrival),
    CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
);

-- One row per room night with the rate charged for that night.
CREATE TABLE reservation_nights (
    reservation_id integer NOT NULL REFERENCES reservations,
    stay_date      date NOT NULL,
    rate           numeric(10,2) NOT NULL,
    PRIMARY KEY (reservation_id, stay_date)
);

CREATE TABLE folios (
    id             serial PRIMARY KEY,
    reservation_id integer NOT NULL REFERENCES reservations,
    opened_at      timestamptz NOT NULL,
    closed_at      timestamptz,
    status         text NOT NULL CHECK (status IN ('open', 'closed'))
);

CREATE TABLE folio_charges (
    id          serial PRIMARY KEY,
    folio_id    integer NOT NULL REFERENCES folios,
    posted_at   timestamptz NOT NULL,
    department  text NOT NULL CHECK (department IN
                ('room', 'fnb', 'spa', 'minibar', 'parking', 'other')),
    description text NOT NULL,
    amount      numeric(10,2) NOT NULL,  -- net of tax
    tax_amount  numeric(10,2) NOT NULL
);

CREATE TABLE payments (
    id       serial PRIMARY KEY,
    folio_id integer NOT NULL REFERENCES folios,
    method   text NOT NULL CHECK (method IN
             ('credit_card', 'debit_card', 'cash', 'virtual_card', 'invoice')),
    amount   numeric(10,2) NOT NULL,
    paid_at  timestamptz NOT NULL
);

CREATE TABLE staff (
    id         serial PRIMARY KEY,
    hotel_id   integer NOT NULL REFERENCES hotels,
    first_name text NOT NULL,
    last_name  text NOT NULL,
    department text NOT NULL CHECK (department IN
               ('front_office', 'housekeeping', 'fnb', 'spa', 'sales', 'management', 'maintenance')),
    role       text NOT NULL,
    hired_on   date NOT NULL
);

CREATE TABLE housekeeping_tasks (
    id            serial PRIMARY KEY,
    hotel_id      integer NOT NULL REFERENCES hotels,
    room_id       integer NOT NULL REFERENCES rooms,
    task_date     date NOT NULL,
    task_type     text NOT NULL CHECK (task_type IN ('departure_clean', 'stayover', 'inspection')),
    status        text NOT NULL CHECK (status IN ('pending', 'done', 'skipped')),
    staff_id      integer REFERENCES staff,
    minutes_spent smallint
);

CREATE TABLE reviews (
    id             serial PRIMARY KEY,
    reservation_id integer NOT NULL REFERENCES reservations,
    source         text NOT NULL CHECK (source IN ('google', 'booking_com', 'tripadvisor', 'internal_survey')),
    score          numeric(3,1) NOT NULL CHECK (score BETWEEN 1 AND 10),
    comment        text,
    created_at     timestamptz NOT NULL
);

-- Table and column docs, surfaced to the LLM by describe_schema.
COMMENT ON TABLE system_settings IS 'Single row. business_date = PMS "today"; dates before it are actuals, on/after it are on-the-books.';
COMMENT ON TABLE reservations IS 'One row per booking of one room. nights = departure - arrival. Cancelled and no_show bookings do not count as sold rooms.';
COMMENT ON COLUMN reservations.channel IS 'Booking source: direct_web, phone, walk_in, ota (Booking.com/Expedia-like), gds, corporate, wholesale.';
COMMENT ON TABLE reservation_nights IS 'One row per reservation per stay night with the nightly room rate (net of tax). Basis for rooms sold and room revenue.';
COMMENT ON TABLE folio_charges IS 'Guest bill line items. amount is net of tax. department room = room revenue; others are ancillary revenue.';
COMMENT ON TABLE housekeeping_tasks IS 'Daily room cleaning tasks; stayover for occupied rooms, departure_clean on checkout day.';
COMMENT ON COLUMN reviews.score IS 'Guest review score on a 1-10 scale.';
