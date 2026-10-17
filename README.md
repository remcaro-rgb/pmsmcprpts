# PMS Reports Chat

A chatbot website that answers questions about a hotel property-management-system (PMS)
database and generates spreadsheets, charts, PowerPoint decks and PDF/Word reports.
See [docs/design.md](docs/design.md) for the full design.

**Status:** milestones 1–6: the sample PMS database, the MCP server that exposes it, the Claude
agent API, the chat website, charts, Excel, PowerPoint and PDF/Word generation, and sign-in so
people can connect the MCP server to their own Claude accounts. Next: an evaluation set of sample
questions with known answers.

## Quick start

```bash
cp .env.example .env         # then set ANTHROPIC_API_KEY
docker compose up -d db      # Postgres 16 with the pms schema and read-only role
docker compose run --rm seed # load ~2 years of synthetic data (~1 minute)
docker compose up -d         # MCP server, Claude agent API and the website
```

Open http://localhost:5050 and ask a question. Services:

| Service | URL |
|---|---|
| Website | http://localhost:5050 |
| Agent API | http://localhost:7001/api/chat |
| MCP server | http://localhost:7070/mcp |
| Postgres | `postgresql://pms_readonly:pms_readonly@localhost:5432/pms` |

Or ask from the command line:

```bash
curl -N http://localhost:7001/api/chat -H 'content-type: application/json' \
  -d '{"message": "How did occupancy and ADR compare across the three hotels last quarter?"}'
```

Set `PMS_DB_PORT` / `PMS_MCP_PORT` / `PMS_AGENT_PORT` / `PMS_WEB_PORT` to use other ports.

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
| `get_dataset(dataset_id, offset, limit)` | Page through a stored result. |
| `make_chart(dataset_id, x, y, title, chart_type, series?, ...)` | Line or bar chart of one measure, shown interactively in the chat and saved as a PNG. Returns a `chart_id` for decks and reports. |
| `make_spreadsheet(title, sheets)` | Excel workbook, one sheet per dataset, with number formats, frozen headers, filters and an About sheet listing each sheet's source query. |
| `make_presentation(title, slides, subtitle?)` | 16:9 PowerPoint deck: title slide, then KPI tiles, charts (with optional takeaways), tables and bullet slides, each with a source footer. |
| `make_report(title, sections, format)` | PDF or Word report: sections with headings, narrative, KPI tiles, charts and tables. |

The document tools read every number from stored datasets (by `dataset_id` and column), never
from text the model types, so the numbers in a file always match the query. Charts follow a
validated colour-blind-safe palette, use one y-axis per chart, and come with light and dark
variants plus a phone layout. Generated files go to `PMS_ARTIFACTS_DIR`, a volume shared with the
agent, which serves them for download, and expire after 24 hours.

Safety: queries are parsed with sqlglot and rejected unless they are a single read query (no
data-modifying CTEs, `SELECT INTO`, `FOR UPDATE`, `pg_sleep`, file-access or SQL-executing
functions). They then run in a `READ ONLY` transaction with a 15 s timeout as `pms_readonly`,
which only has `SELECT` privileges.

### Use it from Claude

Claude Code, against the Docker service:

```bash
claude mcp add --transport http pms-reports http://localhost:7070/mcp
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

### Let people connect from their own Claude accounts

Anyone you allow can add the server as a **custom connector** in their own Claude app (web,
desktop or mobile). They ask questions in their own Claude chats, and their Claude plan covers
the model usage; no Anthropic API key is needed on your side for them.

How it works: the MCP server acts as an OAuth authorization server, the flow Claude's connectors
use, with dynamic client registration and PKCE. It hands the actual sign-in to your OpenID
Connect provider (Google, Microsoft Entra ID, Auth0, Okta, Keycloak, ...), then checks the
allowlist.

Setup:

1. **A public HTTPS address.** Point a domain (e.g. `pms.example.com`) at the server, with ports
   80 and 443 open. The bundled Caddy proxy gets the TLS certificate automatically.
2. **An OIDC app at your sign-in provider**, with redirect URI
   `https://pms.example.com/oauth/callback`. Note its client ID and secret, and the issuer:
   - Google: `https://accounts.google.com`
   - Microsoft Entra ID: `https://login.microsoftonline.com/<tenant-id>/v2.0`
   - Auth0: `https://<tenant>.auth0.com`
3. **Settings in `.env`:**
   ```bash
   PMS_PUBLIC_URL=https://pms.example.com
   PMS_DOMAIN=pms.example.com
   PMS_OIDC_ISSUER=https://accounts.google.com
   PMS_OIDC_CLIENT_ID=...
   PMS_OIDC_CLIENT_SECRET=...
   PMS_ALLOWED_DOMAINS=yourhotelgroup.com   # and/or PMS_ALLOWED_EMAILS=a@x.com,b@y.com
   PMS_MCP_SERVICE_TOKEN=$(openssl rand -hex 32)   # keeps the website working; paste the value
   ```
4. **Start it:** `docker compose --profile public up -d`.
5. **Each user, in Claude:** Settings → Connectors → *Add custom connector*, URL
   `https://pms.example.com/mcp`, then *Connect* and sign in.

What users get:
- **Tools:** all eight, in their own Claude chats.
- **Charts:** shown as images.
- **Files:** spreadsheets, decks and reports come with a download link that works for 24 hours.

Security notes:
- **Who can connect:** only accounts on the allowlist. Removing someone takes effect on their next
  request, because tokens are checked against the allowlist every time.
- **Tokens:** access tokens last 1 hour and refresh tokens 30 days. Refresh tokens rotate on use,
  and all tokens are stored hashed.
- **Privacy between users:** each person's query results and charts are visible only to them.
  Everyone sees the same hotels.
- **Download links:** signed and time-limited.
- **The website:** its agent keeps working through the service token (`PMS_MCP_TOKEN`), set
  automatically from `PMS_MCP_SERVICE_TOKEN` in Docker Compose.
- **Without sign-in:** when `PMS_PUBLIC_URL` is unset, the server runs as before, local and
  without sign-in.

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
| `tool_result` | `{id, name, is_error, result}`: the tool's result, tables trimmed to 50 preview rows; charts and files include their `file` (and `chart`) data |
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

`GET /files/{file_id}` downloads a generated chart or document.

Run it locally with `pip install -r agent/requirements.txt`, then `python -m pms_agent` from
`agent/` (set `ANTHROPIC_API_KEY`, `PMS_MCP_URL` and the same `PMS_ARTIFACTS_DIR` as the MCP server).

## Website

`web/` is a Next.js chat app. Answers stream in as Markdown. Each tool step is a collapsible card
with its input (the SQL, or the KPI parameters) and the result table. Charts appear inline with a
hover crosshair and tooltip (also reachable with the arrow keys), a "Show data" table and a PNG
download. Spreadsheets, decks and reports appear as download cards. There's a Stop button and
starter questions, and it works in light and dark mode and at phone width. The browser only talks
to the site's own `/api/chat` and `/api/files/{id}` routes, which proxy the agent (`AGENT_URL`).

Develop locally (with the agent running on port 7001):

```bash
cd web && npm install
AGENT_URL=http://localhost:7001 npm run dev
```

To try the UI without an Anthropic API key, run the stand-in agent instead of the real one. It is
the real agent service and MCP server with a scripted stand-in for Claude that runs real queries
and answers from their results:

```bash
PMS_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms \
  python web/e2e/fake_agent.py --port 7001
```

## Tests

```bash
pip install -r db/requirements-dev.txt -r mcp_server/requirements-dev.txt -r agent/requirements-dev.txt
PMS_TEST_ADMIN_URL=postgresql://pms:pms@localhost:5432/postgres \
PMS_TEST_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms \
pytest
```

- `db/tests` create a throwaway database, seed a small window and check invariants (no
  double-booked rooms, statuses consistent with the business date, closed folios fully paid, KPI sanity).
- `mcp_server/tests` unit-test the SQL guard and formats, and call every tool through an
  in-process MCP client against the seeded database, opening the generated xlsx/pptx/docx/pdf
  to check their contents.
- `agent/tests` drive the tool loop and the SSE endpoint with a scripted fake Claude client
  (no API key needed) against real in-process MCP servers.

Website:

```bash
cd web
npm test                      # unit tests: SSE parser, stream-event reducer, chart hover
npm run build
PMS_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms npm run e2e
```

The browser tests start the stand-in agent and the production build, then check a starter
question end to end (tool card, SQL, result table, Markdown answer), follow-up questions in one
conversation, Stop, refusals, an interactive chart (hover, keyboard, data table, PNG download) and
downloading a generated .xlsx, .pptx and .pdf. The stand-in understands "chart", "excel", "deck"
and "report" in a question. If Playwright's own Chromium isn't installed, set
`PW_CHROMIUM_PATH` to a Chromium binary.
