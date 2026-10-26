"""Integration tests: call the tools through an in-process MCP client.

Needs a seeded database (see db/seed.py), ideally as the read-only role:
    PMS_TEST_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms pytest mcp_server/tests
"""

import os

import pytest
from mcp.client import Client

from pms_mcp.server import build_server

DSN = os.environ.get("PMS_TEST_DATABASE_URL")
pytestmark = [pytest.mark.anyio, pytest.mark.skipif(not DSN, reason="PMS_TEST_DATABASE_URL not set")]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with Client(build_server(DSN)) as c:
        yield c


async def call(client, tool, **args):
    result = await client.call_tool(tool, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def call_error(client, tool, **args) -> str:
    result = await client.call_tool(tool, args)
    assert result.is_error
    return result.content[0].text


async def test_lists_read_only_tools(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    read_only = {"describe_schema", "run_sql", "get_kpis", "get_dataset", "get_overview"}
    creates_files = {"make_chart", "make_spreadsheet", "make_presentation", "make_report"}
    assert set(tools) == read_only | creates_files
    assert all(tools[n].annotations.read_only_hint for n in read_only)
    assert not any(tools[n].annotations.read_only_hint or tools[n].annotations.destructive_hint
                   for n in creates_files)


async def test_overview(client):
    hotels = {h["hotel_code"]: h for h in (await call(client, "get_overview"))["hotels"]}
    assert set(hotels) == {"LIS", "BCN", "OPO"}
    lis = hotels["LIS"]
    schema = await call(client, "describe_schema")
    assert lis["today"] == str(schema["business_date"]) and lis["currency"] == "EUR"
    assert 0 < lis["occupancy_today"] <= 1 and lis["arrivals_today"] > 0
    assert lis["adr_period"] > 0 and lis["revenue_period"] > 0 and lis["occupancy_next_30"] > 0
    assert lis["period"]["key"] == "mtd" and isinstance(lis["alerts"], list)
    assert len(lis["series"]["occupancy"]) == 14 and len(lis["series"]["occupancy_next_30"]) == 30
    # The month-to-date revenue matches get_kpis for the same days.
    kpis = await call(client, "get_kpis", start=lis["period"]["start"], end=lis["period"]["end"],
                      hotels=["LIS"], granularity="year")
    assert abs(float(kpis["rows"][0][7]) - lis["revenue_period"]) < 0.01
    # This year so far, against the same days of last year.
    ytd = (await call(client, "get_overview", hotel="LIS", period="ytd"))["hotels"][0]
    assert ytd["period"]["start"].endswith("-01-01") and ytd["revenue_period"] > lis["revenue_period"]
    assert ytd["revenue_period_change"] is not None
    one = await call(client, "get_overview", hotel="opo")
    assert [h["hotel_code"] for h in one["hotels"]] == ["OPO"]
    assert "Unknown hotel" in await call_error(client, "get_overview", hotel="XXX")


async def test_describe_schema(client):
    schema = await call(client, "describe_schema")
    names = {r["name"] for r in schema["relations"]}
    assert {"reservations", "v_daily_kpis", "v_pickup", "v_channel_mix", "v_guest_stays"} <= names
    assert {h["code"] for h in schema["hotels"]} == {"LIS", "BCN", "OPO"}
    assert schema["business_date"]

    one = await call(client, "describe_schema", table="pms.v_daily_kpis")
    assert [r["name"] for r in one["relations"]] == ["v_daily_kpis"]
    assert any(c.startswith("occupancy ") for c in one["relations"][0]["columns"])
    assert "Unknown table" in await call_error(client, "describe_schema", table="nope")


async def test_run_sql_and_paging(client):
    res = await call(client, "run_sql", query="SELECT id, code FROM hotels ORDER BY id", preview_rows=2)
    assert res["row_count"] == 3 and res["rows_shown"] == 2
    assert [c["name"] for c in res["columns"]] == ["id", "code"]
    page = await call(client, "get_dataset", dataset_id=res["dataset_id"], offset=2, limit=10)
    assert page["rows"] == [[3, "OPO"]]
    assert "Unknown or expired" in await call_error(client, "get_dataset", dataset_id="ds_missing")


async def test_run_sql_errors_are_actionable(client):
    assert "Only SELECT" in await call_error(client, "run_sql", query="DELETE FROM hotels")
    assert 'column "nope" does not exist' in await call_error(client, "run_sql", query="SELECT nope FROM hotels")


async def test_get_kpis_matches_daily_view(client):
    kpis = await call(client, "get_kpis", start="2025-07-01", end="2025-07-31", hotels=["lis"])
    cols = [c["name"] for c in kpis["columns"]]
    (row,) = kpis["rows"]
    row = dict(zip(cols, row))
    check = await call(client, "run_sql", query="""
        SELECT sum(rooms_sold)::numeric / sum(rooms_available), sum(room_revenue) / sum(rooms_sold)
        FROM v_daily_kpis WHERE hotel_code = 'LIS' AND stay_date BETWEEN '2025-07-01' AND '2025-07-31'""")
    occ, adr = check["rows"][0]
    assert row["hotel_code"] == "LIS" and row["period"] == "2025-07-01"
    assert row["occupancy"] == pytest.approx(occ, abs=1e-4)
    assert row["adr"] == pytest.approx(adr, abs=0.01)
    assert row["fully_actual"] is True


async def test_get_kpis_combined_and_validation(client):
    kpis = await call(client, "get_kpis", start="2025-01-01", end="2025-12-31", granularity="quarter",
                      by_hotel=False)
    assert [r[0] for r in kpis["rows"]] == ["ALL"] * 4
    assert "Unknown hotel codes" in await call_error(client, "get_kpis", start="2025-01-01",
                                                     end="2025-01-31", hotels=["XXX"])
    assert "end must be" in await call_error(client, "get_kpis", start="2025-02-01", end="2025-01-01")
