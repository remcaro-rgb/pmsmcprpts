"""Saved reports: a question kept to ask again on fresh data, from the sidebar or by email every
day, week or month (with its charts and files attached)."""

import asyncio
import html
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .conversations import Conversation, ConversationStore
from .digest import send_email
from .loop import ChatAgent

log = logging.getLogger(__name__)

SCHEDULES = ("none", "daily", "weekly", "monthly")
BULLET = re.compile(r"^\s*([-*•]|\d+[.)])\s+")

TEXT = {
    "en": {"subject": "{title} · {date}", "open": "Open Hotel Super Intelligence",
           "footer": "A saved report, sent {when}. Change it or stop it in the website's sidebar.",
           "daily": "every day", "weekly": "every week", "monthly": "on the 1st of every month", "none": "on request",
           "attached": "Attached: {files}."},
    "es": {"subject": "{title} · {date}", "open": "Abrir Hotel Super Intelligence",
           "footer": "Un reporte guardado, enviado {when}. Cámbialo o detenlo en la barra lateral del sitio.",
           "daily": "cada día", "weekly": "cada semana", "monthly": "el día 1 de cada mes", "none": "a pedido",
           "attached": "Adjuntos: {files}."},
}


def strip_suggestions(text: str) -> str:
    at = text.rfind("```suggestions")
    return text[:at].rstrip() if at >= 0 else text


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)


def markdown_html(text: str) -> str:
    """The Markdown the assistant writes (paragraphs, headings, lists, tables, bold) as email HTML."""
    out: list[str] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        if all(ln.strip().startswith("|") for ln in lines) and len(lines) >= 2:
            rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
            rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c) for c in r)]
            head, *body = rows
            th = "".join(f'<th style="text-align:left;padding:6px 10px;border-bottom:1px solid #e7e5e4;'
                         f'color:#78716c;font-size:13px">{_inline(c)}</th>' for c in head)
            trs = "".join("<tr>" + "".join(f'<td style="padding:6px 10px;border-bottom:1px solid #f0efed;'
                                           f'font-size:14px">{_inline(c)}</td>' for c in r) + "</tr>" for r in body)
            out.append(f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:8px 0">'
                       f"<tr>{th}</tr>{trs}</table>")
        elif all(BULLET.match(ln) for ln in lines):
            items = "".join(f"<li>{_inline(BULLET.sub('', ln))}</li>" for ln in lines)
            out.append(f'<ul style="margin:8px 0;padding-left:20px">{items}</ul>')
        elif lines[0].startswith("#"):
            out.append(f'<h3 style="font-size:16px;margin:14px 0 4px">{_inline(lines[0].lstrip("# "))}</h3>')
            if lines[1:]:
                out.append(f'<p style="margin:8px 0">{"<br>".join(_inline(ln) for ln in lines[1:])}</p>')
        else:
            out.append(f'<p style="margin:8px 0">{"<br>".join(_inline(ln) for ln in lines)}</p>')
    return "\n".join(out)


async def run_report(agent: ChatAgent, settings: Settings, owner: str | None,
                     report: dict[str, Any]) -> tuple[str, list[tuple[str, str, bytes]]]:
    """Asks the report's question on today's data, as its owner: the answer's text and its files."""
    conv = Conversation(f"report_{report['id']}", owner)
    texts: list[str] = []
    files: list[tuple[str, str, bytes]] = []
    error = None
    async with conv.lock:
        async for ev in agent.run_turn(conv, report["question"], owner, report["language"], report["hotel"]):
            data = ev["data"]
            if ev["event"] == "text":
                texts.append(data["text"])
            elif ev["event"] == "tool_result" and not data.get("is_error"):
                info = data["result"].get("file") if isinstance(data["result"], dict) else None
                path = Path(settings.artifacts_dir) / str(info.get("file_id", "")) if info else None
                if path and re.fullmatch(r"[0-9a-f]{32}", path.name) and path.is_file():
                    meta = json.loads((path.parent / f"{path.name}.json").read_text())
                    files.append((meta["filename"], meta["mime"], path.read_bytes()))
            elif ev["event"] in ("error", "refusal"):
                error = data.get("message")
    if error and not texts:
        raise RuntimeError(error)
    return strip_suggestions("".join(texts)), files


def render(report: dict[str, Any], answer: str, files: list[tuple[str, str, bytes]], site_url: str,
           today: str) -> tuple[str, str, str]:
    t = TEXT.get(report["language"], TEXT["en"])
    subject = t["subject"].format(title=report["title"], date=today)
    footer = t["footer"].format(when=t[report["schedule"]])
    attached = t["attached"].format(files=", ".join(f[0] for f in files)) if files else ""
    text = f"{report['title']}\n\n{answer}\n\n{attached}\n\n{t['open']}: {site_url}\n\n{footer}".replace("\n\n\n", "\n\n")
    body = f"""<!doctype html><html><body style="margin:0;background:#eceae7;font-family:Inter,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1c1917">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#eceae7;padding:24px 0"><tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:16px;padding:24px"><tr><td style="font-size:15px;line-height:1.5">
<div style="font-size:15px;font-weight:700;margin-bottom:14px"><span style="display:inline-block;background:#1d4ed8;color:#fff;border-radius:8px;padding:4px 7px;margin-right:8px;font-size:13px">HS</span>Hotel Super Intelligence</div>
<div style="font-size:20px;font-weight:700">{html.escape(report["title"])}</div>
<div style="font-size:13px;color:#78716c;margin-bottom:8px">{html.escape(today)}</div>
{markdown_html(answer)}
{f'<p style="font-size:13px;color:#57534e">📎 {html.escape(attached)}</p>' if attached else ""}
<div style="text-align:center;margin:20px 0 6px"><a href="{html.escape(site_url)}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:600;border-radius:10px;padding:11px 20px">{html.escape(t["open"])}</a></div>
<div style="font-size:12px;color:#78716c;text-align:center;margin-top:14px">{html.escape(footer)}</div>
</td></tr></table></td></tr></table></body></html>"""
    return subject, text, body


class Reports:
    """Runs saved reports and emails them; `run_due` sends today's scheduled ones."""

    def __init__(self, settings: Settings, store: ConversationStore, agent: ChatAgent, zone, sender=None):
        self.settings = settings
        self.store = store
        self.agent = agent
        self.zone = zone
        self.sender = sender  # replaces send_email (tests)

    @property
    def available(self) -> bool:
        return bool(self.settings.smtp_host)

    async def send(self, owner: str, report: dict[str, Any]) -> str:
        """Runs the report now and emails it to its owner; returns the subject."""
        answer, files = await run_report(self.agent, self.settings, owner, report)
        today = datetime.now(self.zone).date().isoformat()
        subject, text, body = render(report, answer, files, self.settings.site_url, today)
        await asyncio.to_thread(self.sender or send_email, self.settings, owner, subject, text, body, files)
        return subject

    async def run_due(self) -> int:
        now = datetime.now(self.zone)
        today = now.date().isoformat()
        sent = 0
        for owner, report in self.store.due_reports(today, now.weekday(), now.day):
            try:
                await self.send(owner, report)
                self.store.update_report(owner, report["id"], last_run=today)
                sent += 1
            except Exception:
                log.exception("report %s for %s failed", report["id"], owner)
        return sent
