"""Integration tests for the schema, views and seeder.

Needs a Postgres server and a role allowed to create databases:
    PMS_TEST_ADMIN_URL=postgresql://pms:pms@localhost:5432/postgres pytest db/tests
"""

import os
import sys
import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest

DB_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DB_DIR))
import seed  # noqa: E402

ADMIN_URL = os.environ.get("PMS_TEST_ADMIN_URL")
BUSINESS_DATE = date(2026, 3, 10)

pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PMS_TEST_ADMIN_URL not set")


@pytest.fixture(scope="module")
def conn():
    name = f"pms_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    url = psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=name)
    try:
        with psycopg.connect(url, autocommit=True) as c:
            for f in ("01_schema.sql", "02_views.sql"):
                c.execute((DB_DIR / "init" / f).read_text())
        seed.main(["--dsn", url, "--business-date", BUSINESS_DATE.isoformat(),
                   "--history-days", "60", "--future-days", "45", "--seed", "7"])
        with psycopg.connect(url) as c:
            c.execute("SET search_path TO pms")
            yield c
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_reference_data(conn):
    assert scalar(conn, "SELECT count(*) FROM hotels") == 3
    assert scalar(conn, "SELECT sum(total_rooms) FROM hotels") == scalar(conn, "SELECT count(*) FROM rooms")
    assert scalar(conn, "SELECT business_date FROM system_settings") == BUSINESS_DATE


def test_no_double_booked_rooms(conn):
    assert scalar(conn, """
        SELECT count(*) FROM reservations a JOIN reservations b
          ON a.room_id = b.room_id AND a.id < b.id
         AND a.arrival < b.departure AND b.arrival < a.departure
        WHERE a.status <> 'cancelled' AND b.status <> 'cancelled'""") == 0


def test_status_consistent_with_business_date(conn):
    bad = scalar(conn, """
        SELECT count(*) FROM reservations, system_settings s WHERE
           (status = 'confirmed'   AND arrival < s.business_date)
        OR (status = 'checked_in'  AND NOT (arrival < s.business_date AND departure >= s.business_date))
        OR (status = 'checked_out' AND departure >= s.business_date)
        OR booked_at >= s.business_date::timestamptz + interval '1 day'
        OR (status = 'cancelled' AND (cancelled_at < booked_at OR room_id IS NOT NULL))
        OR (status <> 'cancelled' AND room_id IS NULL)""")
    assert bad == 0


def test_nights_match_rates(conn):
    assert scalar(conn, """
        SELECT count(*) FROM reservations r
        WHERE r.nights <> (SELECT count(*) FROM reservation_nights n WHERE n.reservation_id = r.id)""") == 0


def test_kpis_are_sane(conn):
    row = conn.execute("""
        SELECT min(occupancy), max(occupancy), min(adr) FILTER (WHERE rooms_sold > 0),
               bool_and(revpar = round(room_revenue / rooms_available, 2))
        FROM v_daily_kpis WHERE is_actual""").fetchone()
    min_occ, max_occ, min_adr, revpar_ok = row
    assert 0.3 < min_occ <= max_occ <= 1
    assert min_adr > 30
    assert revpar_ok


def test_closed_folios_are_paid(conn):
    assert scalar(conn, """
        SELECT count(*) FROM folios f
        WHERE f.status = 'closed' AND abs(
            (SELECT coalesce(sum(amount + tax_amount), 0) FROM folio_charges WHERE folio_id = f.id)
          - (SELECT coalesce(sum(amount), 0) FROM payments WHERE folio_id = f.id)) > 0.05""") == 0


def test_views_cover_every_channel(conn):
    channels = {r[0] for r in conn.execute("SELECT DISTINCT channel FROM v_channel_mix")}
    assert {"ota", "direct_web", "corporate", "wholesale"} <= channels
    assert scalar(conn, "SELECT count(*) FROM v_guest_stays WHERE stays > 0") > 0
    assert scalar(conn, "SELECT count(*) FROM v_pickup WHERE cancelled_on < booked_on") == 0


def test_seed_is_deterministic():
    a = seed.Seeder(BUSINESS_DATE, 20, 10, seed=3).run()
    b = seed.Seeder(BUSINESS_DATE, 20, 10, seed=3).run()
    assert a["reservations"] == b["reservations"]
    assert a["folio_charges"] == b["folio_charges"]
