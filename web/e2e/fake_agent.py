"""The real agent service with a scripted stand-in for Claude, for browser tests and demos
without an API key. Tools run for real against the PMS MCP server and database.

    PMS_DATABASE_URL=postgresql://pms_readonly:...@localhost:5432/pms python web/e2e/fake_agent.py --port 8101

The stand-in picks a tool from keywords in the question, then answers from the actual tool
result. Keywords: "refuse" -> refusal, "slow" -> a slowly streamed answer (to test Stop),
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


def answer_from(result: dict) -> str:
    wanted = [c["name"] for c in result["columns"]
              if c["name"] in ("hotel_code", "period", "channel", "occupancy", "adr", "revpar",
                               "reservations", "cancellation_rate", "room_revenue")]
    idx = [[c["name"] for c in result["columns"]].index(w) for w in wanted]
    lines = ["| " + " | ".join(wanted) + " |", "|" + "---|" * len(wanted)]
    for row in result["rows"][:15]:
        lines.append("| " + " | ".join(fmt(row[i], wanted[j]) for j, i in enumerate(idx)) + " |")
    return ("Here is what the database shows (stand-in answer for testing, built from the tool "
            "result):\n\n" + "\n".join(lines) + f"\n\nSource dataset: `{result['dataset_id']}`.")


class ScriptedMessages:
    def stream(self, **params):
        last = params["messages"][-1]
        if isinstance(last["content"], list):  # tool results: answer from them
            result = last["content"][0]
            if result.get("is_error"):
                return text_stream("The query failed: " + result["content"])
            return text_stream(answer_from(json.loads(result["content"])))
        question = last["content"].lower()
        if "refuse" in question:
            return ScriptedStream([], "refusal", [], 0)
        if "slow" in question:
            return text_stream("This answer streams slowly so the Stop button can be tested. " * 40,
                               delay=0.15)
        if "channel" in question:
            return tool_stream("run_sql", {"query": CHANNEL_SQL},
                               "Cancellation rates by channel for 2026 year to date.")
        return tool_stream("get_kpis", {"start": "2026-07-01", "end": "2026-09-30", "granularity": "quarter"},
                           "Last quarter relative to the business date is Q3 2026.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8101)
    args = p.parse_args()
    client = SimpleNamespace(beta=SimpleNamespace(messages=ScriptedMessages()))
    app = create_app(Settings(mcp_url="unused", cors_origins=[]), client,
                     build_server(os.environ["PMS_DATABASE_URL"]))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
