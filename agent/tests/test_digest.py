from datetime import datetime
from zoneinfo import ZoneInfo

import httpx2
import pytest
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent

from fakes import FakeClient, tool_calls
from pms_agent import digest as digest_module
from pms_agent.app import create_app
from pms_agent.config import Settings
from pms_agent.digest import Digest, alerts, money, render
from pms_agent.recommend import SUBMIT

pytestmark = pytest.mark.anyio

HOTEL = {
    "hotel_code": "FRA", "name": "Fragata <Cartagena>", "currency": "COP", "today": "2026-10-24",
    "occupancy_today": 0.784, "occupancy_today_change_pp": -0.061, "arrivals_today": 14, "departures_today": 9,
    "adr_period": 412300, "adr_period_change": 0.082, "revpar_period": 318900, "revpar_period_change": 0.125,
    "revenue_period": 186_400_000, "revenue_period_change": -0.12, "occupancy_next_30": 0.612,
    "revenue_next_30": 527_000_000, "series": {},
    "alerts": [{"key": "occupancy_today", "value": -0.061}, {"key": "revenue", "value": -0.12}],
}
RECS = [{"title": "Raise the holiday rate", "detail": "92% booked.", "hotel": "Fragata", "question": "q",
         "impact": "+COP 9.8 M", "kind": "money"}]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_money_and_alerts():
    assert money(412300, "COP") == "COP 412,300"
    assert money(186_400_000, "COP") == "COP 186.4 M"
    assert money(147.2, "EUR") == "€147"
    assert money(527_000, "EUR", 100_000) == "€527K"
    assert alerts(HOTEL, "en") == ["occupancy today is −6.1 pp against the same day last year.",
                                   "room revenue this month is −12.0% against last year."]
    assert alerts({**HOTEL, "alerts": []}, "es") == []
    assert alerts({**HOTEL, "alerts": [{"key": "next_30", "value": 0.42}]}, "es") == [
        "solo está reservado el 42.0% de los próximos 30 días."]


def test_render_in_spanish_escapes_and_has_every_part():
    subject, text, body = render(HOTEL, RECS, "es", "Manuel", "https://hotel.example", "07:00")
    assert subject == "Fragata <Cartagena> hoy: 78.4% de ocupación y 1 recomendaciones"
    assert "Buenos días, Manuel" in text and "sábado 24 de octubre" in text
    assert "Fragata &lt;Cartagena&gt;" in body and "<Cartagena>" not in body  # escaped in the HTML
    assert "COP 412,300" in body and "+8.2% vs 2025" in body and "COP 527 M reservados" in body
    assert "Alerta:" in body and "Raise the holiday rate" in body and 'href="https://hotel.example"' in body
    assert "07:00" in text


def test_next_run():
    d = Digest(Settings(mcp_url="unused", digest_time="07:30"), None, None,
               type("D", (), {"zone": ZoneInfo("UTC")})())
    zone = ZoneInfo("UTC")
    assert d.next_run(datetime(2026, 10, 24, 6, 0, tzinfo=zone)) == datetime(2026, 10, 24, 7, 30, tzinfo=zone)
    assert d.next_run(datetime(2026, 10, 24, 8, 0, tzinfo=zone)) == datetime(2026, 10, 25, 7, 30, tzinfo=zone)
    d.settings = Settings(mcp_url="unused", digest_time="bad")
    assert d.next_run(datetime(2026, 10, 24, 6, 0, tzinfo=zone)).hour == 7


def overview_server() -> MCPServer:
    server = MCPServer("toy")

    @server.tool()
    async def get_overview(hotel: str | None = None) -> CallToolResult:
        """Key figures."""
        return CallToolResult(content=[TextContent(type="text", text="{}")], structured_content={"hotels": [HOTEL]})

    return server


async def test_prefs():
    settings = Settings(mcp_url="unused", conversations_db=":memory:", smtp_host="smtp.example")
    app = create_app(settings, FakeClient(), overview_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as http:
        # Without sign-in there's no address to send to.
        assert (await http.get("/api/prefs")).json()["digest_available"] is False
        me = {"x-pms-user": "ann@hotel.example"}
        assert (await http.get("/api/prefs", headers=me)).json() == {
            "digest": False, "language": "en", "hotel": None, "digest_available": True, "digest_time": "07:00"}
        r = await http.put("/api/prefs", headers=me, json={"digest": True, "language": "es", "hotel": "fra"})
        assert r.json()["digest"] is True and r.json()["hotel"] == "FRA" and r.json()["language"] == "es"
        assert (await http.put("/api/prefs", json={"digest": True})).status_code == 400
    # Without SMTP the daily email isn't offered.
    app = create_app(Settings(mcp_url="unused", conversations_db=":memory:"), FakeClient(), overview_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as http:
        assert (await http.get("/api/prefs", headers={"x-pms-user": "a@b.c"})).json()["digest_available"] is False


async def test_digest_sends_once_a_day():
    sent = []
    from pms_agent.conversations import ConversationStore
    from pms_agent.loop import ChatAgent
    from pms_agent.recommend import DailyRecommendations, Overviews

    settings = Settings(mcp_url="unused", smtp_host="smtp.example", site_url="https://hotel.example")
    agent = ChatAgent(settings, FakeClient(tool_calls(("s1", SUBMIT, {"recommendations": RECS}))), overview_server())
    store = ConversationStore(":memory:")
    store.set_prefs("ann@hotel.example", digest=True, language="es", hotel="FRA")
    store.set_prefs("bob@hotel.example", digest=False)

    async def names(email):
        return "Ann"

    d = Digest(settings, store, Overviews(agent), DailyRecommendations(agent, "UTC"), names=names,
               sender=lambda *a: sent.append(a))
    assert await d.send_all() == 1
    assert await d.send_all() == 0  # not twice on the same day
    (_, to, subject, text, body), = sent
    assert to == "ann@hotel.example" and subject.startswith("Fragata <Cartagena> hoy")
    assert "Buenos días, Ann" in text and "Raise the holiday rate" in body


async def test_test_email_endpoint(monkeypatch):
    sent = []
    monkeypatch.setattr(digest_module, "send_email", lambda *a: sent.append(a))
    client = FakeClient(tool_calls(("s1", SUBMIT, {"recommendations": RECS})))
    settings = Settings(mcp_url="unused", conversations_db=":memory:", smtp_host="smtp.example")
    app = create_app(settings, client, overview_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as http:
        assert (await http.post("/api/digest/test", json={"language": "en"})).status_code == 503  # not signed in
        r = await http.post("/api/digest/test", headers={"x-pms-user": "ann@hotel.example"}, json={"language": "en"})
        assert r.status_code == 204
    assert sent[0][1] == "ann@hotel.example" and "Good morning" in sent[0][3]


def test_send_email_over_smtp(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context):
            calls.append("starttls")

        def login(self, user, password):
            calls.append(("login", user))

        def send_message(self, msg):
            calls.append(("send", msg["To"], msg["From"], msg.get_content_type()))

    monkeypatch.setattr(digest_module.smtplib, "SMTP", FakeSMTP)
    settings = Settings(mcp_url="unused", smtp_host="smtp.example", smtp_user="me@example.com",
                        smtp_password="secret", smtp_from="Hotel <hi@example.com>")
    digest_module.send_email(settings, "ann@hotel.example", "Subject", "text", "<p>html</p>")
    assert calls == [("connect", "smtp.example", 587), "starttls", ("login", "me@example.com"),
                     ("send", "ann@hotel.example", "Hotel <hi@example.com>", "multipart/alternative")]
    assert "secret" not in repr(settings)
