import os
from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaTextBlock, BetaThinkingBlock, BetaToolUseBlock
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from fakes import FakeClient, FakeStream, refusal, text_reply, tool_calls
from pms_agent.config import Settings
from pms_agent.conversations import Conversation
from pms_agent.loop import ChatAgent, echo_content

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def toy_server() -> MCPServer:
    mcp = MCPServer("toy", instructions="Toy instructions.")

    @mcp.tool()
    async def lookup(code: str) -> dict[str, Any]:
        """Look up a hotel."""
        if code == "XXX":
            raise ToolError("Unknown hotel code XXX")
        return {"dataset_id": "ds_1", "row_count": 60, "rows": [[i] for i in range(60)]}

    return mcp


def make_agent(*script, steps=15, server=None):
    client = FakeClient(*script)
    settings = Settings(mcp_url="unused", max_tool_steps=steps)
    return ChatAgent(settings, client, server or toy_server()), client


async def run(agent, conv, text):
    return [e async for e in agent.run_turn(conv, text)]


def names(events):
    return [e["event"] for e in events]


async def test_text_answer():
    agent, client = make_agent(text_reply("Hello."))
    conv = Conversation("c1")
    events = await run(agent, conv, "Hi")
    assert names(events) == ["text", "done"]
    assert [m["role"] for m in conv.messages] == ["user", "assistant"]
    req = client.messages.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert req["output_config"] == {"effort": "medium"}
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["cache_control"] == {"type": "ephemeral"}
    assert req["system"].endswith("Toy instructions.")
    assert req["tools"][0]["name"] == "lookup" and req["tools"][0]["eager_input_streaming"] is True


async def test_tool_round_trip():
    agent, client = make_agent(
        tool_calls(("t1", "lookup", {"code": "LIS"}), ("t2", "lookup", {"code": "XXX"})),
        text_reply("LIS is fine; XXX does not exist."),
    )
    conv = Conversation("c1")
    events = await run(agent, conv, "Check LIS and XXX")
    assert names(events) == ["thinking", "tool_start", "tool_start", "tool_call", "tool_call",
                             "tool_result", "tool_result", "text", "done"]
    ok, err = [e["data"] for e in events if e["event"] == "tool_result"]
    assert ok["is_error"] is False and ok["result"]["dataset_id"] == "ds_1"
    assert len(ok["result"]["rows"]) == 50  # trimmed for the UI
    assert err["is_error"] is True and "Unknown hotel code" in err["result"]

    roles = [m["role"] for m in conv.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert conv.messages[1]["content"][0] == {"type": "thinking", "thinking": "Need data.", "signature": "sig"}
    results = conv.messages[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert "is_error" not in results[0] and results[1]["is_error"] is True
    assert '"row_count":60' in results[0]["content"].replace(" ", "")
    # The second request carries the full history, unchanged.
    assert client.messages.requests[1]["messages"] == conv.messages[:3]


async def test_refusal_rolls_back_only_the_failed_turn():
    agent, _ = make_agent(text_reply("First answer."), tool_calls(("t1", "lookup", {"code": "LIS"})), refusal())
    conv = Conversation("c1")
    await run(agent, conv, "First")
    events = await run(agent, conv, "Second")
    assert names(events) == ["thinking", "tool_start", "tool_call", "tool_result", "refusal"]
    assert events[-1]["data"]["category"] == "cyber"
    assert [m["role"] for m in conv.messages] == ["user", "assistant"]


async def test_api_error_is_reported_and_rolled_back():
    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    agent, _ = make_agent(err)
    conv = Conversation("c1")
    events = await run(agent, conv, "Hi")
    assert names(events) == ["error"] and "Claude API error" in events[0]["data"]["message"]
    assert conv.messages == []


async def test_step_limit():
    agent, _ = make_agent(tool_calls(("t1", "lookup", {"code": "LIS"})),
                          tool_calls(("t2", "lookup", {"code": "LIS"})), steps=2)
    conv = Conversation("c1")
    events = await run(agent, conv, "Loop forever")
    assert events[-1]["event"] == "error" and "2 tool steps" in events[-1]["data"]["message"]
    assert conv.messages == []


async def test_truncated_tool_call_is_not_run():
    agent, _ = make_agent(tool_calls(("t1", "lookup", {"code": "L"}), stop_reason="max_tokens"))
    conv = Conversation("c1")
    events = await run(agent, conv, "Hi")
    assert names(events) == ["thinking", "tool_start", "error"]
    assert conv.messages == []


async def test_unparseable_tool_input_is_retried():
    broken = FakeStream([], "tool_use", [], error=ValueError("bad json"))
    agent, client = make_agent(broken, text_reply("Recovered."))
    events = await run(agent, Conversation("c1"), "Hi")
    assert names(events) == ["retry", "text", "done"]
    assert len(client.messages.requests) == 2


def test_echo_content_drops_declined_blocks_before_fallback():
    fallback = BetaTextBlock.model_construct(type="fallback")
    fallback.model_dump = lambda **kw: {"type": "fallback", "from": {"model": "a"}, "to": {"model": "b"}}
    content = [
        BetaTextBlock(type="text", text="partial"),
        BetaThinkingBlock(type="thinking", thinking="x", signature="s"),
        BetaToolUseBlock(type="tool_use", id="t0", name="lookup", input={}),
        fallback,
        BetaThinkingBlock(type="thinking", thinking="y", signature="s2"),
        BetaToolUseBlock(type="tool_use", id="t1", name="lookup", input={"code": "LIS"}),
    ]
    assert [b["type"] for b in echo_content(content)] == ["text", "thinking", "tool_use"]
    assert echo_content(content)[2]["id"] == "t1"


@pytest.mark.skipif(not os.environ.get("PMS_TEST_DATABASE_URL"), reason="PMS_TEST_DATABASE_URL not set")
async def test_with_real_pms_server():
    from pms_mcp.server import build_server

    server = build_server(os.environ["PMS_TEST_DATABASE_URL"])
    agent, client = make_agent(
        tool_calls(("t1", "get_kpis", {"start": "2025-07-01", "end": "2025-07-31", "hotels": ["LIS"]})),
        text_reply("Lisbon ran at high occupancy in July 2025."),
        server=server,
    )
    conv = Conversation("c1")
    events = await run(agent, conv, "How did Lisbon do in July 2025?")
    (result,) = [e["data"] for e in events if e["event"] == "tool_result"]
    assert not result["is_error"]
    assert result["result"]["dataset_id"].startswith("ds_")
    assert result["result"]["rows"][0][:2] == ["LIS", "2025-07-01"]
    tool_names = [t["name"] for t in client.messages.requests[0]["tools"]]
    assert tool_names[:4] == ["describe_schema", "run_sql", "get_kpis", "get_dataset"]
    assert "make_chart" in tool_names
    assert "business date" in client.messages.requests[0]["system"]


def test_service_token_is_sent_to_url_targets():
    from pms_agent.loop import ChatAgent as Agent

    with_token = Agent(Settings(mcp_url="http://mcp:7070/mcp", mcp_token="t" * 40), FakeClient())
    assert not isinstance(with_token._mcp().server, str)  # a transport carrying the bearer header
    without = Agent(Settings(mcp_url="http://mcp:7070/mcp", mcp_token=None), FakeClient())
    assert without._mcp().server == "http://mcp:7070/mcp"
