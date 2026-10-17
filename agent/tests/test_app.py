import json

import httpx2
import pytest

from fakes import FakeClient, text_reply, tool_calls
from pms_agent.app import create_app
from pms_agent.config import Settings
from test_loop import toy_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for chunk in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_chat_streams_sse_and_keeps_history():
    client = FakeClient(tool_calls(("t1", "lookup", {"code": "LIS"})), text_reply("Done."), text_reply("Again."))
    app = create_app(Settings(mcp_url="unused"), client, toy_server())
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        r = await http.post("/api/chat", json={"message": "Check LIS"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(r.text)
        assert [e for e, _ in events] == ["conversation", "thinking", "tool_start", "tool_call",
                                         "tool_result", "text", "done"]
        conv_id = events[0][1]["id"]

        r = await http.post("/api/chat", json={"message": "And again?", "conversation_id": conv_id})
        assert parse_sse(r.text)[0][1]["id"] == conv_id
        # user, assistant(tool_use), user(tool_result), assistant, user
        assert len(client.messages.requests[-1]["messages"]) == 5

        assert (await http.get("/api/health")).json()["model"] == "claude-opus-5-5"
        assert (await http.post("/api/chat", json={"message": ""})).status_code == 422
