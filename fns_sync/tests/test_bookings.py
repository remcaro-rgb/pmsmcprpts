"""`python -m fns_sync bookings`: the active bookings of the active hotels from the FNS API, as CSV."""

import csv
import io
from datetime import date, timedelta

from fake_fns import PASSWORD, USER, FakeFNS
from fns_sync import bookings
from fns_sync.client import FNSClient
from fns_sync.config import Config

TODAY = date(2026, 11, 24)
ALOJ = 987_656
CFG = Config(user=USER, password=PASSWORD, central_id=4274, alojamiento_id=ALOJ, hotel_code="FRT", pause=0)


def client(cfg, fake):
    return FNSClient(cfg, transport=fake.transport(), sleep=lambda s: None)


def test_active_bookings_as_csv():
    fake = FakeFNS(ALOJ, TODAY)
    rows, problems = bookings.for_hotels([CFG], TODAY, 365, lambda cfg: client(cfg, fake))
    assert problems == []
    assert rows == [{"hotel": "FRT", "name": "Jorge Prieto", "booking_number": "4882407816",
                     "check_in": TODAY + timedelta(days=10), "email": "jorge@example.com"}]
    # FNS searches by booking date, 30 days at a time: a year is 13 searches for the active ones.
    searches = [body for path, body in fake.calls if path == "/v1/reservas/listado.php"]
    assert len(searches) == 13 and {b["filter"]["estado"] for b in searches} == {"activas"}
    assert all(b["filter"]["central_id"] == 4274 and b["filter"]["verTitular"] == 1 for b in searches)
    out = io.StringIO()
    assert bookings.write_csv(rows, out) == 1
    assert list(csv.reader(io.StringIO(out.getvalue()))) == [
        ["hotel", "name", "booking_number", "check_in", "email"],
        ["FRT", "Jorge Prieto", "4882407816", str(TODAY + timedelta(days=10)), "jorge@example.com"]]


def test_stays_that_ended_and_cancellations_are_left_out(monkeypatch):
    payload = {
        "1": {"info": {"localizador": "A1", "estado": "Confirmada", "fecha_entrada": "2026-11-20",
                       "fecha_salida": "2026-11-26"}, "titular": {"nombre": "Ana", "email": "ana@x.com"}},
        "2": {"info": {"localizador": "B2", "estado": "Confirmada", "fecha_entrada": "2026-11-01",
                       "fecha_salida": "2026-11-03"}, "titular": {"nombre": "Bea"}},
        "3": {"info": {"localizador": "C3", "estado": "Cancelada", "fecha_entrada": "2026-12-01",
                       "fecha_salida": "2026-12-03", "cancellation_date": "2026-11-10 10:00:00"}},
        "4": {"info": {"localizador": "D4", "estado": "Confirmada", "fecha_entrada": "2026-12-24",
                       "fecha_salida": "2026-12-26"}, "cliente": {"nombre": "Carlos", "primerapellido": "Ruiz",
                                                                   "email": "carlos@x.com"}},
    }
    c = client(CFG, FakeFNS(ALOJ, TODAY))
    monkeypatch.setattr(c, "call", lambda name, body: payload)
    rows = bookings.active_bookings(CFG, c, TODAY, 30)
    # Staying now and arriving later; not the stay that ended nor the cancelled one; by check-in.
    assert [(r["booking_number"], r["name"], r["email"]) for r in rows] == [
        ("A1", "Ana", "ana@x.com"), ("D4", "Carlos Ruiz", "carlos@x.com")]


def test_a_hotel_fns_refuses_is_reported_and_the_others_still_count():
    fake = FakeFNS(ALOJ, TODAY)
    other = Config(**{**CFG.__dict__, "hotel_code": "BAD", "password": "wrong"})
    rows, problems = bookings.for_hotels([other, CFG], TODAY, 30, lambda cfg: client(cfg, fake))
    assert [r["hotel"] for r in rows] == ["FRT"]
    assert len(problems) == 1 and problems[0].startswith("BAD: ") and "HTTP 403" in problems[0]


def test_the_command_covers_every_active_hotel(monkeypatch, tmp_path, capsys):
    import os

    import psycopg
    import pytest

    from fns_sync import __main__ as cli

    admin_url, dsn = os.environ.get("PMS_TEST_ADMIN_URL"), os.environ.get("PMS_TEST_DATABASE_URL")
    if not (admin_url and dsn):
        pytest.skip("PMS_TEST_ADMIN_URL / PMS_TEST_DATABASE_URL not set")
    url = psycopg.conninfo.make_conninfo(admin_url, dbname=psycopg.conninfo.conninfo_to_dict(dsn)["dbname"])
    fake = FakeFNS(ALOJ, date.today())
    real = bookings.FNSClient
    monkeypatch.setattr(bookings, "FNSClient", lambda cfg: real(cfg, transport=fake.transport(), sleep=lambda s: None))
    with psycopg.connect(url, autocommit=True) as conn:
        try:
            for aloj, code, enabled in ((ALOJ, "BKA", True), (ALOJ + 1, "BKP", False)):
                conn.execute("INSERT INTO pms.fns_hotels (alojamiento_id, central_id, code, name, enabled) "
                             "VALUES (%s, 4274, %s, %s, %s)", (aloj, code, code, enabled))
            env = {"FNS_DATABASE_URL": url, "FNS_USER": USER, "FNS_PASSWORD": PASSWORD, "FNS_PAUSE": "0"}
            monkeypatch.setattr(os, "environ", {**os.environ, **env})
            out = tmp_path / "activas.csv"
            assert cli.main(["bookings", "--created-days", "30", "--out", str(out)]) == 0
            lines = out.read_text().splitlines()
            # Only the active hotel (BKP is paused); other hotels added in this database may answer too.
            assert lines[0] == "hotel,name,booking_number,check_in,email"
            assert any(line.startswith("BKA,Jorge Prieto,4882407816,") for line in lines)
            assert not any(line.startswith("BKP,") for line in lines)
        finally:
            conn.execute("DELETE FROM pms.fns_hotels WHERE alojamiento_id IN (%s, %s)", (ALOJ, ALOJ + 1))
