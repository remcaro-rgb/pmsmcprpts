from datetime import datetime
from zoneinfo import ZoneInfo

import httpx2
import pytest

from fakes import FakeClient, text_reply
from pms_agent.app import create_app
from pms_agent.config import Settings
from pms_agent.conversations import ConversationStore
from pms_agent.loop import ChatAgent
from pms_agent.reports import Reports, markdown_html, render, strip_suggestions
from test_loop import toy_server

pytestmark = pytest.mark.anyio
ANN = {"x-pms-user": "ann@hotel.example"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_saved_reports_api():
    app = create_app(Settings(mcp_url="unused", conversations_db=":memory:"), FakeClient(), toy_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as http:
        r = await http.post("/api/reports", headers=ANN, json={
            "title": "Weekly KPIs", "question": "How did Fragata do last week?", "hotel": "fra", "language": "es"})
        assert r.status_code == 201
        report = r.json()
        assert report["hotel"] == "FRA" and report["schedule"] == "none"
        # Emailing on a schedule needs SMTP.
        r = await http.patch(f"/api/reports/{report['id']}", headers=ANN, json={"schedule": "weekly"})
        assert r.status_code == 400
        listed = (await http.get("/api/reports", headers=ANN)).json()
        assert [x["title"] for x in listed["reports"]] == ["Weekly KPIs"] and listed["scheduling_available"] is False
        # Someone else doesn't see or change it.
        bob = {"x-pms-user": "bob@hotel.example"}
        assert (await http.get("/api/reports", headers=bob)).json()["reports"] == []
        assert (await http.delete(f"/api/reports/{report['id']}", headers=bob)).status_code == 404
        r = await http.patch(f"/api/reports/{report['id']}", headers=ANN, json={"title": "KPIs of the week"})
        assert r.json()["title"] == "KPIs of the week"
        assert (await http.post(f"/api/reports/{report['id']}/send", headers=ANN)).status_code == 503
        assert (await http.delete(f"/api/reports/{report['id']}", headers=ANN)).status_code == 204

    app = create_app(Settings(mcp_url="unused", conversations_db=":memory:", smtp_host="smtp.example"),
                     FakeClient(), toy_server())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://t") as http:
        r = await http.post("/api/reports", headers=ANN, json={
            "title": "Daily", "question": "q", "schedule": "weekly", "weekday": 4})
        assert r.status_code == 201 and r.json()["weekday"] == 4
        assert (await http.post("/api/reports", json={"title": "x", "question": "q", "schedule": "daily"})).status_code == 400


async def test_due_reports_run_and_are_emailed_once():
    sent = []
    store = ConversationStore(":memory:")
    answer = "**Occupancy** rose.\n\n| Month | Occupancy |\n|---|---|\n| Oct | 78% |\n\n```suggestions\n- More\n```"
    client = FakeClient(text_reply(answer), text_reply(answer))
    settings = Settings(mcp_url="unused", smtp_host="smtp.example", site_url="https://hotel.example")
    agent = ChatAgent(settings, client, toy_server())
    zone = ZoneInfo("UTC")
    reports = Reports(settings, store, agent, zone, sender=lambda *a: sent.append(a))
    today = datetime.now(zone)
    store.create_report("ann@hotel.example", "Every day", "How is it going?", "FRA", "en", "daily")
    store.create_report("ann@hotel.example", "Another day", "q", None, "en", "weekly", (today.weekday() + 1) % 7)
    store.create_report("ann@hotel.example", "On request", "q", None, "en", "none")
    assert await reports.run_due() == 1
    assert await reports.run_due() == 0  # not twice on the same day
    _, to, subject, text, body, files = sent[0]
    assert to == "ann@hotel.example" and subject.startswith("Every day · ")
    assert "suggestions" not in text and "<b>Occupancy</b>" in body and "<td" in body and files == []
    # The question went to the model with the report's hotel and language.
    assert "hotel FRA selected" in client.messages.requests[0]["system"]


def test_markdown_html_and_render():
    assert strip_suggestions("Done.\n\n```suggestions\n- x\n```") == "Done."
    html = markdown_html("# Title\nLine\n\n- one\n- **two**\n\n| a | b |\n|---|---|\n| 1 | <2> |")
    assert "<h3" in html and "<li><b>two</b></li>" in html and "&lt;2&gt;" in html and "|---" not in html
    report = {"title": "KPIs <weekly>", "language": "es", "schedule": "weekly"}
    subject, text, body = render(report, "Todo bien.", [("chart.png", "image/png", b"x")], "https://h.example", "2026-10-26")
    assert subject == "KPIs <weekly> · 2026-10-26" and "KPIs &lt;weekly&gt;" in body
    assert "Adjuntos: chart.png." in text and "cada semana" in body


def test_attachments(monkeypatch):
    from pms_agent import digest

    messages = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context):
            pass

        def send_message(self, msg):
            messages.append(msg)

    monkeypatch.setattr(digest.smtplib, "SMTP", FakeSMTP)
    digest.send_email(Settings(mcp_url="unused", smtp_host="smtp.example"), "a@b.c", "S", "t", "<p>h</p>",
                      [("kpis.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK")])
    msg = messages[0]
    assert msg.get_content_type() == "multipart/mixed"
    assert [p.get_filename() for p in msg.iter_attachments()] == ["kpis.xlsx"]
