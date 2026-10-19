"""Hotel access from the user directory (PMS_USER_DIRECTORY=true, db/init/05_users.sh): each
user sees only their assigned hotels, administrators see all, and anyone else sees nothing."""

import asyncio
import base64
import os
import secrets
import socket
from contextlib import contextmanager

import psycopg
import pytest
import uvicorn
from mcp.client import Client

from pms_mcp import auth
from pms_mcp.access import HotelAccess, Scope
from pms_mcp.auth import ServiceTokenMiddleware
from pms_mcp.db import Database
from pms_mcp.server import build_server
from test_hotel_access import SERVICE_TOKEN, as_user

DSN = os.environ.get("PMS_TEST_DATABASE_URL")
ADMIN_URL = os.environ.get("PMS_TEST_ADMIN_URL")
pytestmark = [pytest.mark.anyio, pytest.mark.skipif(not (DSN and ADMIN_URL),
                                                   reason="PMS_TEST_DATABASE_URL / PMS_TEST_ADMIN_URL not set")]
DIRECTORY = HotelAccess(directory=True)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def people():
    """ann (LIS), oscar (LIS and OPO), boss (administrator, no hotels) and gone (LIS, deactivated),
    with random addresses so runs don't collide; removed afterwards."""
    tag = secrets.token_hex(4)
    emails = {k: f"{k}-{tag}@directory.test" for k in ("ann", "oscar", "boss", "gone")}
    dbname = psycopg.conninfo.conninfo_to_dict(DSN)["dbname"]
    owner_dsn = psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=dbname)
    with psycopg.connect(owner_dsn, autocommit=True) as c:
        for key, email in emails.items():
            c.execute("INSERT INTO app.users (name, email, is_admin, active) VALUES (%s, %s, %s, %s)",
                      (key.title(), email, key == "boss", key != "gone"))
        for key, codes in (("ann", ["LIS"]), ("oscar", ["LIS", "OPO"]), ("gone", ["LIS"])):
            c.execute("INSERT INTO app.user_hotels SELECT u.id, h.id FROM app.users u, pms.hotels h "
                      "WHERE u.email = %s AND h.code = ANY(%s)", (emails[key], codes))
        try:
            yield emails
        finally:
            c.execute("DELETE FROM app.users WHERE email = ANY(%s)", (list(emails.values()),))


@contextmanager
def acting_as(email: str):
    """In-process tool calls act as the local identity (what PMS_LOCAL_USER sets for stdio)."""
    auth.set_local_identity(email)
    try:
        yield
    finally:
        auth.set_local_identity("")


async def call(client, tool, **args):
    result = await client.call_tool(tool, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


def test_settings():
    assert HotelAccess.from_env({"PMS_USER_DIRECTORY": "true"}).directory
    assert not HotelAccess.from_env({}).directory
    assert DIRECTORY.scope(" Ann@Hotel.Example ") == Scope("ann@hotel.example", "")
    with pytest.raises(ValueError, match="not both"):
        HotelAccess.from_env({"PMS_USER_DIRECTORY": "true", "PMS_HOTEL_ACCESS": "* = LIS"})


async def test_each_user_sees_only_their_hotels(people):
    async with Client(build_server(DSN, access=DIRECTORY)) as c:
        for who, expected in (("ann", ["LIS"]), ("oscar", ["LIS", "OPO"]), ("boss", ["LIS", "BCN", "OPO"])):
            with acting_as(people[who]):
                hotels = [h["code"] for h in (await call(c, "describe_schema"))["hotels"]]
                assert hotels == expected, who
                kpis = await call(c, "get_kpis", start="2026-07-01", end="2026-07-31", granularity="month")
                assert sorted({r[0] for r in kpis["rows"]}) == sorted(expected), who
                counts = await call(c, "run_sql", query="""
                    SELECT (SELECT count(DISTINCT hotel_id) FROM reservations),
                           (SELECT count(DISTINCT r.hotel_id) FROM payments p JOIN folios f ON f.id = p.folio_id
                              JOIN reservations r ON r.id = f.reservation_id),
                           (SELECT count(DISTINCT hotel_code) FROM v_daily_kpis)""")
                assert counts["rows"][0] == [len(expected)] * 3, who

        # Asking for another hotel by name doesn't help.
        with acting_as(people["ann"]):
            bcn = await c.call_tool("get_kpis", {"start": "2026-07-01", "end": "2026-07-31", "hotels": ["BCN"]})
            assert bcn.is_error and "Available: ['LIS']" in bcn.content[0].text
            r = await call(c, "run_sql", query="SELECT count(*) FROM reservations r JOIN hotels h "
                                               "ON h.id = r.hotel_id WHERE h.code = 'BCN'")
            assert r["rows"] == [[0]]


async def test_everyone_else_sees_nothing(people):
    async with Client(build_server(DSN, access=DIRECTORY)) as c:
        for who in (people["gone"], "stranger@directory.test", "website", ""):  # "" = plain local use
            with acting_as(who):
                r = await c.call_tool("describe_schema", {})
                assert r.is_error and "no hotels assigned" in r.content[0].text, who
                rows = await call(c, "run_sql", query="SELECT (SELECT count(*) FROM hotels), "
                                                      "(SELECT count(*) FROM guests), (SELECT count(*) FROM payments)")
                assert rows["rows"] == [[0, 0, 0]], who


async def test_the_database_decides(people):
    db = Database(DSN)
    # A directory user's assignments win over the older pms.allowed_hotels setting...
    ann = await db.query("SELECT string_agg(code, ',') FROM hotels", hotels="*", user=people["ann"])
    assert ann.rows == [["LIS"]]
    # ...and the queries the model writes can't read the directory.
    with pytest.raises(Exception, match="permission denied"):
        await db.query("SELECT email FROM app.users", hotels="*", user=people["boss"])


async def test_website_users_through_the_service_token(people):
    """The website's agent passes the signed-in user after the service token."""
    server = build_server(DSN, access=DIRECTORY)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = ServiceTokenMiddleware(server.streamable_http_app(host="127.0.0.1"), SERVICE_TOKEN)
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(uv.serve())
    while not uv.started:
        await asyncio.sleep(0.05)
    try:
        base = f"http://127.0.0.1:{port}"
        oscar = SERVICE_TOKEN + ":" + base64.urlsafe_b64encode(people["oscar"].encode()).decode().rstrip("=")
        async with as_user(base, oscar) as c:
            assert [h["code"] for h in (await call(c, "describe_schema"))["hotels"]] == ["LIS", "OPO"]
        async with as_user(base, SERVICE_TOKEN) as c:  # the website without a signed-in user
            assert (await c.call_tool("describe_schema", {})).is_error
    finally:
        uv.should_exit = True
        await task
