"""The real agent service with a scripted stand-in for Claude, for browser tests and demos
without an API key. Tools run for real against the PMS MCP server and database.

    PMS_DATABASE_URL=postgresql://pms_readonly:...@localhost:5432/pms python web/e2e/fake_agent.py --port 8101

With PMS_MCP_URL (and PMS_MCP_TOKEN) set it uses that MCP server instead of one in-process;
PMS_APP_DATABASE_URL turns on user accounts, as in the real agent.

The stand-in picks a plan from keywords in the question, runs its tool steps (each step's input
is built from earlier real results), then answers. Keywords: "refuse" -> refusal, "slow" -> a
slowly streamed answer (to test Stop), "chart", "excel", "deck", "report" -> document flows,
"channel" -> run_sql on v_channel_mix, anything else -> get_kpis for last quarter.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "mcp_server")]

import uvicorn  # noqa: E402
from anthropic.types.beta import BetaTextBlock, BetaThinkingBlock, BetaToolUseBlock  # noqa: E402

from pms_agent.app import create_app  # noqa: E402
from pms_agent.config import Settings  # noqa: E402
from pms_mcp.server import build_server  # noqa: E402

CHANNEL_SQL = """SELECT channel,
       sum(reservations) AS reservations,
       round(sum(cancellations)::numeric / sum(reservations), 4) AS cancellation_rate,
       round(sum(room_revenue) / nullif(sum(room_nights), 0), 2) AS adr
FROM v_channel_mix
WHERE arrival_month >= '2026-01-01' AND arrival_month < '2026-10-01'
GROUP BY channel
ORDER BY cancellation_rate DESC"""


class ScriptedStream:
    def __init__(self, content, stop_reason, chunks, delay):
        self.content, self.stop_reason, self.chunks, self.delay = content, stop_reason, chunks, delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _events(self):
        for event in self.chunks:
            await asyncio.sleep(self.delay)
            yield event

    def __aiter__(self):
        return self._events()

    async def get_final_message(self):
        usage = SimpleNamespace(input_tokens=1200, output_tokens=180, cache_read_input_tokens=5400,
                                cache_creation_input_tokens=0)
        details = SimpleNamespace(category="cyber") if self.stop_reason == "refusal" else None
        return SimpleNamespace(content=self.content, stop_reason=self.stop_reason, usage=usage,
                               stop_details=details)


def text_stream(text, delay=0.02, size=12):
    pieces = [text[i:i + size] for i in range(0, len(text), size)]
    return ScriptedStream([BetaTextBlock(type="text", text=text)], "end_turn",
                          [SimpleNamespace(type="text", text=p) for p in pieces], delay)


def tool_stream(name, tool_input, thinking):
    tool_id = f"toolu_{abs(hash((name, json.dumps(tool_input)))) % 10**8}"
    content = [BetaThinkingBlock(type="thinking", thinking=thinking, signature="sig"),
               BetaToolUseBlock(type="tool_use", id=tool_id, name=name, input=tool_input)]
    events = [SimpleNamespace(type="thinking", thinking=thinking),
              SimpleNamespace(type="content_block_start",
                              content_block=SimpleNamespace(type="tool_use", id=tool_id, name=name))]
    return ScriptedStream(content, "tool_use", events, 0.05)


def fmt(value, column):
    if isinstance(value, (int, float)):
        if column in ("occupancy", "cancellation_rate"):
            return f"{value * 100:.1f}%"
        if column in ("adr", "revpar") or column.endswith("revenue"):
            return f"€{value:,.2f}"
        return f"{value:,}"
    return str(value)


def answer_from(result: dict, spanish: bool = False) -> str:
    wanted = [c["name"] for c in result["columns"]
              if c["name"] in ("hotel_code", "period", "channel", "occupancy", "adr", "revpar",
                               "reservations", "cancellation_rate", "room_revenue")]
    idx = [[c["name"] for c in result["columns"]].index(w) for w in wanted]
    lines = ["| " + " | ".join(wanted) + " |", "|" + "---|" * len(wanted)]
    for row in result["rows"][:15]:
        lines.append("| " + " | ".join(fmt(row[i], wanted[j]) for j, i in enumerate(idx)) + " |")
    if spanish:
        return ("Esto es lo que muestra la base de datos (respuesta simulada para pruebas, armada con el "
                "resultado de la herramienta):\n\n" + "\n".join(lines)
                + f"\n\nConjunto de datos: `{result['dataset_id']}`.")
    return ("Here is what the database shows (stand-in answer for testing, built from the tool "
            "result):\n\n" + "\n".join(lines) + f"\n\nSource dataset: `{result['dataset_id']}`.")


MONTHLY = {"start": "2025-10-01", "end": "2026-09-30", "granularity": "month"}
Q3 = {"start": "2026-07-01", "end": "2026-09-30", "granularity": "quarter"}

# Each plan: tool steps (functions of earlier results -> (tool, input)), then a closing text.
PLANS = {
    "trend": ([
        lambda r: ("get_kpis", {**MONTHLY, "by_hotel": False}),
        lambda r: ("make_chart", {"dataset_id": r[0]["dataset_id"], "chart_type": "bar", "x": "period",
                                  "y": "occupancy", "trend": "linear", "y2": "adr", "title": "Occupancy and ADR",
                                  "subtitle": "All hotels, Oct 2025 – Sep 2026"}),
    ], "Occupancy by month with its trend line, and ADR on the right-hand axis."),
    "chart": ([
        lambda r: ("get_kpis", MONTHLY),
        lambda r: ("make_chart", {"dataset_id": r[0]["dataset_id"], "x": "period", "y": "occupancy",
                                  "series": "hotel_code", "title": "Occupancy by hotel",
                                  "subtitle": "Monthly, Oct 2025 – Sep 2026"}),
    ], "Here is monthly occupancy by hotel for the last 12 months. All three hotels peaked in summer."),
    "excel": ([
        lambda r: ("get_kpis", MONTHLY),
        lambda r: ("make_spreadsheet", {"title": "Monthly KPIs Oct 2025 - Sep 2026",
                                        "sheets": [{"name": "Monthly by hotel", "dataset_id": r[0]["dataset_id"]}]}),
    ], "I put the monthly KPIs by hotel into a spreadsheet."),
    "deck": ([
        lambda r: ("get_kpis", {**Q3, "by_hotel": False}),
        lambda r: ("get_kpis", Q3),
        lambda r: ("make_chart", {"dataset_id": r[1]["dataset_id"], "x": "hotel_code", "y": "revpar",
                                  "chart_type": "bar", "title": "RevPAR by hotel", "subtitle": "Q3 2026"}),
        lambda r: ("make_presentation", {"title": "Q3 2026 performance review", "subtitle": "All hotels", "slides": [
            {"kind": "kpis", "title": "Q3 2026 at a glance", "kpis": [
                {"label": "Occupancy", "dataset_id": r[0]["dataset_id"], "column": "occupancy"},
                {"label": "ADR", "dataset_id": r[0]["dataset_id"], "column": "adr"},
                {"label": "Total revenue", "dataset_id": r[0]["dataset_id"], "column": "total_revenue"}]},
            {"kind": "chart", "title": "Barcelona leads RevPAR", "chart_id": r[2]["chart_id"]},
            {"kind": "table", "title": "KPIs by hotel", "table": {"dataset_id": r[1]["dataset_id"]}}]}),
    ], "The Q3 2026 deck is ready: headline KPIs, RevPAR by hotel and a KPI table."),
    "report": ([
        lambda r: ("get_kpis", MONTHLY),
        lambda r: ("make_chart", {"dataset_id": r[0]["dataset_id"], "x": "period", "y": "occupancy",
                                  "series": "hotel_code", "title": "Occupancy by hotel"}),
        lambda r: ("make_report", {"title": "Occupancy report", "format": "pdf", "sections": [
            {"heading": "Occupancy", "text": "Monthly occupancy for the last 12 months.",
             "chart_id": r[1]["chart_id"]}]}),
    ], "The occupancy report is ready as a PDF."),
}


# Spanish versions for when the system prompt asks for Latin American Spanish: keywords that pick
# each plan, closing texts, and the titles the plans give their documents.
KEYWORDS_ES = {"trend": "tendencia", "chart": "gráfico", "excel": "hoja de cálculo", "deck": "presentación", "report": "reporte"}
CLOSINGS_ES = {
    "trend": "Ocupación mensual con su línea de tendencia y el ADR en el eje derecho.",
    "chart": "Esta es la ocupación mensual por hotel de los últimos 12 meses. Los tres hoteles tuvieron su pico en verano.",
    "excel": "Puse los KPI mensuales por hotel en una hoja de cálculo.",
    "deck": "La presentación del T3 2026 está lista: KPI principales, RevPAR por hotel y una tabla de KPI.",
    "report": "El reporte de ocupación está listo en PDF.",
}
TITLES_ES = {
    "Occupancy by hotel": "Ocupación por hotel", "Monthly, Oct 2025 – Sep 2026": "Mensual, oct 2025 – sept 2026",
    "Monthly KPIs Oct 2025 - Sep 2026": "KPI mensuales oct 2025 - sept 2026", "Monthly by hotel": "Mensual por hotel",
    "Occupancy report": "Reporte de ocupación", "Occupancy": "Ocupación",
    "Monthly occupancy for the last 12 months.": "Ocupación mensual de los últimos 12 meses.",
}


def to_spanish(value):
    """Tool input with Spanish titles and language="es" (document tools)."""
    if isinstance(value, dict):
        return {k: to_spanish(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_spanish(v) for v in value]
    return TITLES_ES.get(value, value) if isinstance(value, str) else value


def turn_results(messages):
    """Model-facing JSON of every tool result since the last question."""
    results = []
    for m in reversed(messages):
        if m["role"] == "user" and isinstance(m["content"], str):
            break
        if m["role"] == "user":
            results[:0] = [json.loads(b["content"]) for b in m["content"] if not b.get("is_error")]
    return results


RECOMMENDATIONS = {"recommendations": [
    {"title": "Cut OTA cancellations", "detail": "Booking.com cancels 31% of its bookings this year.",
     "hotel": "Lisbon", "impact": "€18,400 at risk", "kind": "risk", "question": "Which booking channels have the highest cancellation rates this year?"},
    {"title": "Raise weekend rates", "detail": "Weekends are 94% full 30 days out.", "hotel": "Porto",
     "impact": "+€6,200 estimated", "kind": "money", "question": "Show weekend occupancy on the books"},
    {"title": "Fill midweek in March", "detail": "Tuesday to Thursday sit at 52%.", "hotel": "",
     "impact": "−12 pp vs 2025", "kind": "risk", "question": "Show midweek occupancy in March"},
]}
RECOMMENDATIONS_ES = {"recommendations": [
    {"title": "Reducir las cancelaciones de OTA", "detail": "Booking.com cancela el 31% de sus reservas este año.",
     "hotel": "Lisboa", "impact": "€18,400 en riesgo", "kind": "risk", "question": "¿Qué canales de reserva tienen las tasas de cancelación más altas este año?"},
    {"title": "Subir las tarifas de fin de semana", "detail": "Los fines de semana están al 94% a 30 días.",
     "hotel": "Oporto", "impact": "+€6,200 estimados", "kind": "money", "question": "Muestra la ocupación de fin de semana"},
    {"title": "Llenar entre semana en marzo", "detail": "De martes a jueves están al 52%.", "hotel": "",
     "impact": "−12 pp vs 2025", "kind": "risk", "question": "Muestra la ocupación entre semana en marzo"},
]}


class ScriptedMessages:
    def stream(self, **params):
        messages = params["messages"]
        question = next(m["content"] for m in reversed(messages)
                        if m["role"] == "user" and isinstance(m["content"], str)).lower()
        last = messages[-1]
        if isinstance(last["content"], list) and any(b.get("is_error") for b in last["content"]):
            return text_stream("The tool failed: " + last["content"][0]["content"])
        results = turn_results(messages)
        spanish = "Latin American Spanish" in params["system"]
        if any(t["name"] == "give_recommendations" for t in params["tools"]):
            return tool_stream("give_recommendations", RECOMMENDATIONS_ES if spanish else RECOMMENDATIONS,
                               "Picking today's recommendations.")

        key = next((k for k in PLANS if k in question or (spanish and KEYWORDS_ES[k] in question)), None)
        if key:
            steps, closing = PLANS[key]
            if len(results) < len(steps):
                name, tool_input = steps[len(results)](results)
                if spanish and name.startswith("make_"):
                    tool_input = {**to_spanish(tool_input), "language": "es"}
                return tool_stream(name, tool_input, f"Step {len(results) + 1}: {name}.")
            return text_stream(CLOSINGS_ES[key] if spanish else closing)
        if results:  # one query done: answer from it
            return text_stream(answer_from(results[-1], spanish))
        if "refuse" in question:
            return ScriptedStream([], "refusal", [], 0)
        if "slow" in question:
            return text_stream("This answer streams slowly so the Stop button can be tested. " * 40,
                               delay=0.15)
        if "channel" in question or (spanish and "canal" in question):
            return tool_stream("run_sql", {"query": CHANNEL_SQL},
                               "Cancellation rates by channel for 2026 year to date.")
        return tool_stream("get_kpis", Q3, "Last quarter relative to the business date is Q3 2026.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8101)
    args = p.parse_args()
    client = SimpleNamespace(beta=SimpleNamespace(messages=ScriptedMessages()))
    artifacts = os.environ.get("PMS_ARTIFACTS_DIR", "/tmp/pms-artifacts-e2e")
    settings = Settings(cors_origins=[], artifacts_dir=artifacts, conversations_db=":memory:")
    if os.environ.get("PMS_MCP_URL"):
        # A separate MCP server (PMS_MCP_URL, PMS_MCP_TOKEN), e.g. with the user directory on.
        app = create_app(settings, client)
    else:
        app = create_app(settings, client, build_server(os.environ["PMS_DATABASE_URL"], artifacts_dir=artifacts))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
