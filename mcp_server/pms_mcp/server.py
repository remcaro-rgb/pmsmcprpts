"""MCP server exposing the sample hotel PMS database as read-only tools."""

import base64
import json
import os
import tempfile
import time
from datetime import date
from typing import Any, Literal
from urllib.parse import quote

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ContentBlock, ImageContent, TextContent, ToolAnnotations
from starlette.requests import Request
from starlette.responses import Response

from .access import HotelAccess, Scope
from .artifacts import ArtifactStore, FileInfo
from .auth import SCOPE, AuthConfig, OIDCAuthProvider, current_user
from .charts import CHART_TYPES, ChartError, build_chart, build_custom, chart_payload, render_png
from .datasets import Dataset, DatasetStore
from .db import Database, QueryError
from .documents import DocError, Section, SheetSpec, Slide, build_docx, build_pdf, build_pptx, build_xlsx
from .formats import KINDS
from .overview import DAILY, MOVES, MOVES_FNS, build as build_overview
from .sql_guard import UnsafeQueryError, check_read_only

INSTRUCTIONS = """\
Read-only access to a hotel property-management-system (PMS) database (PostgreSQL, schema `pms`).
- Call describe_schema first to see tables, views, column meanings, hotels and the business date.
- Use get_kpis for occupancy, ADR, RevPAR and revenue over time; use run_sql for anything else,
  preferring the v_* reporting views over re-deriving metrics from base tables.
- Money is in each hotel's currency (hotels.currency), net of tax. Stay dates before the business
  date are actuals; later dates are on-the-books (future) bookings.
- Hotels with `fns_data_as_of` set (e.g. Fragata) are imported daily from the FNSrooms PMS into the
  fns_* tables; the sample tables (reservations, guests, folios...) have no rows for them. For them,
  "today" is the calendar date in the hotel's time zone, and their KPIs are in get_kpis too.
- For ratios over a period (occupancy, ADR, RevPAR) sum numerators and denominators;
  never average daily ratios.
- Results are stored under a dataset_id; page through them with get_dataset.
- Documents: make_chart, make_spreadsheet, make_presentation and make_report take dataset_ids
  (and chart_ids from make_chart) and read every number from the stored data. Query exactly the
  rows and columns a document needs first. make_chart also returns the chart as an image.
- When a result includes a download_url and your app doesn't show files itself, give the user that
  link (it works for 24 hours).
- Tell the user which hotels and date range an answer covers."""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
CREATES_FILE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                               open_world_hint=False)

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
SCHEMA_TTL_SECONDS = 600


def _ok(payload: dict[str, Any], for_model: dict[str, Any] | None = None,
        extra_content: list[ContentBlock] | None = None) -> CallToolResult:
    """Structured result plus compact JSON text (the default text rendering is indented,
    which roughly doubles the tokens a model spends reading tables). `for_model` replaces
    the text when the structured payload carries UI-only data (e.g. a chart's spec and data)."""
    text = json.dumps(for_model or payload, separators=(",", ":"), ensure_ascii=False, default=str)
    return CallToolResult(content=[TextContent(type="text", text=text), *(extra_content or [])],
                          structured_content=payload)


def _file(info: FileInfo) -> dict[str, Any]:
    return {"file_id": info.file_id, "filename": info.filename, "mime": info.mime, "size": info.size}


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


def build_server(dsn: str, statement_timeout_ms: int = 15000, artifacts_dir: str | None = None,
                 auth: AuthConfig | None = None, oidc_http_client=None,
                 access: HotelAccess | None = None) -> MCPServer:
    """With `auth`, remote users sign in through the configured OIDC provider (HTTP transport),
    each user's datasets and charts are private, and files get signed download links."""
    db = Database(dsn, statement_timeout_ms)
    store = DatasetStore(max_datasets=1000)
    artifacts = ArtifactStore(artifacts_dir or os.environ.get("PMS_ARTIFACTS_DIR")
                              or os.path.join(tempfile.gettempdir(), "pms-artifacts"))
    charts: dict[str, tuple[str, bytes]] = {}  # chart_id -> (owner, PNG), for embedding in documents
    provider = OIDCAuthProvider(auth, oidc_http_client) if auth else None
    if provider:
        mcp = MCPServer(
            "pms-reports", instructions=INSTRUCTIONS, auth_server_provider=provider,
            auth=AuthSettings(
                issuer_url=auth.public_url,
                resource_server_url=f"{auth.public_url}/mcp",
                validate_token_resource=False,  # tokens are opaque and only issued for this server
                client_registration_options=ClientRegistrationOptions(
                    enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
                revocation_options=RevocationOptions(enabled=True),
                required_scopes=[SCOPE],
            ))
    else:
        mcp = MCPServer("pms-reports", instructions=INSTRUCTIONS)
    access = access or HotelAccess.from_env(os.environ)
    schema_cache: dict[str, Any] = {}  # the same for everyone: dates and relations, not hotels
    schema_read_at = [0.0]  # re-read now and then: the business date and the tables can change

    def my_scope() -> Scope:
        scope = access.scope(current_user())
        if not access.directory and not scope.hotels:
            raise ToolError("Your account has no hotels assigned. Ask the administrator to add you "
                            "to PMS_HOTEL_ACCESS.")
        return scope

    def my_store():
        return store.scoped(current_user())

    def my_charts() -> dict[str, bytes]:
        user = current_user()
        return {cid: png for cid, (owner, png) in charts.items() if owner == user}

    def file_ref(info: FileInfo) -> dict[str, Any]:
        ref = _file(info)
        if provider:  # remote clients (e.g. Claude apps) download through a signed link
            ref["download_url"] = provider.download_url(info.file_id)
        return ref

    async def load_schema(with_hotels: bool = True) -> dict[str, Any]:
        """Business date, data range, the caller's hotels, and the tables and views."""
        scope = my_scope()
        try:
            if not schema_cache or time.monotonic() - schema_read_at[0] > SCHEMA_TTL_SECONDS:
                schema_cache.update(await _read_schema())
                schema_read_at[0] = time.monotonic()
            if not with_hotels:
                return schema_cache
            fns_as_of = ("(SELECT max(f.fetched_at) FROM pms.fns_revenue_daily f WHERE f.hotel_id = h.id)"
                         if schema_cache["fns"] else "NULL::timestamptz")
            rows = await db.query(
                "SELECT code, name, city, country, star_rating, total_rooms, currency, timezone, alojamiento_id, "
                f"pms_id, {fns_as_of} AS fns_data_as_of FROM pms.hotels h ORDER BY id",
                hotels=scope.hotels, user=scope.user)
        except QueryError as e:
            raise ToolError(str(e)) from e
        visible = [dict(zip([c["name"] for c in rows.columns], r)) for r in rows.rows]
        if not visible:
            raise ToolError("Your account has no hotels assigned, or isn't active. Ask an administrator "
                            "to assign you hotels.")
        shared = {k: v for k, v in schema_cache.items() if k not in ("relations", "fns")}
        return {**shared, "hotels": visible, "relations": schema_cache["relations"]}

    async def _read_schema() -> dict[str, Any]:
        # Shared by every caller: dates and catalog only, read across all hotels.
        settings = await db.query(
            "SELECT business_date, data_start, (SELECT max(stay_date) FROM pms.reservation_nights) "
            "FROM pms.system_settings", hotels="*")
        relations = await db.query(SCHEMA_SQL, hotels="*")
        business_date, data_start, data_end = settings.rows[0]
        return {
            # The FNSrooms import's tables (db/init/06_fns.sql) exist.
            "fns": any(name == "fns_revenue_daily" for name, *_ in relations.rows),
            "business_date": business_date,
            "data_start": data_start,
            "data_end": data_end,
            "relations": [
                {"name": name, "kind": kind, "comment": comment, "columns": columns}
                for name, kind, comment, columns in relations.rows
            ],
        }

    async def run(query, params, source) -> Dataset:
        try:
            scope = my_scope()
            res = await db.query(query, params, max_rows=MAX_STORED_ROWS,
                                 hotels=scope.hotels, user=scope.user)
        except QueryError as e:
            raise ToolError(str(e)) from e
        return my_store().put(res.columns, res.rows, res.truncated, source)

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
        sold, occupancy (0-1), ADR, RevPAR, and room, F&B, spa, other and total revenue (each
        hotel's currency, net of tax). Periods on or after the business date contain on-the-books
        business (`fully_actual` is false). Hotels imported from FNSrooms have room revenue only
        (F&B, spa, other and total are null: use fns_production_cc). Don't combine hotels with
        different currencies (by_hotel=false).

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
                   round(sum(rooms_sold)::numeric / nullif(sum(rooms_available), 0), 6) AS occupancy,
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
            ds = my_store().get(dataset_id)
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

    @mcp.tool(annotations=READ_ONLY)
    async def get_overview(hotel: str | None = None) -> CallToolResult:
        """Today's key figures per hotel, as on the website's home screen: occupancy today,
        arrivals and departures today, ADR, RevPAR and room revenue this month so far, and
        occupancy and room revenue on the books for the next 30 days. Changes compare with the
        same days a year earlier (occupancy in points, the others relative: 0.08 = +8%).
        "Today" is each hotel's first date that isn't an actual yet.

        Args:
            hotel: A hotel code such as "FRA"; omit for every hotel you can see.
        """
        schema = await load_schema()
        hotels = {h["code"]: h for h in schema["hotels"]}
        if hotel and hotel.upper() not in hotels:
            raise ToolError(f"Unknown hotel code {hotel!r}. Available: {sorted(hotels)}")
        scope = my_scope()
        where = "WHERE hotel_code = %(hotel)s" if hotel else ""
        try:
            daily = await db.query(DAILY.format(where=where), {"hotel": hotel.upper() if hotel else None},
                                   hotels=scope.hotels, user=scope.user)
            codes = sorted({r[0] for r in daily.rows})
            days = [next(r[1] for r in daily.rows if r[0] == c) for c in codes]
            moves: dict[str, tuple[int, int]] = {}
            for sql in [MOVES] + ([MOVES_FNS] if schema_cache.get("fns") else []):
                res = await db.query(sql, {"codes": codes, "days": days}, hotels=scope.hotels, user=scope.user)
                for code, arrivals, departures in res.rows:
                    a, d = moves.get(code, (0, 0))
                    moves[code] = (a + arrivals, d + departures)
        except QueryError as e:
            raise ToolError(str(e)) from e
        figures = build_overview(daily.rows, {c: moves.get(c, (0, 0)) for c in codes})
        out = []
        for code, h in hotels.items():
            if code in figures:
                out.append({"hotel_code": code, "name": h["name"], "currency": h["currency"].strip(),
                            "data_as_of": h.get("fns_data_as_of"), **figures[code]})
        return _ok({"hotels": out})

    def doc_error(e: Exception) -> ToolError:
        return ToolError(str(e))

    @mcp.tool(annotations=CREATES_FILE)
    async def make_chart(
        dataset_id: str,
        title: str,
        chart_type: Literal[CHART_TYPES] = "line",
        x: str | None = None,
        y: str | None = None,
        series: str | None = None,
        subtitle: str | None = None,
        trend: Literal["linear", "moving_average"] | None = None,
        trend_window: int = 3,
        y2: str | None = None,
        y2_type: Literal["line", "bar"] = "line",
        y_format: Literal[KINDS] | None = None,
        y2_format: Literal[KINDS] | None = None,
        currency: str = "EUR",
        spec: dict[str, Any] | None = None,
        language: Literal["en", "es"] = "en",
    ) -> CallToolResult:
        """Chart a stored dataset. The chart is shown to the user in the chat (interactive, with
        tooltips) and saved as a PNG; pass the returned chart_id to make_presentation or
        make_report to embed it. Every value comes from the dataset.

        Pick a chart_type with x, y and series:
        - line (trends over time), area, stacked_area (parts of a total over time)
        - bar (compare periods or categories; with series: grouped bars), stacked_bar,
          horizontal_bar (ranking categories with long names)
        - scatter (two measures: x and y numeric), pie / donut (shares: x = category, y = value;
          at most ~6 slices), heatmap (x = columns, series = rows, y = value as color),
          histogram (distribution of numeric x), boxplot (distribution of y per x category)
        Add trend="linear" or "moving_average" (trend_window periods) for a dashed trend line on
        line, bar, area or scatter charts. Add y2 for a second measure on its own right-hand axis
        (e.g. bars of revenue with a line of occupancy; y2_type "line" or "bar").

        For anything else (layers, reference lines, annotations, small multiples, waterfalls,
        custom transforms) pass `spec`: a Vega-Lite v6 specification WITHOUT data (no "data",
        "datasets" or URLs); the dataset's rows are its data and fields are its column names.
        Date columns are ISO dates: use "type": "temporal" (timeUnit "yearmonth" for months).
        With spec, chart_type/x/y/series/trend/y2 are ignored.

        Args:
            dataset_id: From run_sql or get_kpis. Rows should be ordered by x.
            title: Chart title, e.g. "Occupancy by hotel".
            chart_type: One of the types above.
            x: Column for the x-axis (dates or categories; the categories of a pie).
            y: Numeric column to plot (not needed for histogram).
            series: Column whose values become separate colors (lines, bars, slices of a stack).
            subtitle: Period and scope, e.g. "Monthly, Oct 2025 - Sep 2026".
            trend: Dashed trend line: "linear" (least squares) or "moving_average".
            trend_window: Periods in the moving average.
            y2: Second numeric column, drawn on a right-hand axis.
            y2_type: "line" or "bar" for y2.
            y_format, y2_format: Override the value format inferred from the column name.
            currency: ISO code of the amounts (the hotel's hotels.currency), e.g. EUR or COP.
            spec: A Vega-Lite spec for charts the types above don't cover.
            language: Language of the dates and labels the tool adds: "en", or "es" for Latin
                American Spanish. Write titles in the same language.
        """
        try:
            ds = _get(dataset_id)
            if spec:
                chart = build_custom(ds, spec, title, subtitle, language, currency)
            else:
                chart = build_chart(ds, chart_type, title, x, y, series, subtitle, y_format, language, currency,
                                    trend, trend_window, y2, y2_type, y2_format)
            png = render_png(chart)
        except ChartError as e:
            raise doc_error(e) from e
        info = artifacts.save(png, title, "png")
        charts[info.file_id] = (current_user(), png)
        summary = {
            "chart_id": info.file_id,
            "file": file_ref(info),
            "type": "custom" if spec else chart_type,
            "rows": len(chart.rows),
            "series": chart.series,
            "note": "The chart image is attached and shown to the user.",
        }
        # A 1x image for clients that display tool images (e.g. Claude apps) and for the model to
        # check its work; the website draws the interactive chart from the payload instead.
        image = ImageContent(type="image", data=base64.b64encode(render_png(chart, scale=1)).decode(),
                             mime_type="image/png")
        return _ok({**summary, "chart": chart_payload(chart)}, for_model=summary, extra_content=[image])

    @mcp.tool(annotations=CREATES_FILE)
    async def make_spreadsheet(title: str, sheets: list[SheetSpec], filename: str | None = None,
                               currency: str = "EUR", language: Literal["en", "es"] = "en") -> CallToolResult:
        """Create an Excel workbook with one sheet per dataset: formatted header, number formats
        (percent, money, integers, dates) inferred from column names, frozen header row, filters,
        plus an About sheet listing each sheet's source query. All rows of each dataset are
        included. The file is offered to the user for download.

        Args:
            title: Workbook title (also the default file name).
            sheets: One entry per sheet.
            filename: Optional file name without extension.
            currency: ISO code of the amounts (the hotel's hotels.currency, listed per hotel by
                describe_schema), e.g. EUR or COP. Money shows as €1,234, $1,234, £1,234, or the
                code for other currencies (COP 1,234,000).
            language: Language of the text the tool adds (dates, column headers, source line):
                "en", or "es" for Latin American Spanish. Write titles and text in the same language.
        """
        schema = await load_schema(with_hotels=False)
        try:
            data = build_xlsx(my_store(), title, sheets, schema["business_date"], language, currency)
        except DocError as e:
            raise doc_error(e) from e
        info = artifacts.save(data, filename or title, "xlsx")
        return _ok({"file": file_ref(info), "sheets": len(sheets)})

    @mcp.tool(annotations=CREATES_FILE)
    async def make_presentation(title: str, slides: list[Slide], subtitle: str | None = None,
                                filename: str | None = None, currency: str = "EUR",
                                language: Literal["en", "es"] = "en") -> CallToolResult:
        """Create a 16:9 PowerPoint deck: a title slide, then one slide per entry. Slide kinds:
        kpis (1-4 headline tiles, values read from datasets), chart (a chart_id from make_chart,
        optionally with 2-4 takeaway bullets beside it), table (up to 14 rows from a dataset),
        bullets (2-6 short points: findings, recommendations). Every slide gets a source footer.
        Write titles that state the takeaway ("Lisbon led occupancy in Q3"), not just the topic.

        Args:
            title: Deck title.
            slides: Content slides in order (max 25).
            subtitle: E.g. period and scope.
            filename: Optional file name without extension.
            currency: ISO code of the amounts (the hotel's hotels.currency, listed per hotel by
                describe_schema), e.g. EUR or COP. Money shows as €1,234, $1,234, £1,234, or the
                code for other currencies (COP 1,234,000).
            language: Language of the text the tool adds (dates, column headers, source line):
                "en", or "es" for Latin American Spanish. Write titles and text in the same language.
        """
        schema = await load_schema(with_hotels=False)
        try:
            data = build_pptx(my_store(), my_charts(), title, subtitle, slides, schema["business_date"], language,
                              currency)
        except DocError as e:
            raise doc_error(e) from e
        info = artifacts.save(data, filename or title, "pptx")
        return _ok({"file": file_ref(info), "slides": len(slides) + 1})

    @mcp.tool(annotations=CREATES_FILE)
    async def make_report(title: str, sections: list[Section], format: Literal["pdf", "docx"] = "pdf",
                          subtitle: str | None = None, filename: str | None = None, currency: str = "EUR",
                          language: Literal["en", "es"] = "en") -> CallToolResult:
        """Create a written report as PDF or Word (.docx). Each section can have a heading,
        narrative text (paragraphs; lines starting with '- ' become bullets), KPI tiles, a chart
        (chart_id from make_chart) and a table from a dataset, in that order.

        Args:
            title: Report title.
            sections: Sections in order.
            format: "pdf" or "docx".
            subtitle: E.g. period and scope.
            filename: Optional file name without extension.
            currency: ISO code of the amounts (the hotel's hotels.currency, listed per hotel by
                describe_schema), e.g. EUR or COP. Money shows as €1,234, $1,234, £1,234, or the
                code for other currencies (COP 1,234,000).
            language: Language of the text the tool adds (dates, column headers, source line):
                "en", or "es" for Latin American Spanish. Write titles and text in the same language.
        """
        if not sections:
            raise ToolError("Provide at least one section.")
        schema = await load_schema(with_hotels=False)
        build = build_pdf if format == "pdf" else build_docx
        try:
            data = build(my_store(), my_charts(), title, subtitle, sections, schema["business_date"], language,
                         currency)
        except DocError as e:
            raise doc_error(e) from e
        info = artifacts.save(data, filename or title, format)
        return _ok({"file": file_ref(info), "sections": len(sections)})

    def _get(dataset_id: str) -> Dataset:
        try:
            return my_store().get(dataset_id)
        except KeyError:
            raise ToolError(f"Unknown or expired dataset_id {dataset_id!r}; run the query again.") from None

    if provider:
        @mcp.custom_route("/oauth/callback", methods=["GET"])
        async def oauth_callback(request: Request) -> Response:
            return await provider.handle_callback(request)

        @mcp.custom_route("/files/{file_id}", methods=["GET"])
        async def download(request: Request) -> Response:
            file_id = request.path_params["file_id"]
            if not provider.link_is_valid(file_id, request.query_params.get("exp", ""),
                                          request.query_params.get("sig", "")):
                return Response("This download link is invalid or has expired.", status_code=403)
            try:
                info, data = artifacts.info(file_id), artifacts.read(file_id)
            except KeyError:
                return Response("File not found or expired.", status_code=404)
            disposition = "inline" if info.mime.startswith("image/") else "attachment"
            return Response(data, media_type=info.mime, headers={
                "Content-Disposition": f"{disposition}; filename*=utf-8''{quote(info.filename)}",
                "Cache-Control": "private, max-age=3600"})

    @mcp.resource("pms://schema", name="schema", mime_type="application/json",
                  description="Tables, views, hotels and business date of the PMS database.")
    async def schema_resource() -> str:
        return json.dumps(await load_schema(), indent=1)

    return mcp
