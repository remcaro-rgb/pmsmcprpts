import httpx2
import pytest

from fakes import FakeClient, text_reply, tool_calls
from pms_agent.app import create_app
from pms_agent.config import Settings
from pms_agent.recommend import SUBMIT, clean
from test_loop import toy_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def submit(n):
    items = [{"title": f"Raise ADR {i}", "detail": "Pace is up 12%.", "hotel": "Fragata",
              "question": "Show pace", "impact": "+COP 9.8 M", "kind": "money"} for i in range(n)]
    return tool_calls(("s1", SUBMIT, {"recommendations": items}))


async def test_made_once_a_day_and_trimmed_to_three():
    # Prose without the tool gets a nudge; then four come back and three are kept.
    client = FakeClient(text_reply("Here they are."), submit(4))
    app = create_app(Settings(mcp_url="unused", conversations_db=":memory:", timezone="Mars/Base"),
                     client, toy_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as http:
        r = await http.get("/api/recommendations", params={"language": "es"})
        assert r.status_code == 200 and len(r.json()["recommendations"]) == 3
        first = r.json()["recommendations"][0]
        assert first["hotel"] == "Fragata" and first["kind"] == "money" and first["feedback"] is None
        # Feedback is kept per user and shows on the next read.
        for ref, value in [(first["ref"] + ":done", "done"), (first["ref"], "up")]:
            r2 = await http.post("/api/feedback", json={"kind": "recommendation", "ref": ref, "value": value})
            assert r2.status_code == 204
        again = await http.get("/api/recommendations", params={"language": "es"})
        assert again.json()["recommendations"][0] | {"feedback": "up", "done": True} == again.json()["recommendations"][0]
        assert (await http.post("/api/feedback", json={"kind": "answer", "ref": "x y", "value": "up"})).status_code == 422
    first = client.messages.requests[0]
    assert "español" in first["messages"][0]["content"]
    assert [t["name"] for t in first["tools"]] == [SUBMIT]  # the toy server has no data tools
    assert len(client.messages.requests) == 2


async def test_failure_is_a_503_and_not_cached():
    client = FakeClient(tool_calls(("s1", SUBMIT, {"recommendations": []})), submit(1))
    app = create_app(Settings(mcp_url="unused", conversations_db=":memory:"), client, toy_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as http:
        r = await http.get("/api/recommendations")
        assert r.status_code == 503 and "recommendations" in r.json()["detail"]
        assert len((await http.get("/api/recommendations")).json()["recommendations"]) == 1


def test_clean():
    assert clean({"recommendations": [{"title": " x ", "detail": None, "extra": 1}, {"title": ""}]}) == [
        {"title": "x", "detail": "", "hotel": "", "question": "", "impact": "", "kind": "info"}]


async def test_overview_and_hotel_context():
    from mcp.server.mcpserver import MCPServer
    from mcp_types import CallToolResult, TextContent

    server = MCPServer("toy")

    @server.tool()
    async def get_overview(hotel: str | None = None) -> CallToolResult:
        """Key figures."""
        payload = {"hotels": [{"hotel_code": hotel or "ALL", "occupancy_today": 0.78}]}
        return CallToolResult(content=[TextContent(type="text", text="{}")], structured_content=payload)

    client = FakeClient(text_reply("Done."))
    app = create_app(Settings(mcp_url="unused", conversations_db=":memory:"), client, server)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as http:
        r = await http.get("/api/overview", params={"hotel": "FRA"})
        assert r.json()["hotels"][0]["hotel_code"] == "FRA"
        assert (await http.get("/api/overview", params={"hotel": "x;y"})).status_code == 422
        await http.post("/api/chat", json={"message": "How is today?", "hotel": "FRA"})
    assert "hotel FRA selected" in client.messages.requests[0]["system"]
