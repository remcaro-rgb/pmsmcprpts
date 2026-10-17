# PMS Reports Chat — Design

A demo website where hotel staff chat with an AI assistant that answers questions about a
hotel property-management-system (PMS) database and generates documents — Excel workbooks,
charts, PowerPoint decks, and PDF/Word reports — from that data.

## Decisions

| Topic | Choice |
|---|---|
| Data | Synthetic sample PMS database: 3 hotels, 2 years of history |
| Engine | PostgreSQL 16 |
| Web UI | Next.js (App Router) + Tailwind |
| Backend | Python FastAPI agent service |
| LLM ↔ data | Standalone **MCP server** (Python, `mcp` SDK) — also usable from Claude Desktop / Claude Code |
| LLM | Claude via Anthropic API, tool use + streaming (model configurable via env) |
| Auth | None (demo) |
| Run | Local `docker compose up` |

## Architecture

```
┌─────────────┐  SSE stream   ┌──────────────────┐  MCP (streamable HTTP)  ┌──────────────────┐   SQL (read-only role)  ┌────────────┐
│ Next.js web │ ◀───────────▶ │ FastAPI agent    │ ◀─────────────────────▶ │ pms-mcp server   │ ──────────────────────▶ │ Postgres   │
│ chat + docs │   /api/chat   │ Claude tool loop │                         │ data + doc tools │                         │ pms schema │
└─────────────┘               └──────────────────┘                         └────────┬─────────┘                         └────────────┘
       ▲  GET /files/{id}                                                           │ writes
       └─────────────────────────────────── shared volume: ./artifacts ◀────────────┘
```

1. User sends a message; web calls `POST /api/chat` (SSE).
2. Agent service holds conversation state, lists tools from the MCP server, and runs the
   Claude tool-use loop, bridging each `tool_use` block to an MCP `call_tool`.
3. MCP tools query Postgres through a **read-only role** and write generated files to a
   shared `artifacts/` volume, returning `{file_id, filename, mime, preview}`.
4. Agent streams text deltas, tool-progress events, and artifact events to the UI.
   The UI renders text as markdown, tables as grids, charts inline (Vega-Lite), and
   files as download cards.

## Sample PMS schema (`pms`)

- `hotels` (id, name, city, star_rating, total_rooms, currency)
- `room_types` (id, hotel_id, code, name, max_occupancy, base_rate)
- `rooms` (id, hotel_id, room_type_id, number, floor, status)
- `guests` (id, first_name, last_name, email, country, loyalty_tier, created_at)
- `companies` / `travel_agents` (corporate & OTA accounts)
- `rate_plans` (id, hotel_id, code, name, refundable, includes_breakfast, price_factor)
- `reservations` (id, hotel_id, guest_id, channel, source_id, rate_plan_id, booked_at,
  arrival, departure, adults, children, status [confirmed/cancelled/no_show/checked_in/checked_out],
  cancelled_at)
- `reservation_nights` (reservation_id, stay_date, rate) — one row per room night
- `folios` / `folio_charges` (room, F&B, spa, minibar, taxes; posted_at, amount)
- `payments` (folio_id, method, amount, paid_at)
- `housekeeping_tasks` (room_id, date, type, status, staff_id)
- `staff` (id, hotel_id, department, role)
- `reviews` (reservation_id, score, source, comment, created_at)

Plus reporting **views** that encode industry definitions once, so the LLM doesn't reinvent them:
`v_daily_kpis` (hotel, date, rooms_available, rooms_sold, occupancy, ADR, RevPAR, revenue by
department), `v_pickup`, `v_channel_mix`, `v_guest_stays`.

**Seeder** (`db/seed.py`, Faker + deterministic RNG seed): ~600 rooms, ~150k reservations,
with seasonality, weekday/weekend patterns, lead-time distributions, a cancellation rate by
channel, and realistic ancillary spend.

## MCP tools

Data:
- `describe_schema()` — tables, columns, views, and KPI definitions (also exposed as an MCP resource).
- `run_sql(query, preview_rows=100)` — single `SELECT`/`WITH` only (parsed with `sqlglot`),
  read-only role and transaction, `statement_timeout` 15s, 50k-row cap. Returns `dataset_id`,
  columns, row count, truncated flag and a preview.
- `get_kpis(start, end, hotels, granularity, by_hotel)` — fast path over `v_daily_kpis`.
- `get_dataset(dataset_id, offset, limit)` — page through a stored result.

Documents (each reads values from stored datasets by `dataset_id` and column, so data flows
SQL → doc without the LLM re-typing numbers; the model supplies structure and commentary):
- `make_chart(dataset_id, x, y, series, chart_type, ...)` — one Python SVG renderer (validated
  palette, one y-axis, data-viz mark specs) → PNG via `vl-convert`'s resvg for documents, and
  light/dark × wide/narrow SVGs plus hover geometry for the interactive inline view.
- `make_spreadsheet(title, sheets[])` — openpyxl; header styles, number formats inferred from
  column names, frozen panes, filters, an About sheet with each sheet's source query.
  (Native Excel charts: not yet.)
- `make_presentation(title, slides[])` — python-pptx; a title slide, then kpis (tiles), chart
  (`chart_id`, optional takeaways), table and bullets slides, each with a source footer.
- `make_report(title, sections[], format="pdf"|"docx")` — headings, narrative, KPI tiles,
  charts and tables → PDF (reportlab, no system libraries needed) or DOCX (python-docx).
- Files go to a shared artifacts volume (24h expiry); the agent serves `GET /files/{id}`.

To keep large results out of the LLM context, `run_sql` stores full results server-side and
returns a `dataset_id` plus a preview; doc tools accept `dataset_id`.

## Agent service (FastAPI)

- `POST /api/chat` — `{conversation_id, message}` → SSE events: `conversation`, `thinking`,
  `text`, `tool_start`, `tool_call`, `tool_result`, `done`, `refusal`, `error` (`artifact` comes
  with the document tools).
- `GET /files/{file_id}` — serves generated files (milestone 5).
- Claude Opus 5.5 at `medium` effort with summarized adaptive thinking; refusal fallbacks
  (`fallbacks: "default"`) on. A failed turn is rolled back so history stays valid.
- System prompt: role, KPI glossary, "always inspect schema before writing SQL", "state the
  date range and hotels you assumed", "prefer views for KPIs".
- Prompt caching (top-level `cache_control`) over system prompt, tools and the append-only
  history; max 15 tool steps per turn.
- Conversations saved per user in SQLite on the agent (history to continue them, plus each answer's events to show them again).

## Web UI (Next.js)

- Chat pane with streaming markdown, collapsible "ran SQL" blocks showing the query.
- Inline Vega-Lite charts; result tables via a lightweight data grid.
- Artifact cards (icon, name, size, download); side panel listing this session's files.
- Starter prompts: "Occupancy and ADR by month for 2025, all hotels", "Build a PowerPoint
  on Q3 performance for the Lisbon hotel", "Export cancellations by channel to Excel".

## Repo layout

```
db/            schema.sql, views.sql, seed.py
mcp_server/    pms_mcp/{server,db,sql_guard,datasets}.py (+ doc tools later), tests/
agent/         pms_agent/{app,loop,config,prompts,conversations}.py, tests/
web/           Next.js app: app/ (page + /api/chat proxy), components/, lib/ (SSE, reducer), e2e/
docker-compose.yml, .env.example, README.md
```

## Remote access (Claude custom connectors)

- The MCP server is an OAuth 2.1 authorization server (SDK `auth_server_provider`): dynamic client
  registration, PKCE, `/authorize` → upstream OIDC login → `/oauth/callback` → code → `/token`.
- Identity comes from the OIDC ID token (signature checked against the provider's JWKS, issuer,
  audience, nonce, verified email); an email/domain allowlist decides access, checked on every
  request. Clients, codes and tokens (hashed) live in SQLite on a volume.
- Per-user data: datasets and charts carry their owner; tools only see the caller's.
- Files: HMAC-signed links valid 24h served by the MCP server; charts also returned as images.
- The website's agent authenticates with a shared service token.

## Safety & correctness

- DB role with `SELECT` only on `pms` schema; SQL parsed and rejected if not a single read query.
- Row/time limits; file size limits; artifacts expire after 24h.
- Numbers in documents come from tool datasets, never from LLM-typed values.
- No PII concerns (synthetic data), but guest fields are still fake-only.

## Testing

- Unit: SQL guard, each doc generator (open output and assert structure).
- Golden questions: ~20 NL questions with expected SQL results on the fixed-seed DB,
  run against the agent as an eval.
- E2E: Playwright — ask a question, receive a chart and a downloadable .xlsx.

## Milestones

1. ✅ DB schema, views, seeder, docker-compose with Postgres.
2. ✅ MCP server: `describe_schema`, `run_sql`, `get_kpis` + tests (usable from Claude Desktop immediately).
3. ✅ Agent service with Claude tool loop + SSE.
4. ✅ Web chat UI with streaming and SQL/table display.
5. ✅ Doc tools: charts → xlsx → pptx → pdf/docx, with artifact cards.
6. ✅ Remote connector: users connect their own Claude accounts (OAuth 2.1 + OIDC sign-in,
   allowlist, per-user data, signed download links).
7. ✅ CI (GitHub Actions), rate limits, website sign-in (OIDC, same allowlist), saved
   conversations with a sidebar, per-hotel access (PostgreSQL row-level security).
8. ✅ English and Latin American Spanish: website, agent answers, chart and document labels.
9. Golden-question evals, polish, README.

## Open questions

- Hotel names/locations: defaulted to Lisbon, Barcelona and Porto (EUR); see README.
- Should decks follow a brand template (.potx) later?
