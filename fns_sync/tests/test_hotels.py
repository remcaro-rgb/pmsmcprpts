"""Hotels added in the Admin page (pms.fns_hotels): when each is imported, its own FNS account,
and the progress the Admin page shows while an import runs."""

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.rows import dict_row

from fake_fns import PASSWORD, USER, FakeFNS
from fns_sync import __main__ as cli
from fns_sync import store
from fns_sync.client import FNSClient
from fns_sync.config import Config
from fns_sync.secret import decrypt, encrypt
from fns_sync.sync import HISTORY_STEPS, Sync

ADMIN_URL = os.environ.get("PMS_TEST_ADMIN_URL")
DSN = os.environ.get("PMS_TEST_DATABASE_URL")
db = pytest.mark.skipif(not (ADMIN_URL and DSN), reason="PMS_TEST_ADMIN_URL / PMS_TEST_DATABASE_URL not set")

BOGOTA = ZoneInfo("America/Bogota")
TODAY = date(2026, 10, 20)
ALOJ = 987_655
BASE = Config(user=USER, password=PASSWORD, central_id=0, alojamiento_id=0, timezone="America/Bogota",
              refresh_days=3, forward_days=40, backfill_days=35, pause=0, secret_key="test-key")
ROW = {"id": 1, "alojamiento_id": ALOJ, "central_id": 4274, "pms_id": None, "code": "NEW", "name": "New Hotel",
       "city": "Cartagena", "country": "Colombia", "timezone": "America/Bogota", "moneda_id": None, "currency": None,
       "sync_time": time(3, 0), "backfill_days": 35, "fns_user": None, "fns_password": None, "enabled": True,
       "run_requested_at": None, "hotel_id": None}
NEVER = {"started": None, "finished": None, "status": None, "last_ok": None}


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BOGOTA)


def ran(started: datetime, status: str = "ok", minutes: int = 5) -> dict:
    return {"started": started, "finished": started + timedelta(minutes=minutes), "status": status,
            "last_ok": started if status in ("ok", "partial") else None}


def test_when_a_hotel_is_imported():
    cfg = BASE.for_hotel(ROW)
    # A new hotel at once; the history until every step has loaded it (an hour after a cut-short run).
    assert cli.due(cfg, ROW, NEVER, True, at(20, 14)) == "first import"
    assert cli.due(cfg, ROW, ran(at(20, 14), "partial"), True, at(20, 14, 30)) is None
    assert cli.due(cfg, ROW, ran(at(20, 14), "partial"), True, at(20, 15, 10)) == "history still to load"
    # Then once a day at its time (hotel time), the missed one on start-up, and none twice.
    assert cli.due(cfg, ROW, ran(at(20, 3)), False, at(20, 23)) is None
    assert cli.due(cfg, ROW, ran(at(20, 3)), False, at(21, 2, 59)) is None
    assert cli.due(cfg, ROW, ran(at(20, 3)), False, at(21, 3)) == "daily import"
    assert cli.due(cfg, ROW, ran(at(18, 3)), False, at(20, 10)) == "daily import"
    # A daily import that failed: again after FNS_RETRY_MINUTES.
    assert cli.due(cfg, {**ROW}, {**ran(at(21, 3), "failed"), "last_ok": at(20, 3)}, False, at(21, 3, 30)) is None
    assert cli.due(cfg, ROW, {**ran(at(21, 3), "failed"), "last_ok": at(20, 3)}, False, at(21, 4, 6)) == "daily import"
    # "Import now", unless it already ran since; never while one runs.
    asked = {**ROW, "run_requested_at": at(20, 23)}
    assert cli.due(cfg, asked, ran(at(20, 3)), False, at(20, 23, 1)) == "requested in the Admin page"
    assert cli.due(cfg, asked, ran(at(20, 23, 1)), False, at(20, 23, 30)) is None
    assert cli.due(cfg, asked, {**ran(at(20, 3)), "status": "running"}, False, at(20, 23, 1)) is None


def test_each_hotel_uses_its_account_or_the_one_in_env():
    assert (BASE.for_hotel(ROW).user, BASE.for_hotel(ROW).password) == (USER, PASSWORD)
    own = {**ROW, "fns_user": "other", "fns_password": encrypt("other-secret", "test-key")}
    cfg = BASE.for_hotel(own)
    assert (cfg.user, cfg.password, cfg.hotel_code, cfg.alojamiento_id, cfg.central_id) == \
        ("other", "other-secret", "NEW", ALOJ, 4274)
    assert "other-secret" not in repr(cfg) and decrypt(own["fns_password"], "test-key") == "other-secret"
    with pytest.raises(ValueError, match="FNS_SECRET_KEY"):
        Config(**{**BASE.__dict__, "secret_key": "another-key"}).for_hotel(own)
    with pytest.raises(ValueError, match="enter the FNS password"):
        BASE.for_hotel({**own, "fns_password": None})
    with pytest.raises(ValueError, match="no FNS account"):
        Config(**{**BASE.__dict__, "user": "", "password": ""}).for_hotel(ROW)


@pytest.fixture
def owner():
    dbname = psycopg.conninfo.conninfo_to_dict(DSN)["dbname"]
    with psycopg.connect(psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=dbname), autocommit=True) as conn:
        store.ensure_schema(conn)
        try:
            yield conn
        finally:
            conn.execute("DELETE FROM pms.fns_hotels WHERE alojamiento_id IN (%s, %s)", (ALOJ, ALOJ + 1))
            conn.execute("DELETE FROM pms.hotels WHERE alojamiento_id IN (%s, %s)", (ALOJ, ALOJ + 1))
            conn.execute("DELETE FROM pms.fns_exchange_rates WHERE rate_date BETWEEN %s AND %s",
                         (TODAY - timedelta(days=60), TODAY))


def due(conn) -> list[tuple[int, str]]:
    """The test's hotels due now (ids, reasons), in the importer's order."""
    return [(row["id"], reason) for row, reason in cli.due_hotels(BASE, conn, datetime.now().astimezone())
            if row["alojamiento_id"] in (ALOJ, ALOJ + 1)]


def add(conn, **fields) -> dict:
    row = {k: v for k, v in {**ROW, **fields}.items() if k not in ("id", "hotel_id", "enabled")}
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO pms.fns_hotels ({cols}) VALUES ({', '.join(['%s'] * len(row))})", list(row.values()))
    return next(r for r in store.fns_hotels(conn, enabled_only=False) if r["alojamiento_id"] == row["alojamiento_id"])


@db
def test_a_new_hotel_loads_its_history_with_progress(owner):
    row = add(owner)
    fake = FakeFNS(ALOJ, TODAY)
    seen = []

    def make_sync(cfg):
        s = Sync(cfg, FNSClient(cfg, transport=fake.transport(), sleep=lambda s: None), sleep=lambda s: None)
        run = s.run
        s.run = lambda conn: run(conn, today=TODAY)
        original = s._progress

        def progress(method="", window=""):
            original(method, window)
            if method:  # what the Admin page reads while it runs
                seen.append(owner.execute("SELECT progress FROM pms.fns_sync_runs WHERE status = 'running' "
                                          "ORDER BY id DESC LIMIT 1").fetchone()[0])
        s._progress = progress
        return s

    assert due(owner) == [(row["id"], "first import")]
    result = cli.import_hotel(BASE, owner, row, make_sync=make_sync)
    assert result["status"] == "ok" and result["backfill"]
    hotel_id = owner.execute("SELECT hotel_id FROM pms.fns_hotels WHERE id = %s", (row["id"],)).fetchone()[0]
    assert owner.execute("SELECT code, name, timezone FROM pms.hotels WHERE id = %s", (hotel_id,)).fetchone() == \
        ("NEW", "New Hotel", "America/Bogota")
    assert store.loaded_steps(owner, hotel_id) == set(HISTORY_STEPS)
    # The progress grew call by call, and the finished run's says everything is done.
    assert seen and seen[0]["calls"] == 1 and seen[-1]["calls"] == len(result["calls"])
    assert all(p["planned"] >= p["calls"] for p in seen) and seen[-1]["steps_total"] == 11
    assert seen[0]["planned"] == len(result["calls"]) == 46  # the bar fills as planned
    final = owner.execute("SELECT progress FROM pms.fns_sync_runs WHERE hotel_id = %s ORDER BY id DESC LIMIT 1",
                          (hotel_id,)).fetchone()[0]
    assert final["steps_done"] == final["steps_total"] == 11 and final["rows"] == result["rows"] > 0


@db
def test_a_hotel_without_an_account_shows_why(owner):
    row = add(owner, alojamiento_id=ALOJ + 1, code="NOACC", fns_user="someone")
    assert cli.import_hotel(BASE, owner, row) is None
    with owner.cursor(row_factory=dict_row) as cur:
        run = cur.execute("SELECT r.status, r.calls FROM pms.fns_sync_runs r JOIN pms.fns_hotels f "
                          "ON f.hotel_id = r.hotel_id WHERE f.id = %s", (row["id"],)).fetchone()
    assert run["status"] == "failed" and "enter the FNS password" in run["calls"][0]["error"]
    # Not tried again until FNS_RETRY_MINUTES have passed.
    assert due(owner) == []


@db
def test_import_now_goes_first_and_env_hotel_is_added_once(owner):
    store.add_env_hotel(owner, Config(**{**BASE.__dict__, "alojamiento_id": ALOJ, "central_id": 4274,
                                         "hotel_code": "ENV", "hotel_name": "From env"}))
    store.add_env_hotel(owner, Config(**{**BASE.__dict__, "alojamiento_id": ALOJ, "central_id": 4274,
                                         "hotel_code": "ENV", "hotel_name": "Renamed in env"}))
    first = next(r for r in store.fns_hotels(owner) if r["alojamiento_id"] == ALOJ)
    assert first["name"] == "From env"  # afterwards the Admin page's settings win
    second = add(owner, alojamiento_id=ALOJ + 1, code="SECOND", run_requested_at=datetime.now().astimezone())
    assert due(owner) == [(second["id"], "requested in the Admin page"), (first["id"], "first import")]


@db
def test_the_import_log_keeps_each_call_with_its_request_and_answer(owner):
    from fns_sync import runlog

    row = add(owner)
    fake = FakeFNS(ALOJ, TODAY)

    def make_sync(cfg):
        s = Sync(cfg, FNSClient(cfg, transport=fake.transport(), sleep=lambda s: None), sleep=lambda s: None)
        run = s.run
        s.run = lambda conn: run(conn, today=TODAY)
        return s

    dbname = psycopg.conninfo.conninfo_to_dict(DSN)["dbname"]
    handler = runlog.install(psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=dbname))
    try:
        result = cli.import_hotel(BASE, owner, row, make_sync=make_sync)
    finally:
        cli.log.removeHandler(handler)
        handler.close()
    with owner.cursor(row_factory=dict_row) as cur:
        lines = cur.execute("SELECT l.* FROM pms.fns_sync_log l JOIN pms.fns_sync_runs r ON r.id = l.run_id "
                            "WHERE r.id = %s ORDER BY l.id", (result["run_id"],)).fetchall()
    hotel_id = owner.execute("SELECT hotel_id FROM pms.fns_hotels WHERE id = %s", (row["id"],)).fetchone()[0]
    assert {line["hotel_id"] for line in lines} == {hotel_id}
    calls = [line for line in lines if line["command"]]
    assert len(calls) == len(result["calls"])  # one line per API call
    revenue = next(line for line in calls if line["message"].startswith("revenue "))
    assert revenue["level"] == "info" and "answered (HTTP 200 in" in revenue["message"]
    assert revenue["command"].startswith("curl -sS -X POST 'https://ms.fnsmanager.com/v1/ventas/revenue.php' "
                                         "-u \"$FNS_USER:$FNS_PASSWORD\"")
    assert PASSWORD not in revenue["command"] and '"alojamiento_id":987655' in revenue["command"]
    assert revenue["output"].startswith("HTTP 200 in") and "num_hab_tot" in revenue["output"]
    # The list FNS refuses and the days without an exchange rate are warnings, not failures.
    warnings = [line["message"] for line in lines if line["level"] == "warning"]
    assert any(m.startswith("master usuariosGastro: ") and "HTTP 422" in m for m in warnings)
    assert any("No existe tipo de cambio" in m for m in warnings)
    assert not [line for line in lines if line["level"] == "error"]
    assert lines[-1]["message"].startswith("FNS import ok: ") and lines[-1]["level"] == "info"
