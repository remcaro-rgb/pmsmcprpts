"""MCP server exposing the sample hotel PMS database as read-only tools."""

import json
from datetime import date
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, TextContent, ToolAnnotations

from .datasets import Dataset, DatasetStore
from .db import Database, QueryError
from .sql_guard import UnsafeQueryError, check_read_only

INSTRUCTIONS = """\
Read-only access to a hotel property-management-system (PMS) database (PostgreSQL, schema `pms`).
- Call describe_schema first to see tables, views, column meanings, hotels and the business date.
- Use get_kpis for occupancy, ADR, RevPAR and revenue over time; use run_sql for anything else,
  preferring the v_* reporting views over re-deriving metrics from base tables.
- Money is in EUR, net of tax. Stay dates before the business date are actuals; later dates are
  on-the-books (future) bookings.
- For ratios over a period (occupancy, ADR, RevPAR) sum numerators and denominators;
  never average daily ratios.
- Results are stored under a dataset_id; page through them with get_dataset.
- Tell the user which hotels and date range an answer covers."""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

SCHEMA_SQL = """
SELECT c.relname AS name,
       CASE c.relkind WHEN 'v' THEN 'view' ELSE 'table' END AS kind,
       obj_description(c.oid, 'pg_class') AS comment,
       array_agg(a.attname || ' ' || format_type(a.atttypid, a.atttypmod)
                 || coalesce(' -- ' || col_description(c.oid, a.attnum), '') ORDER BY a.attnum) AS columns
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'pms'
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE c.relkind IN ('r', 'v')
GROUP BY c.oid, c.relname, c.relkind
ORDER BY c.relkind DESC, c.relname
"""

KPI_GRANULARITIES = ("day", "week", "month", "quarter", "year")
MAX_STORED_ROWS = 50_000
MAX_PREVIEW_ROWS = 1000


def _ok(payload: dict[str, Any]) -> CallToolResult:
    """Structured result plus compact JSON text (the default text rendering is indented,
    which roughly doubles the tokens a model spends reading tables)."""
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=payload)


def _result(ds: Dataset, preview_rows: int, **extra: Any) -> CallToolResult:
    preview_rows = max(0, min(preview_rows, MAX_PREVIEW_ROWS))
    return _ok({
        "dataset_id": ds.id,
        "columns": ds.columns,
        "row_count": len(ds.rows),
        "truncated": ds.truncated,
        "rows": ds.page(0, preview_rows),
        "rows_shown": min(preview_rows, len(ds.rows)),
        **extra,
    })


def build_server(dsn: str, statement_timeout_ms: int = 15000) -> MCPServer:
    db = Database(dsn, statement_timeout_ms)
    store = DatasetStore()
    mcp = MCPServer("pms-reports", instructions=INSTRUCTIONS)
    schema_cache: dict[str, Any] = {}

    async def load_schema() -> dict[str, Any]:
        if not schema_cache:
            settings = await db.query(
                "SELECT business_date, data_start, (SELECT max(stay_date) FROM pms.reservation_nights) "
                "FROM pms.system_settings")
            hotels = await db.query(
                "SELECT code, name, city, country, star_rating, total_rooms, currency "
                "FROM pms.hotels ORDER BY id")
            relations = await db.query(SCHEMA_SQL)
            business_date, data_start, data_end = settings.rows[0]
            schema_cache.update({
                "business_date": business_date,
                "data_start": data_start,
                "data_end": data_end,
                "hotels": [dict(zip([c["name"] for c in hotels.columns], r)) for r in hotels.rows],
                "relations": [
                    {"name": name, "kind": kind, "comment": comment, "columns": columns}
                    for name, kind, comment, columns in relations.rows
                ],
            })
        return schema_cache

    async def run(query, params, source) -> Dataset:
        try:
            res = await db.query(query, params, max_rows=MAX_STORED_ROWS)
        except QueryError as e:
            raise ToolError(str(e)) from e
        return store.put(res.columns, res.rows, res.truncated, source)

    @mcp.tool(annotations=READ_ONLY)
    async def describe_schema(table: str | None = None) -> CallToolResult:
        """Describe the PMS database: business date, data range, hotels, and every table and
        reporting view (schema `pms`) with column types and meanings.

        Args:
            table: Optional table or view name to describe only that relation.
        """
        schema = await load_schema()
        if table is None:
            return _ok(schema)
        matches = [r for r in schema["relations"] if r["name"] == table.removeprefix("pms.")]
        if not matches:
            names = ", ".join(r["name"] for r in schema["relations"])
            raise ToolError(f"Unknown table or view {table!r}. Available: {names}")
        return _ok({**{k: v for k, v in schema.items() if k != "relations"}, "relations": matches})

    @mcp.tool(annotations=READ_ONLY)
    async def run_sql(query: str, preview_rows: int = 100) -> CallToolResult:
        """Run one read-only PostgreSQL SELECT (WITH ... SELECT allowed) against schema `pms`
        and store the full result (up to 50,000 rows) as a dataset.

        Returns the dataset_id, column names and types, total row count and the first
        `preview_rows` rows (max 1000). Queries time out after 15 seconds; aggregate in SQL
        rather than pulling raw rows.

        Args:
            query: A single SELECT statement. Tables can be referenced without the `pms.` prefix.
            preview_rows: How many rows to return inline.
        """
        try:
            check_read_only(query)
        except UnsafeQueryError as e:
            raise ToolError(str(e)) from e
        ds = await run(query, None, query)
        return _result(ds, preview_rows)

    @mcp.tool(annotations=READ_ONLY)
    async def get_kpis(
        start: date,
        end: date,
        hotels: list[str] | None = None,
        granularity: Literal["day", "week", "month", "quarter", "year"] = "month",
        by_hotel: bool = True,
        preview_rows: int = 200,
    ) -> CallToolResult:
        """Hotel KPIs per period from v_daily_kpis, aggregated correctly: rooms available and
        sold, occupancy (0-1), ADR, RevPAR, and room, F&B, spa, other and total revenue (EUR,
        net of tax). Periods on or after the business date contain on-the-books business
        (`fully_actual` is false).

        Args:
            start: First stay date (inclusive), YYYY-MM-DD.
            end: Last stay date (inclusive), YYYY-MM-DD.
            hotels: Hotel codes such as ["LIS", "BCN"]; omit for all hotels.
            granularity: Period size.
            by_hotel: One row per hotel and period; false combines the selected hotels.
            preview_rows: How many rows to return inline (max 1000).
        """
        if end < start:
            raise ToolError("end must be on or after start.")
        schema = await load_schema()
        if hotels:
            hotels = [h.upper() for h in hotels]
            known = {h["code"] for h in schema["hotels"]}
            unknown = sorted(set(hotels) - known)
            if unknown:
                raise ToolError(f"Unknown hotel codes {unknown}. Available: {sorted(known)}")
        hotel_col = "hotel_code" if by_hotel else "'ALL'::text"
        hotel_filter = "AND hotel_code = ANY(%(hotels)s)" if hotels else ""
        query = f"""
            SELECT {hotel_col} AS hotel_code,
                   date_trunc(%(granularity)s, stay_date)::date AS period,
                   sum(rooms_available)::bigint AS rooms_available,
                   sum(rooms_sold)::bigint AS rooms_sold,
                   round(sum(rooms_sold)::numeric / nullif(sum(rooms_available), 0), 4) AS occupancy,
                   round(sum(room_revenue) / nullif(sum(rooms_sold), 0), 2) AS adr,
                   round(sum(room_revenue) / nullif(sum(rooms_available), 0), 2) AS revpar,
                   sum(room_revenue) AS room_revenue,
                   sum(fnb_revenue) AS fnb_revenue,
                   sum(spa_revenue) AS spa_revenue,
                   sum(other_revenue) AS other_revenue,
                   sum(total_revenue) AS total_revenue,
                   bool_and(is_actual) AS fully_actual
            FROM pms.v_daily_kpis
            WHERE stay_date BETWEEN %(start)s AND %(end)s {hotel_filter}
            GROUP BY 1, 2
            ORDER BY 2, 1"""
        params = {"granularity": granularity, "start": start, "end": end, "hotels": hotels}
        source = f"get_kpis({json.dumps({k: str(v) for k, v in params.items()})}, by_hotel={by_hotel})"
        ds = await run(query, params, source)
        return _result(ds, preview_rows, business_date=schema["business_date"])

    @mcp.tool(annotations=READ_ONLY)
    async def get_dataset(dataset_id: str, offset: int = 0, limit: int = 100) -> CallToolResult:
        """Page through a stored dataset from run_sql or get_kpis.

        Args:
            dataset_id: Id returned by run_sql or get_kpis.
            offset: First row to return (0-based).
            limit: Number of rows to return (max 1000).
        """
        try:
            ds = store.get(dataset_id)
        except KeyError:
            raise ToolError(f"Unknown or expired dataset_id {dataset_id!r}.") from None
        offset = max(0, offset)
        return _ok({
            "dataset_id": ds.id,
            "columns": ds.columns,
            "row_count": len(ds.rows),
            "offset": offset,
            "rows": ds.page(offset, max(0, min(limit, MAX_PREVIEW_ROWS))),
            "source": ds.source,
        })

    @mcp.resource("pms://schema", name="schema", mime_type="application/json",
                  description="Tables, views, hotels and business date of the PMS database.")
    async def schema_resource() -> str:
        return json.dumps(await load_schema(), indent=1)

    return mcp
