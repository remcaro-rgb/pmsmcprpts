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
              "question": "Show pace"} for i in range(n)]
    return tool_calls(("s1", SUBMIT, {"recommendations": items}))


async def test_made_once_a_day_and_trimmed_to_three():
    # Prose without the tool gets a nudge; then four come back and three are kept.
    client = FakeClient(text_reply("Here they are."), submit(4))
    app = create_app(Settings(mcp_url="unused", conversations_db=":memory:", timezone="Mars/Base"),
                     client, toy_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as http:
        r = await http.get("/api/recommendations", params={"language": "es"})
        assert r.status_code == 200 and len(r.json()["recommendations"]) == 3
        assert r.json()["recommendations"][0]["hotel"] == "Fragata"
        again = await http.get("/api/recommendations", params={"language": "es"})
        assert again.json() == r.json()  # cached: no more requests to Claude
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
        {"title": "x", "detail": "", "hotel": "", "question": ""}]
