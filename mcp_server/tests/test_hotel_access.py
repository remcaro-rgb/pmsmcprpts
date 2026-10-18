"""Per-hotel access: the PMS_HOTEL_ACCESS rules, and the database's row-level security
(db/init/04_hotel_access.sql) through the tools and the private service-token mode."""

import asyncio
import base64
import os
import socket

import httpx2
import psycopg
import pytest
import uvicorn
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from pms_mcp.access import HotelAccess
from pms_mcp.auth import ServiceTokenMiddleware
from pms_mcp.db import Database, QueryError
from pms_mcp.server import build_server

DSN = os.environ.get("PMS_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DSN, reason="PMS_TEST_DATABASE_URL not set")
SERVICE_TOKEN = "t" * 40


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_rules():
    access = HotelAccess.parse("""
        Ann@Hotel.example = lis, OPO
        @lisbon.example = LIS;  * = *
    """)
    assert access.hotels_for("ann@hotel.example") == "LIS,OPO"
    assert access.hotels_for("joe@lisbon.example") == "LIS"
    assert access.hotels_for("someone@else.example") == "*"
    assert access.hotels_for("local") == "*"
    strict = HotelAccess.parse("ann@hotel.example = BCN")
    assert strict.hotels_for("bob@hotel.example") == "" and strict.hotels_for("local") == ""
    assert HotelAccess.parse("").hotels_for("anyone@x.example") == "*"  # not configured: all hotels


@pytest.mark.parametrize("spec, message", [
    ("ann@hotel.example", "expected `who = hotels`"),
    ("ann = LIS", "not an email address"),
    ("ann@x.example = LIS; ann@x.example = BCN", "listed twice"),
    ("ann@x.example = LIS'; --", "invalid hotel codes"),
    ("ann@x.example = ,", "invalid hotel codes"),
])
def test_invalid_rules(spec, message):
    with pytest.raises(ValueError, match=message):
        HotelAccess.parse(spec)


async def call(client, tool, **args):
    result = await client.call_tool(tool, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


@needs_db
@pytest.mark.anyio
async def test_tools_only_see_allowed_hotels():
    async with Client(build_server(DSN, access=HotelAccess.parse("* = LIS"))) as c:
        schema = await call(c, "describe_schema")
        assert [h["code"] for h in schema["hotels"]] == ["LIS"]
        kpis = await call(c, "get_kpis", start="2026-07-01", end="2026-07-31", granularity="month")
        assert {r[0] for r in kpis["rows"]} == {"LIS"}
        bcn = await c.call_tool("get_kpis", {"start": "2026-07-01", "end": "2026-07-31", "hotels": ["BCN"]})
        assert bcn.is_error and "Available: ['LIS']" in bcn.content[0].text
        # Raw SQL too, including tables that reach hotels only through their reservation.
        counts = await call(c, "run_sql", query="""
            SELECT (SELECT count(*) FROM hotels), (SELECT count(DISTINCT hotel_id) FROM reservations),
                   (SELECT count(DISTINCT r.hotel_id) FROM folio_charges fc JOIN folios f ON f.id = fc.folio_id
                      JOIN reservations r ON r.id = f.reservation_id),
                   (SELECT count(*) FROM folio_charges) < (SELECT 400000)""")
        assert counts["rows"][0] == [1, 1, 1, True]

    async with Client(build_server(DSN)) as c:  # no rules: all hotels
        assert len((await call(c, "describe_schema"))["hotels"]) == 3

    async with Client(build_server(DSN, access=HotelAccess.parse("ann@hotel.example = LIS"))) as c:
        r = await c.call_tool("run_sql", {"query": "SELECT 1"})
        assert r.is_error and "no hotels assigned" in r.content[0].text


@needs_db
@pytest.mark.anyio
async def test_queries_cannot_widen_their_access():
    db = Database(DSN)
    assert (await db.query("SELECT count(*) FROM hotels", hotels="BCN")).rows == [[1]]
    assert (await db.query("SELECT count(*) FROM guests", hotels="")).rows == [[0]]
    with pytest.raises(QueryError, match="permission denied for function set_config"):
        await db.query("SELECT pg_catalog.set_config('pms.allowed_hotels', '*', true)", hotels="BCN")
    with pytest.raises(QueryError, match="multiple commands"):
        await db.query("SET LOCAL pms.allowed_hotels = '*'; SELECT count(*) FROM hotels", hotels="BCN")
    # Without the setting (e.g. another client logging in as pms_readonly) no hotel data is visible.
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        assert await (await conn.execute("SELECT count(*) FROM pms.reservations")).fetchone() == (0,)


@pytest.fixture
async def private_server():
    """The HTTP server without public sign-in, private to the website's agent."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    access = HotelAccess.parse("ann@hotel.example = OPO; * = *")
    app = ServiceTokenMiddleware(build_server(DSN, access=access).streamable_http_app(host="127.0.0.1"),
                                 SERVICE_TOKEN)
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(uv.serve())
    while not uv.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    uv.should_exit = True
    await task


def as_user(base: str, bearer: str) -> Client:
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {bearer}"})
    return Client(streamable_http_client(f"{base}/mcp", http_client=http))


@needs_db
@pytest.mark.anyio
async def test_private_server_acts_for_website_users(private_server):
    async with httpx2.AsyncClient() as http:
        r = await http.post(f"{private_server}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401
        r = await http.post(f"{private_server}/mcp", headers={"Authorization": "Bearer " + "x" * 40},
                            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401

    ann = SERVICE_TOKEN + ":" + base64.urlsafe_b64encode(b"ann@hotel.example").decode().rstrip("=")
    async with as_user(private_server, ann) as c:
        assert [h["code"] for h in (await call(c, "describe_schema"))["hotels"]] == ["OPO"]
    async with as_user(private_server, SERVICE_TOKEN) as c:  # the website without sign-in
        assert len((await call(c, "describe_schema"))["hotels"]) == 3
