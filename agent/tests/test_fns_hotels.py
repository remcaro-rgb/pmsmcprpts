"""Hotels imported from FNSrooms, in the Admin page: adding one (its account encrypted), checking
the account with FNS, "Import now", and the live progress of a running import."""

import json
import os
import secrets
from datetime import datetime, timedelta

import httpx2
import psycopg
import pytest

from fakes import FakeClient, text_reply
from pms_agent.app import create_app
from pms_agent.config import Settings
from pms_agent.fns_hotels import FnsHotels, decrypt
from pms_agent.users import UserDirectory
from test_loop import toy_server

APP_DSN = os.environ.get("PMS_TEST_APP_DATABASE_URL")
ADMIN_URL = os.environ.get("PMS_TEST_ADMIN_URL")
needs_db = pytest.mark.skipif(not (APP_DSN and ADMIN_URL), reason="PMS_TEST_APP_DATABASE_URL / PMS_TEST_ADMIN_URL not set")
ALOJ = 876_543


@pytest.fixture
def anyio_backend():
    return "asyncio"


def owner() -> psycopg.Connection:
    dbname = psycopg.conninfo.conninfo_to_dict(APP_DSN)["dbname"]
    return psycopg.connect(psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=dbname), autocommit=True)


def fake_fns(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)["filter"]
    if request.headers.get("authorization") != httpx2.BasicAuth("fns-user", "fns-secret")._auth_header:
        return httpx2.Response(403, json={"mensaje": "Los datos de acceso no son válidos"})
    if body["alojamiento_id"] != ALOJ:
        return httpx2.Response(403, json={"error": "PMS not allowed to this property"})
    return httpx2.Response(200, json={" th": {"1": "Doble", "2": "Suite"}})


@pytest.fixture
async def site():
    tag = secrets.token_hex(4)
    admin = await UserDirectory(APP_DSN).upsert_admin(f"boss-{tag}@agent.test", "Boss", "boss-password-1")
    settings = Settings(mcp_url="unused", conversations_db=":memory:", app_database_url=APP_DSN,
                        fns_user="fns-user", fns_password="fns-secret", fns_secret_key="test-key")
    app = create_app(settings, FakeClient(text_reply("Hi.")), toy_server())
    fns = FnsHotels(APP_DSN, "test-key", "fns-user", "fns-secret", transport=httpx2.MockTransport(fake_fns))
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as http:
        try:
            yield http, {"x-pms-user": admin.email}, fns
        finally:
            with owner() as c:
                c.execute("DELETE FROM pms.hotels WHERE alojamiento_id IN (%s, %s)", (ALOJ, ALOJ + 1))
                c.execute("DELETE FROM pms.fns_hotels WHERE alojamiento_id IN (%s, %s)", (ALOJ, ALOJ + 1))
                c.execute("DELETE FROM app.users WHERE email LIKE %s", (f"%-{tag}@agent.test",))


NEW = {"alojamiento_id": ALOJ, "central_id": 4284, "code": "nue", "name": "Hotel Nuevo", "city": "Santa Marta",
       "country": "Colombia", "timezone": "America/Bogota", "currency": "cop", "sync_time": "04:30"}


@needs_db
@pytest.mark.anyio
async def test_adding_a_hotel_queues_its_first_import(site):
    http, as_admin, _ = site
    assert (await http.get("/api/admin/fns/hotels")).status_code == 403  # administrators only
    r = await http.post("/api/admin/fns/hotels", headers=as_admin,
                        json={**NEW, "fns_user": "own-user", "fns_password": "own-secret"})
    assert r.status_code == 201, r.text
    hotel = r.json()
    assert (hotel["code"], hotel["currency"], hotel["sync_time"], hotel["fns_user"]) == ("NUE", "COP", "04:30", "own-user")
    assert hotel["has_password"] and "fns_password" not in hotel and "own-secret" not in r.text
    assert hotel["state"] == "queued" and hotel["current"] is None and hotel["history"]["loaded"] == 0
    with owner() as c:
        stored = c.execute("SELECT fns_password FROM pms.fns_hotels WHERE id = %s", (hotel["id"],)).fetchone()[0]
    assert stored.startswith("fernet:") and decrypt(stored, "test-key") == "own-secret"

    # The same alojamiento twice, a code a sample hotel has, a wrong time zone: refused with the reason.
    again = await http.post("/api/admin/fns/hotels", headers=as_admin, json={**NEW, "code": "OTHER"})
    assert again.status_code == 400 and "already being imported" in again.json()["detail"]
    clash = await http.post("/api/admin/fns/hotels", headers=as_admin,
                            json={**NEW, "alojamiento_id": ALOJ + 1, "code": "LIS"})
    assert clash.status_code == 400 and "LIS" in clash.json()["detail"]
    zone = await http.post("/api/admin/fns/hotels", headers=as_admin,
                           json={**NEW, "alojamiento_id": ALOJ + 1, "code": "OK", "timezone": "Mars/Base"})
    assert zone.status_code == 400 and "time zone" in zone.json()["detail"]
    no_password = await http.post("/api/admin/fns/hotels", headers=as_admin,
                                  json={**NEW, "alojamiento_id": ALOJ + 1, "code": "OK", "fns_user": "x"})
    assert no_password.status_code == 400 and "password" in no_password.json()["detail"]

    # Back to the account in .env; paused; then edited.
    r = await http.patch(f"/api/admin/fns/hotels/{hotel['id']}", headers=as_admin,
                         json={"fns_user": "", "enabled": False, "name": "Hotel Nuevo Centro"})
    assert r.status_code == 200, r.text
    assert (r.json()["fns_user"], r.json()["has_password"], r.json()["name"], r.json()["next_at"]) == \
        (None, False, "Hotel Nuevo Centro", None)


@needs_db
@pytest.mark.anyio
async def test_progress_of_a_running_import_and_import_now(site):
    http, as_admin, _ = site
    hotel = (await http.post("/api/admin/fns/hotels", headers=as_admin, json=NEW)).json()
    started = datetime.now().astimezone() - timedelta(minutes=5)
    with owner() as c:  # what the fns-sync service writes while it imports
        hotel_id = c.execute("INSERT INTO pms.hotels (code, name, city, country, star_rating, total_rooms, currency, "
                             "timezone, opened_on, alojamiento_id, pms_id) VALUES ('NUE', 'Hotel Nuevo', '', '', 3, 0, "
                             "'COP', 'America/Bogota', current_date, %s, %s) RETURNING id",
                             (ALOJ, 900_000_000 + ALOJ)).fetchone()[0]
        c.execute("UPDATE pms.fns_hotels SET hotel_id = %s WHERE id = %s", (hotel_id, hotel["id"]))
        c.execute("INSERT INTO pms.fns_sync_runs (hotel_id, started_at, finished_at, status, backfill, calls) "
                  "VALUES (%s, %s, %s, 'partial', true, %s)", (hotel_id, started - timedelta(hours=1), started,
                  json.dumps([{"method": "revenue", "ok": True, "rows": 400},
                              {"method": "pos", "window": "2026-01-01..2026-01-30", "ok": False, "error": "HTTP 500"}])))
        c.execute("INSERT INTO pms.fns_sync_steps (hotel_id, step, history_from) VALUES (%s, 'revenue', '2025-11-01')",
                  (hotel_id,))
        c.execute("INSERT INTO pms.fns_sync_runs (hotel_id, started_at, backfill, progress) VALUES (%s, %s, true, %s)",
                  (hotel_id, started, json.dumps({"step": "reservations", "steps_done": 4, "steps_total": 11,
                                                  "calls": 30, "planned": 80, "rows": 1200, "failed": 0})))
    listed = (await http.get("/api/admin/fns/hotels", headers=as_admin)).json()
    assert listed["default_account"] and listed["can_save_passwords"]
    now = next(h for h in listed["hotels"] if h["id"] == hotel["id"])
    assert now["state"] == "running" and now["current"]["backfill"]
    assert now["current"]["progress"] == {"step": "reservations", "steps_done": 4, "steps_total": 11, "calls": 30,
                                          "planned": 80, "rows": 1200, "failed": 0}
    assert now["history"] == {"loaded": 1, "total": 8, "from": "2025-11-01"}
    assert now["last"]["status"] == "partial" and now["last"]["rows"] == 400
    assert now["last"]["errors"] == ["pos 2026-01-01..2026-01-30: HTTP 500"]

    runs = (await http.get(f"/api/admin/fns/hotels/{hotel['id']}/runs", headers=as_admin)).json()["runs"]
    assert [r["status"] for r in runs] == ["running", "partial"] and runs[1]["failed_calls"] == 1

    with owner() as c:
        c.execute("UPDATE pms.fns_sync_runs SET status = 'ok', finished_at = now() WHERE hotel_id = %s AND "
                  "status = 'running'", (hotel_id,))
    r = await http.post(f"/api/admin/fns/hotels/{hotel['id']}/run", headers=as_admin)
    assert r.status_code == 200 and r.json()["state"] == "queued"
    assert (await http.post("/api/admin/fns/hotels/999999/run", headers=as_admin)).status_code == 404


@needs_db
@pytest.mark.anyio
async def test_checking_the_account_with_fns(site):
    _, _, fns = site
    ok = await fns.verify({"alojamiento_id": ALOJ})  # the account in .env
    assert ok == {"ok": True, "room_types": 2, "message": "FNS answered: 2 room types."}
    wrong_hotel = await fns.verify({"alojamiento_id": ALOJ + 1})
    assert not wrong_hotel["ok"] and "PMS not allowed" in wrong_hotel["message"]
    wrong_password = await fns.verify({"alojamiento_id": ALOJ, "fns_user": "fns-user", "fns_password": "nope"})
    assert not wrong_password["ok"] and "HTTP 403" in wrong_password["message"]
    # A saved hotel's own account, without typing its password again.
    saved = await fns.create({**NEW, "fns_user": "fns-user", "fns_password": "fns-secret"})
    assert (await fns.verify({"alojamiento_id": ALOJ, "fns_user": "fns-user"}, saved["id"]))["ok"]
