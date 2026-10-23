"""A full import against the stand-in API (fake_fns.py) into the test database: every method is
called and stored, the data obeys per-hotel access, and the agent's tools can read it."""

import os
from dataclasses import replace
from datetime import date, timedelta

import psycopg
import pytest

from fake_fns import PASSWORD, USER, FakeFNS
from fns_sync.client import ENDPOINTS, FNSClient
from fns_sync.config import Config
from fns_sync.sync import Sync

ADMIN_URL = os.environ.get("PMS_TEST_ADMIN_URL")
DSN = os.environ.get("PMS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not (ADMIN_URL and DSN), reason="PMS_TEST_ADMIN_URL / PMS_TEST_DATABASE_URL not set")

TODAY = date(2026, 10, 20)
ALOJ = 987_654
CFG = Config(user=USER, password=PASSWORD, central_id=4274, alojamiento_id=ALOJ, hotel_code="FRT",
             hotel_name="Fragata Test", hotel_city="Cartagena", hotel_country="Colombia", timezone="America/Bogota",
             refresh_days=3, forward_days=40, backfill_days=35, pause=0)


@pytest.fixture
def owner():
    dbname = psycopg.conninfo.conninfo_to_dict(DSN)["dbname"]
    with psycopg.connect(psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=dbname), autocommit=True) as conn:
        try:
            yield conn
        finally:
            conn.execute("DELETE FROM pms.hotels WHERE alojamiento_id = %s", (ALOJ,))
            conn.execute("DELETE FROM pms.fns_exchange_rates WHERE rate_date BETWEEN %s AND %s",
                         (TODAY - timedelta(days=60), TODAY))


def sync(cfg=CFG, fake=None):
    fake = fake or FakeFNS(ALOJ, TODAY)
    return Sync(cfg, FNSClient(cfg, transport=fake.transport(), sleep=lambda s: None), sleep=lambda s: None), fake


def counts(conn) -> dict[str, int]:
    tables = ["fns_master_items", "fns_revenue_daily", "fns_production_cc", "fns_production", "fns_sales_reservations",
              "fns_sales_reservation_days", "fns_pos_sales", "fns_accounting_entries", "fns_accounting_lines",
              "fns_third_parties", "fns_reservations", "fns_reservation_rooms", "fns_room_blocks", "fns_availability",
              "fns_rates"]
    return {t: conn.execute(f"SELECT count(*) FROM pms.{t} t JOIN pms.hotels h ON h.id = t.hotel_id "
                            "WHERE h.alojamiento_id = %s", (ALOJ,)).fetchone()[0] for t in tables}


def readonly(query, hotels):
    with psycopg.connect(DSN) as c, c.transaction():
        c.execute("SET LOCAL pms.allowed_hotels = " + psycopg.sql.quote(hotels))
        return c.execute(query).fetchall()


def test_first_import_calls_every_method_and_stores_it(owner):
    s, fake = sync()
    result = s.run(owner, today=TODAY)
    assert result["backfill"] and result["status"] == "ok", [c for c in result["calls"] if not c.get("ok")]
    assert {p for p, _ in fake.calls} == set(ENDPOINTS.values())
    # Neither the master list the API refused nor the latest days without an exchange rate fail the run.
    failed = [c["window"] for c in result["calls"] if not c.get("ok")]
    assert failed == ["usuariosGastro"] + [f"{d}..{d}" for d in (TODAY - timedelta(days=1), TODAY)]
    # One call per method for the whole history, except the API's 30-day searches and the recent
    # days of the production report (one each, so they stay daily).
    per_path = {}
    for path, _ in fake.calls:
        per_path[path] = per_path.get(path, 0) + 1
    assert per_path == {
        "/v1/maestros/alojamiento.php": 20, "/v1/maestros/cambio.php": 1, "/v1/ventas/revenue.php": 1,
        "/v1/ventas/produccion_cc.php": 1, "/v1/ventas/produccion.php": 1 + CFG.refresh_days + 1,
        "/v1/custom/ventas1.php": 1, "/v1/ventas/pos.php": 1, "/v1/contabilidad/cobros.php": 1,
        "/v1/contabilidad/facturacion.php": 1, "/v1/contabilidad/produccion.php": 1,
        "/v1/reservas/listado.php": 3 * 2, "/v1/reservas/bloqueos.php": 4, "/v1/disponibilidad/consulta.php": 1}

    n = counts(owner)
    history = CFG.backfill_days + 1
    assert n["fns_revenue_daily"] == history + CFG.forward_days
    assert n["fns_production_cc"] == 2 * history
    # 3 channels: the history as one period, then the recent days with an exchange rate.
    assert n["fns_production"] == 3 * (1 + CFG.refresh_days + 1 - 2)
    periods = owner.execute("SELECT DISTINCT prod_date, period_end FROM pms.fns_production p JOIN pms.hotels h "
                            "ON h.id = p.hotel_id WHERE h.alojamiento_id = %s ORDER BY 1", (ALOJ,)).fetchall()
    assert periods[0] == (TODAY - timedelta(days=CFG.backfill_days), TODAY - timedelta(days=CFG.refresh_days + 1))
    assert all(a == b for a, b in periods[1:])
    assert n["fns_reservations"] == 2 and n["fns_reservation_rooms"] == 2  # active (modified) + cancelled
    assert n["fns_room_blocks"] == 1 and n["fns_third_parties"] == 1
    assert n["fns_availability"] == 2 * 41 and n["fns_rates"] == 2 * 41 * 3
    assert all(v > 0 for v in n.values()), n

    hotel = owner.execute("SELECT code, name, currency, total_rooms, timezone FROM pms.hotels WHERE alojamiento_id = %s",
                          (ALOJ,)).fetchone()
    assert hotel == ("FRT", "Fragata Test", "EUR", 30, "America/Bogota")
    booking = owner.execute("SELECT status, nights, total_price, cancelled_at IS NULL, client_country "
                            "FROM pms.fns_reservations WHERE localizador = '4882407816'").fetchone()
    assert booking == ("Modificada", 3, 450, True, "ES")
    # Requests follow the spec: reservation searches stay within 30 days; amounts net of tax.
    for path, body in fake.calls:
        f = body.get("filter", body)
        if "start_date" in f and path.startswith("/v1/reservas"):
            assert (date.fromisoformat(f["end_date"]) - date.fromisoformat(f["start_date"])).days < 30
        if "impuesto" in f:
            assert f["impuesto"] == 0

    # Daily refresh: only the recent days, the same rows (no duplicates).
    s2, fake2 = sync()
    again = s2.run(owner, today=TODAY)
    assert not again["backfill"] and again["status"] == "ok" and counts(owner) == n
    revenue_starts = {b["filter"]["start_date"] for p, b in fake2.calls if p.endswith("revenue.php")}
    assert min(revenue_starts) == (TODAY - timedelta(days=CFG.refresh_days)).isoformat()


def test_hotel_access_and_kpis(owner):
    sync()[0].run(owner, today=TODAY)
    q = ("SELECT (SELECT count(*) FROM fns_revenue_daily), (SELECT count(*) FROM fns_reservations), "
         "(SELECT count(*) FROM fns_accounting_lines), (SELECT count(*) FROM v_fns_reservation_revenue)")
    mine = readonly(q, "FRT")[0]
    assert all(mine) and readonly(q, "LIS") == [(0, 0, 0, 0)] and readonly(q, "") == [(0, 0, 0, 0)]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        readonly("SELECT count(*) FROM fns_sync_runs", "*")
    # The FNS days are in v_daily_kpis: 20 of 30 rooms sold, room revenue 1600.50.
    kpi = readonly("SELECT rooms_available, rooms_sold, occupancy, adr, room_revenue, total_revenue, is_actual "
                   "FROM v_daily_kpis WHERE hotel_code = 'FRT' AND stay_date = '2026-10-15'", "FRT")
    assert [tuple(map(lambda v: float(v) if v is not None and not isinstance(v, bool) else v, r)) for r in kpi] == \
        [(30.0, 20.0, 0.6667, 80.03, 1600.5, None, True)]
    # Guests repeat per reservation; the view counts each reservation day once.
    per_res = readonly("SELECT count(*), sum(room_revenue) FROM v_fns_reservation_revenue", "FRT")[0]
    assert per_res[0] == readonly("SELECT count(DISTINCT (reservation_id, prod_date)) FROM fns_sales_reservation_days",
                                  "FRT")[0][0]


@pytest.mark.anyio
async def test_the_agents_tools_see_fragata(owner):
    from mcp.client import Client
    from pms_mcp.access import HotelAccess
    from pms_mcp.server import build_server
    sync()[0].run(owner, today=TODAY)
    access = HotelAccess.parse("* = FRT")
    async with Client(build_server(DSN, access=access)) as c:
        schema = (await c.call_tool("describe_schema", {})).structured_content
        assert [h["code"] for h in schema["hotels"]] == ["FRT"] and schema["hotels"][0]["fns_data_as_of"]
        assert {"fns_revenue_daily", "fns_reservations", "v_fns_reservation_revenue"} <= \
            {r["name"] for r in schema["relations"]}
        kpis = (await c.call_tool("get_kpis", {"start": "2026-10-01", "end": "2026-10-31", "granularity": "month",
                                               "hotels": ["FRT"]})).structured_content
        assert kpis["rows"][0][0] == "FRT" and kpis["rows"][0][3] > 0


def test_wrong_credentials_stop_the_run(owner):
    s, _ = sync(replace(CFG, password="wrong"))
    result = s.run(owner, today=TODAY)
    assert result["status"] == "failed" and "Check FNS_USER" in result["calls"][-1]["error"]
    assert len(result["calls"]) == 1  # stops at the first denied call


def test_currency(owner):
    from fns_sync import store
    sync()[0].run(owner, today=TODAY, only={"accounting"})
    hotel_id = owner.execute("SELECT id FROM pms.hotels WHERE alojamiento_id = %s", (ALOJ,)).fetchone()[0]
    # The accounting entries say EUR (id 1); FNS_MONEDA_ID wins, and the label always matches the id.
    assert store.hotel_currency(owner, hotel_id, CFG) == (1, "EUR")
    assert store.hotel_currency(owner, hotel_id, replace(CFG, moneda_id=10, currency="COP")) == (10, "COP")
    assert store.hotel_currency(owner, hotel_id, replace(CFG, moneda_id=2)) == (2, "USD")
    owner.execute("DELETE FROM pms.fns_accounting_entries WHERE hotel_id = %s", (hotel_id,))
    assert store.hotel_currency(owner, hotel_id, replace(CFG, currency="COP")) == (1, "EUR")
    assert store.hotel_currency(owner, hotel_id, replace(CFG, currency="USD")) == (2, "USD")


def test_an_interrupted_first_import_resumes(owner):
    # The API stops answering at the revenue report: the run stops after a few calls instead of
    # waiting on every remaining one, and keeps what it had loaded.
    fake = FakeFNS(ALOJ, TODAY)
    fake.down = {"/v1/ventas/revenue.php", "/v1/ventas/produccion_cc.php", "/v1/custom/ventas1.php"}
    first = sync(fake=fake)[0].run(owner, today=TODAY)
    assert first["status"] == "failed" and "could not reach the API" in first["calls"][-1]["error"]
    assert [c["method"] for c in first["calls"]][-3:] == ["revenue", "production_cc", "sales_reservations"]
    assert "revenue" in first["pending"] and "production" in first["pending"]
    assert counts(owner)["fns_master_items"] > 0 and counts(owner)["fns_revenue_daily"] == 0

    # The API answers again: steps already loaded refresh only the recent days; the rest load history.
    fake.down = set()
    second = sync(fake=fake)[0].run(owner, today=TODAY)
    assert second["status"] == "ok" and second["pending"] == []
    assert counts(owner)["fns_revenue_daily"] == CFG.backfill_days + 1 + CFG.forward_days
    third = sync(fake=fake)[0].run(owner, today=TODAY)
    assert not third["backfill"] and third["pending"] == []


def test_long_ranges_the_api_refuses_are_read_in_parts(owner):
    fake = FakeFNS(ALOJ, TODAY)
    fake.limits = {"/v1/ventas/revenue.php": 60}      # "Period not valid" above 60 days
    fake.slow = {"/v1/contabilidad/cobros.php": 31}   # times out above 31 days
    result = sync(fake=fake)[0].run(owner, today=TODAY)
    assert result["status"] == "ok", [c for c in result["calls"] if not c.get("ok")]
    assert counts(owner)["fns_revenue_daily"] == CFG.backfill_days + 1 + CFG.forward_days
    revenue = [c for c in result["calls"] if c["method"] == "revenue"]
    assert not revenue[0]["ok"] and revenue[0]["optional"] and all(c["ok"] for c in revenue[1:])
    assert len(revenue) == 1 + 3  # the refused range, then 30-day parts
    payments = [c for c in result["calls"] if c["method"] == "payments"]
    assert "no answer within" in payments[0]["error"] and all(c["ok"] for c in payments[1:])
