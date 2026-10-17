# PMS Reports Chat

A chatbot website that answers questions about a hotel property-management-system (PMS)
database and generates spreadsheets, charts, PowerPoint decks and PDF/Word reports.
See [docs/design.md](docs/design.md) for the full design.

**Status:** milestones 1–3 — sample PMS database, the MCP server that exposes it, and the Claude
agent API. The web UI and document generation come next.

## Quick start

```bash
cp .env.example .env
docker compose up -d db      # Postgres 16 with the pms schema and read-only role
docker compose run --rm seed # load ~2 years of synthetic data (~1 minute)
docker compose up -d mcp     # MCP server at http://localhost:8000/mcp
docker compose up -d agent   # Claude agent API at http://localhost:8001 (needs ANTHROPIC_API_KEY in .env)
```

Ask a question from the command line:

```bash
curl -N http://localhost:8001/api/chat -H 'content-type: application/json' \
  -d '{"message": "How did occupancy and ADR compare across the three hotels last quarter?"}'
```

Set `PMS_DB_PORT` / `PMS_MCP_PORT` / `PMS_AGENT_PORT` to use ports other than 5432 / 8000 / 8001.

## Sample data

Three fictional hotels (all EUR):

| Code | Hotel | City | Stars | Rooms |
|---|---|---|---|---|
| LIS | Tagus Riverside Hotel | Lisbon | 4 | 220 |
| BCN | Eixample Grand Hotel | Barcelona | 5 | 180 |
| OPO | Douro Plaza Hotel | Porto | 4 | 200 |

- **Business date** 2026-10-17 (`pms.system_settings`). Stays before it are actuals; the
  following 180 days hold on-the-books bookings, for pickup / pace analysis.
- **History** of 730 days: ~174k reservations, ~450k room nights, ~750k folio charges,
  ~400k housekeeping tasks, ~30k reviews.
- **Realistic patterns:** seasonality per city, weekday/weekend demand and pricing,
  channel-specific lead times and cancellation rates, corporate mid-week demand,
  non-refundable plans, no-shows, repeat guests and loyalty tiers, room-level inventory
  with no double bookings.

Generation is deterministic for a given `--seed`. Options:

```bash
python db/seed.py --help
python db/seed.py --reset --business-date 2026-10-17 --history-days 730 --future-days 180
```

## Schema

Tables in schema `pms`: `hotels`, `room_types`, `rooms`, `rate_plans`, `guests`,
`companies`, `travel_agents`, `reservations`, `reservation_nights`, `folios`,
`folio_charges`, `payments`, `staff`, `housekeeping_tasks`, `reviews`, `system_settings`.

Reporting views (KPI definitions live in their `COMMENT`s):

- `v_daily_kpis` — per hotel per date: rooms available/sold, occupancy, ADR, RevPAR, revenue by department.
- `v_pickup` — one row per booked room night with booking/cancellation dates, for pace reports.
- `v_channel_mix` — per hotel, arrival month and channel: volume, cancellations, room nights, ADR, lead time.
- `v_guest_stays` — per guest: stays, nights, spend, first/last stay.

The `pms_readonly` role has `SELECT` only, read-only transactions and a 15 s statement timeout;
the MCP server connects with it.

## MCP server

`mcp_server/` is an [MCP](https://modelcontextprotocol.io) server that gives an LLM read-only
access to the database. Tools:

| Tool | Purpose |
|---|---|
| `describe_schema(table?)` | Business date, data range, hotels, and every table/view with column types and meanings. Also available as the `pms://schema` resource. |
| `run_sql(query, preview_rows=100)` | One read-only `SELECT`/`WITH` query. The full result (up to 50k rows) is stored as a dataset; returns its `dataset_id`, columns, row count and a preview. |
| `get_kpis(start, end, hotels?, granularity, by_hotel)` | Occupancy, ADR, RevPAR and revenue by day/week/month/quarter/year, with ratios aggregated correctly. |
| `get_dataset(dataset_id, offset, limit)` | Page through a stored result. Later milestones' chart/spreadsheet/deck tools take a `dataset_id` too, so numbers flow from SQL into documents without being retyped. |

Safety: queries are parsed with sqlglot and rejected unless they are a single read query (no
data-modifying CTEs, `SELECT INTO`, `FOR UPDATE`, `pg_sleep`, file-access or SQL-executing
functions). They then run in a `READ ONLY` transaction with a 15 s timeout as `pms_readonly`,
which only has `SELECT` privileges.

### Use it from Claude

Claude Code, against the Docker service:

```bash
claude mcp add --transport http pms-reports http://localhost:8000/mcp
```

Claude Desktop (stdio), in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pms-reports": {
      "command": "python",
      "args": ["-m", "pms_mcp"],
      "env": {
        "PYTHONPATH": "/path/to/pmsmcprpts/mcp_server",
        "PMS_DATABASE_URL": "postgresql://pms_readonly:pms_readonly@localhost:5432/pms"
      }
    }
  }
}
```

Run it locally with `pip install -r mcp_server/requirements.txt`, then
`python -m pms_mcp --help` from `mcp_server/`.

## Agent API

`agent/` is a FastAPI service that runs Claude with the MCP server's tools.

`POST /api/chat` with `{"message": "...", "conversation_id": "..."}` (omit the id to start a new
conversation) returns a stream of server-sent events:

| Event | Data |
|---|---|
| `conversation` | `{id}`: pass it back to continue the conversation |
| `thinking` | `{text}`: summarized reasoning, streamed |
| `tool_start` | `{id, name}`: a tool call began |
| `tool_call` | `{id, name, input}`: the complete tool input (e.g. the SQL) |
| `tool_result` | `{id, name, is_error, result}`: the tool's result, tables trimmed to 50 preview rows |
| `text` | `{text}`: answer text, streamed |
| `done` | `{stop_reason, usage}` |
| `refusal` / `error` | `{message, ...}`: the turn failed and is not kept in the history |

Details:
- **Model:** `claude-opus-5-5` at `medium` effort (`PMS_CLAUDE_MODEL`, `PMS_CLAUDE_EFFORT`), with
  adaptive thinking and up to 15 tool steps per message (`PMS_MAX_TOOL_STEPS`).
- **Prompt caching:** the system prompt, tools and conversation history are cached between steps.
  Histories are append-only so the cache stays warm.
- **Refusal fallbacks:** if Claude's safety filters decline a request, the API retries it on a
  recommended fallback model (`fallbacks: "default"`; set `PMS_SERVER_FALLBACKS=false` on
  platforms other than the Claude API).
- **Storage:** conversations are kept in memory and lost on restart.

Run it locally with `pip install -r agent/requirements.txt`, then `python -m pms_agent` from
`agent/` (set `ANTHROPIC_API_KEY` and `PMS_MCP_URL`).

## Tests

```bash
pip install -r db/requirements-dev.txt -r mcp_server/requirements-dev.txt -r agent/requirements-dev.txt
PMS_TEST_ADMIN_URL=postgresql://pms:pms@localhost:5432/postgres \
PMS_TEST_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms \
pytest
```

- `db/tests` create a throwaway database, seed a small window and check invariants (no
  double-booked rooms, statuses consistent with the business date, closed folios fully paid, KPI sanity).
- `mcp_server/tests` unit-test the SQL guard and call every tool through an in-process MCP
  client against the seeded database.
- `agent/tests` drive the tool loop and the SSE endpoint with a scripted fake Claude client
  (no API key needed) against real in-process MCP servers.
