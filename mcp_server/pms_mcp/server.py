"""MCP server exposing the sample hotel PMS database as read-only tools."""

import base64
import json
import os
import tempfile
from datetime import date
from typing import Any, Literal
from urllib.parse import quote

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ContentBlock, ImageContent, TextContent, ToolAnnotations
from starlette.requests import Request
from starlette.responses import Response

from .access import HotelAccess
from .artifacts import ArtifactStore, FileInfo
from .auth import SCOPE, AuthConfig, OIDCAuthProvider, current_user
from .charts import ChartError, build_chart_data, chart_payload, render_png, render_svg
from .datasets import Dataset, DatasetStore
from .db import Database, QueryError
from .documents import DocError, Section, SheetSpec, Slide, build_docx, build_pdf, build_pptx, build_xlsx
from .formats import KINDS
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


def _ok(payload: dict[str, Any], for_model: dict[str, Any] | None = None,
        extra_content: list[ContentBlock] | None = None) -> CallToolResult:
    """Structured result plus compact JSON text (the default text rendering is indented,
    which roughly doubles the tokens a model spends reading tables). `for_model` replaces
    the text when the structured payload carries UI-only data (e.g. chart SVGs)."""
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

    def my_hotels() -> str:
        hotels = access.hotels_for(current_user())
        if not hotels:
            raise ToolError("Your account has no hotels assigned. Ask the administrator to add you "
                            "to PMS_HOTEL_ACCESS.")
        return hotels

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
        hotels = my_hotels()
        try:
            if not schema_cache:
                schema_cache.update(await _read_schema())
            if not with_hotels:
                return schema_cache
            rows = await db.query(
                "SELECT code, name, city, country, star_rating, total_rooms, currency "
                "FROM pms.hotels ORDER BY id", hotels=hotels)
        except QueryError as e:
            raise ToolError(str(e)) from e
        visible = [dict(zip([c["name"] for c in rows.columns], r)) for r in rows.rows]
        shared = {k: v for k, v in schema_cache.items() if k != "relations"}
        return {**shared, "hotels": visible, "relations": schema_cache["relations"]}

    async def _read_schema() -> dict[str, Any]:
        settings = await db.query(
            "SELECT business_date, data_start, (SELECT max(stay_date) FROM pms.reservation_nights) "
            "FROM pms.system_settings")
        relations = await db.query(SCHEMA_SQL)
        business_date, data_start, data_end = settings.rows[0]
        return {
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
            res = await db.query(query, params, max_rows=MAX_STORED_ROWS, hotels=my_hotels())
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

    def doc_error(e: Exception) -> ToolError:
        return ToolError(str(e))

    @mcp.tool(annotations=CREATES_FILE)
    async def make_chart(
        dataset_id: str,
        x: str,
        y: str,
        title: str,
        chart_type: Literal["line", "bar"] = "line",
        series: str | None = None,
        subtitle: str | None = None,
        y_format: Literal[KINDS] | None = None,
        language: Literal["en", "es"] = "en",
    ) -> CallToolResult:
        """Chart one numeric measure from a stored dataset. The chart is shown to the user in
        the chat (interactive) and saved as a PNG; pass the returned chart_id to
        make_presentation or make_report to embed it.

        Use line for trends over time, bar for comparing categories or a few periods. One measure
        per chart (never two y-axes): to compare occupancy and ADR, make two charts. At most 8
        series; bar charts at most 60 bars.

        Args:
            dataset_id: From run_sql or get_kpis. Rows should be ordered by x.
            x: Column for the x-axis (dates or categories).
            y: Numeric column to plot.
            title: Chart title, e.g. "Occupancy by hotel".
            chart_type: "line" or "bar".
            series: Column whose values become separate lines/bar colors, e.g. "hotel_code".
            subtitle: Period and scope, e.g. "Monthly, Oct 2025 - Sep 2026".
            y_format: Override the value format inferred from the column name.
            language: Language of the text the tool adds (dates, column headers, source line):
                "en", or "es" for Latin American Spanish. Write titles and text in the same language.
        """
        try:
            chart = build_chart_data(_get(dataset_id), chart_type, x, y, series, title, subtitle, y_format,
                                     language)
        except ChartError as e:
            raise doc_error(e) from e
        svg, _ = render_svg(chart, "light")
        png = render_png(svg)
        info = artifacts.save(png, title, "png")
        charts[info.file_id] = (current_user(), png)
        summary = {
            "chart_id": info.file_id,
            "file": file_ref(info),
            "series": [name for name, _ in chart.series],
            "points": len(chart.categories),
            "note": "The chart image is attached and shown to the user.",
        }
        # A 1x image for clients that display tool images (e.g. Claude apps); the website uses
        # the interactive payload instead.
        image = ImageContent(type="image", data=base64.b64encode(render_png(svg, scale=1)).decode(),
                             mime_type="image/png")
        return _ok({**summary, "chart": chart_payload(chart)}, for_model=summary, extra_content=[image])

    @mcp.tool(annotations=CREATES_FILE)
    async def make_spreadsheet(title: str, sheets: list[SheetSpec], filename: str | None = None,
                               language: Literal["en", "es"] = "en") -> CallToolResult:
        """Create an Excel workbook with one sheet per dataset: formatted header, number formats
        (percent, EUR, integers, dates) inferred from column names, frozen header row, filters,
        plus an About sheet listing each sheet's source query. All rows of each dataset are
        included. The file is offered to the user for download.

        Args:
            title: Workbook title (also the default file name).
            sheets: One entry per sheet.
            filename: Optional file name without extension.
            language: Language of the text the tool adds (dates, column headers, source line):
                "en", or "es" for Latin American Spanish. Write titles and text in the same language.
        """
        schema = await load_schema(with_hotels=False)
        try:
            data = build_xlsx(my_store(), title, sheets, schema["business_date"], language)
        except DocError as e:
            raise doc_error(e) from e
        info = artifacts.save(data, filename or title, "xlsx")
        return _ok({"file": file_ref(info), "sheets": len(sheets)})

    @mcp.tool(annotations=CREATES_FILE)
    async def make_presentation(title: str, slides: list[Slide], subtitle: str | None = None,
                                filename: str | None = None,
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
            language: Language of the text the tool adds (dates, column headers, source line):
                "en", or "es" for Latin American Spanish. Write titles and text in the same language.
        """
        schema = await load_schema(with_hotels=False)
        try:
            data = build_pptx(my_store(), my_charts(), title, subtitle, slides, schema["business_date"], language)
        except DocError as e:
            raise doc_error(e) from e
        info = artifacts.save(data, filename or title, "pptx")
        return _ok({"file": file_ref(info), "slides": len(slides) + 1})

    @mcp.tool(annotations=CREATES_FILE)
    async def make_report(title: str, sections: list[Section], format: Literal["pdf", "docx"] = "pdf",
                          subtitle: str | None = None, filename: str | None = None,
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
            language: Language of the text the tool adds (dates, column headers, source line):
                "en", or "es" for Latin American Spanish. Write titles and text in the same language.
        """
        if not sections:
            raise ToolError("Provide at least one section.")
        schema = await load_schema(with_hotels=False)
        build = build_pdf if format == "pdf" else build_docx
        try:
            data = build(my_store(), my_charts(), title, subtitle, sections, schema["business_date"], language)
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
