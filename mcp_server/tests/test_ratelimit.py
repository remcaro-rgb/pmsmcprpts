import httpx2
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from pms_mcp.ratelimit import RateLimitMiddleware, Rule


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def make_client(clock, **kwargs):
    app = Starlette(routes=[Route("/{path:path}", lambda r: PlainTextResponse("ok"), methods=["GET", "POST"])])
    limited = RateLimitMiddleware(app, rules=(Rule("auth", ("/token",), limit=2, window=60),), clock=clock, **kwargs)
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=limited, client=("10.0.0.1", 1)),
                              base_url="http://test")


@pytest.mark.anyio
async def test_limits_per_client_and_window():
    clock = Clock()
    async with make_client(clock) as http:
        assert (await http.post("/token")).status_code == 200
        assert (await http.post("/token")).status_code == 200
        r = await http.post("/token")
        assert r.status_code == 429 and r.headers["retry-after"] == "61"
        assert "Too many requests" in r.json()["error_description"]
        assert (await http.get("/other")).status_code == 200  # unlimited path
        clock.now += 61
        assert (await http.post("/token")).status_code == 200


@pytest.mark.anyio
async def test_forwarded_for_only_when_trusted_and_service_token_exempt():
    clock = Clock()
    async with make_client(clock, trust_proxy=True, service_token="s" * 40) as http:
        for ip in ("1.1.1.1", "1.1.1.1"):
            assert (await http.post("/token", headers={"x-forwarded-for": f"{ip}, 172.18.0.5"})).status_code == 200
        assert (await http.post("/token", headers={"x-forwarded-for": "1.1.1.1"})).status_code == 429
        assert (await http.post("/token", headers={"x-forwarded-for": "2.2.2.2"})).status_code == 200
        for _ in range(5):
            assert (await http.post("/token", headers={"authorization": "Bearer " + "s" * 40})).status_code == 200
    async with make_client(clock) as http:  # untrusted: the header is ignored, the socket address counts
        await http.post("/token", headers={"x-forwarded-for": "3.3.3.3"})
        await http.post("/token", headers={"x-forwarded-for": "4.4.4.4"})
        assert (await http.post("/token", headers={"x-forwarded-for": "5.5.5.5"})).status_code == 429
