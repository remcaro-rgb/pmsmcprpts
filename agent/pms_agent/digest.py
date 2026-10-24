"""The daily email: each subscriber's key figures, alerts and the day's three recommendations,
sent through SMTP at PMS_DIGEST_TIME (in PMS_TIMEZONE) to the users who turn it on."""

import asyncio
import html
import logging
import smtplib
import ssl
from datetime import date, datetime
from email.message import EmailMessage
from typing import Any

from .config import Settings
from .conversations import ConversationStore
from .recommend import DailyRecommendations, Overviews
from .scheduler import next_run

log = logging.getLogger(__name__)

# Alerts: a change against the same days a year earlier at or past these.
ALERT_OCCUPANCY_PP = -0.05
ALERT_ADR = -0.05
ALERT_REVENUE = -0.10

TEXT = {
    "en": {
        "subject": "{hotel} today: {occupancy} occupancy and {n} recommendations",
        "hello": "Good morning, {name}",
        "hello_anon": "Good morning",
        "summary": "Summary of {hotel} for {date}.",
        "kpis": [("Occupancy today", "occupancy"), ("Arrivals · Departures", "moves"), ("ADR this month", "adr"),
                 ("RevPAR this month", "revpar"), ("Room revenue this month", "revenue"), ("Booked next 30 days", "next30")],
        "vs": "vs {year}",
        "today": "today",
        "on_books": "{money} on the books",
        "alert": "Alert",
        "alert_occupancy": "occupancy today is {change} against the same day last year.",
        "alert_adr": "ADR this month is {change} against last year.",
        "alert_revenue": "room revenue this month is {change} against last year.",
        "recommendations": "Today's recommendations",
        "open": "Open Hotel Super Intelligence",
        "footer": "You get this email every morning at {time}. Turn it off in the website's account menu.",
        "months": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                   "October", "November", "December"],
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "date": "{day}, {month} {d}",
    },
    "es": {
        "subject": "{hotel} hoy: {occupancy} de ocupación y {n} recomendaciones",
        "hello": "Buenos días, {name}",
        "hello_anon": "Buenos días",
        "summary": "Resumen de {hotel} para el {date}.",
        "kpis": [("Ocupación hoy", "occupancy"), ("Llegadas · Salidas", "moves"), ("ADR del mes", "adr"),
                 ("RevPAR del mes", "revpar"), ("Ingresos del mes", "revenue"), ("Reservado 30 días", "next30")],
        "vs": "vs {year}",
        "today": "hoy",
        "on_books": "{money} reservados",
        "alert": "Alerta",
        "alert_occupancy": "la ocupación de hoy está {change} frente al mismo día del año pasado.",
        "alert_adr": "el ADR del mes está {change} frente al año pasado.",
        "alert_revenue": "los ingresos por habitaciones del mes están {change} frente al año pasado.",
        "recommendations": "Recomendaciones del día",
        "open": "Abrir Hotel Super Intelligence",
        "footer": "Recibes este correo cada mañana a las {time}. Desactívalo en el menú de tu cuenta en el sitio.",
        "months": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                   "octubre", "noviembre", "diciembre"],
        "days": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
        "date": "{day} {d} de {month}",
    },
}

MINUS = "−"
SYMBOLS = {"EUR": "€", "GBP": "£"}


def pct(v: float | None) -> str:
    return "–" if v is None else f"{v * 100:.1f}%"


def signed(v: float | None, unit: str) -> str | None:
    if v is None:
        return None
    n = abs(v * 100)
    return f"{MINUS if v < 0 else '+'}{n:.1f}{unit}"


def money(v: float | None, currency: str, short_from: float = 1_000_000) -> str:
    if v is None:
        return "–"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= short_from:
        short = lambda x: f"{x:.1f}".removesuffix(".0")  # noqa: E731
        text = f"{short(v / 1_000_000)} M" if v >= 1_000_000 else f"{short(v / 1000)}K"
    else:
        text = f"{v:,.0f}"
    symbol = SYMBOLS.get(currency)
    return f"{sign}{symbol}{text}" if symbol else f"{sign}{currency} {text}"


def long_date(day: str, language: str) -> str:
    d = date.fromisoformat(day)
    t = TEXT[language]
    return t["date"].format(day=t["days"][d.weekday()], month=t["months"][d.month - 1], d=d.day)


def alerts(h: dict[str, Any], language: str) -> list[str]:
    """Plain-language alerts for figures well below last year's."""
    t, out = TEXT[language], []
    if (c := h.get("occupancy_today_change_pp")) is not None and c <= ALERT_OCCUPANCY_PP:
        out.append(t["alert_occupancy"].format(change=signed(c, " pp")))
    if (c := h.get("adr_month_change")) is not None and c <= ALERT_ADR:
        out.append(t["alert_adr"].format(change=signed(c, "%")))
    if (c := h.get("revenue_month_change")) is not None and c <= ALERT_REVENUE:
        out.append(t["alert_revenue"].format(change=signed(c, "%")))
    return out


def tiles(h: dict[str, Any], language: str) -> list[tuple[str, str, str | None, str]]:
    """(label, value, sub, tone) for each key figure."""
    t = TEXT[language]
    year = int(h["today"][:4]) - 1
    cur = h["currency"]

    def vs(change: str | None) -> str | None:
        return f"{change} {t['vs'].format(year=year)}" if change else None

    def tone(v: float | None) -> str:
        return "flat" if not v else "up" if v > 0 else "down"

    values = {
        "occupancy": (pct(h.get("occupancy_today")), vs(signed(h.get("occupancy_today_change_pp"), " pp")),
                      tone(h.get("occupancy_today_change_pp"))),
        "moves": (f"{h.get('arrivals_today') or 0} · {h.get('departures_today') or 0}", t["today"], "flat"),
        "adr": (money(h.get("adr_month"), cur), vs(signed(h.get("adr_month_change"), "%")), tone(h.get("adr_month_change"))),
        "revpar": (money(h.get("revpar_month"), cur), vs(signed(h.get("revpar_month_change"), "%")),
                   tone(h.get("revpar_month_change"))),
        "revenue": (money(h.get("revenue_month"), cur), vs(signed(h.get("revenue_month_change"), "%")),
                    tone(h.get("revenue_month_change"))),
        "next30": (pct(h.get("occupancy_next_30")),
                   t["on_books"].format(money=money(h.get("revenue_next_30"), cur, 100_000)), "flat"),
    }
    return [(label, *values[key]) for label, key in t["kpis"]]


def render(h: dict[str, Any], recs: list[dict[str, Any]], language: str, name: str | None,
           site_url: str, send_time: str) -> tuple[str, str, str]:
    """The email's subject, plain text and HTML (inline styles, tables: what email apps render)."""
    t = TEXT[language]
    e = html.escape
    subject = t["subject"].format(hotel=h["name"], occupancy=pct(h.get("occupancy_today")), n=len(recs))
    hello = t["hello"].format(name=name) if name else t["hello_anon"]
    summary = t["summary"].format(hotel=h["name"], date=long_date(h["today"], language))
    figures = tiles(h, language)
    warn = alerts(h, language)

    text = [hello, summary, ""]
    text += [f"- {label}: {value}" + (f" ({sub})" if sub else "") for label, value, sub, _ in figures]
    text += [""] + [f"{t['alert']}: {a}" for a in warn]
    text += ["", t["recommendations"]]
    text += [f"{i}. {r['title']}" + (f" ({r['impact']})" if r.get("impact") else "") + f"\n   {r['detail']}"
             for i, r in enumerate(recs, 1)]
    text += ["", f"{t['open']}: {site_url}", "", t["footer"].format(time=send_time)]

    colors = {"up": ("#ecfdf3", "#15803d"), "down": ("#fef2f2", "#b91c1c"), "flat": ("#f5f5f4", "#57534e")}
    kinds = {"money": ("#ecfdf3", "#15803d"), "risk": ("#fff7ed", "#b45309"), "info": ("#f5f5f4", "#57534e")}
    cells = []
    for label, value, sub, tone in figures:
        bg, fg = colors[tone]
        badge = (f'<span style="background:{bg};color:{fg};border-radius:6px;padding:1px 6px;font-size:12px;'
                 f'font-weight:600">{e(sub)}</span>') if sub else ""
        cells.append(f'<td width="33%" style="padding:5px;vertical-align:top"><div style="border:1px solid #e7e5e4;'
                     f'border-radius:12px;padding:10px 12px"><div style="font-size:12px;color:#78716c">{e(label)}</div>'
                     f'<div style="font-size:19px;font-weight:700;color:#1c1917;margin:2px 0 4px">{e(value)}</div>'
                     f'{badge}</div></td>')
    rows = "".join(f"<tr>{''.join(cells[i:i + 3])}</tr>" for i in range(0, len(cells), 3))
    alert_html = "".join(
        f'<div style="margin:14px 0 0;padding:10px 12px;background:#fef2f2;border-radius:10px;color:#7f1d1d;'
        f'font-size:14px"><b>{e(t["alert"])}:</b> {e(a)}</div>' for a in warn)
    rec_html = ""
    for i, r in enumerate(recs, 1):
        bg, fg = kinds.get(r.get("kind", "info"), kinds["info"])
        impact = (f' <span style="background:{bg};color:{fg};border-radius:999px;padding:1px 8px;font-size:12px;'
                  f'font-weight:600">{e(r["impact"])}</span>') if r.get("impact") else ""
        rec_html += (f'<tr><td style="padding:10px 10px 10px 0;vertical-align:top;border-top:1px solid #f0efed">'
                     f'<div style="width:24px;height:24px;border-radius:12px;background:#2563eb;color:#fff;'
                     f'font-size:12px;font-weight:700;text-align:center;line-height:24px">{i}</div></td>'
                     f'<td style="padding:10px 0;border-top:1px solid #f0efed"><b style="color:#1c1917">'
                     f'{e(r["title"])}</b>{impact}<div style="font-size:14px;color:#44403c;margin-top:3px">'
                     f'{e(r["detail"])}</div></td></tr>')
    body = f"""<!doctype html><html><body style="margin:0;background:#eceae7;font-family:Inter,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#eceae7;padding:24px 0"><tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%;background:#ffffff;border-radius:16px;padding:24px">
<tr><td>
<div style="font-size:15px;font-weight:700;color:#1c1917;margin-bottom:14px"><span style="display:inline-block;background:#1d4ed8;color:#fff;border-radius:8px;padding:4px 7px;margin-right:8px;font-size:13px">HS</span>Hotel Super Intelligence</div>
<div style="font-size:21px;font-weight:700;color:#1c1917">{e(hello)}</div>
<div style="font-size:15px;color:#78716c;margin:2px 0 12px">{e(summary)}</div>
<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
{alert_html}
<div style="font-size:16px;font-weight:700;color:#1c1917;margin:20px 0 4px">{e(t["recommendations"])}</div>
<table width="100%" cellpadding="0" cellspacing="0">{rec_html}</table>
<div style="text-align:center;margin:20px 0 6px"><a href="{e(site_url)}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:600;border-radius:10px;padding:11px 20px">{e(t["open"])}</a></div>
<div style="font-size:12px;color:#78716c;text-align:center;margin-top:14px">{e(t["footer"].format(time=send_time))}</div>
</td></tr></table></td></tr></table></body></html>"""
    return subject, "\n".join(text), body


def send_email(settings: Settings, to: str, subject: str, text: str, body: str) -> None:
    """Sends one email through the configured SMTP server (blocking: run it in a thread)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user or "hotel-super-intelligence@localhost"
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    context = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=30)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with server:
        if settings.smtp_security == "starttls":
            server.starttls(context=context)
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password or "")
        server.send_message(msg)


class Digest:
    """Builds and sends the daily email; `run` sends it every morning."""

    def __init__(self, settings: Settings, store: ConversationStore, overviews: Overviews,
                 daily: DailyRecommendations, names=None, sender=None):
        self.settings = settings
        self.store = store
        self.overviews = overviews
        self.daily = daily
        self.names = names  # async email -> display name, from the user directory
        self.sender = sender  # replaces send_email (tests)
        self.zone = daily.zone

    @property
    def available(self) -> bool:
        return bool(self.settings.smtp_host)

    async def send_to(self, user: str, language: str, hotel: str | None) -> str:
        """Sends one user their email now; returns the subject."""
        hotels = (await self.overviews.get(user, hotel))["hotels"]
        if not hotels:
            raise LookupError("No hotels for this user.")
        h = next((x for x in hotels if x["hotel_code"] == (hotel or "").upper()), hotels[0])
        recs = (await self.daily.get(user, language, h["hotel_code"]))["recommendations"]
        name = await self.names(user) if self.names else None
        subject, text, body = render(h, recs, language, name, self.settings.site_url, self.settings.digest_time)
        await asyncio.to_thread(self.sender or send_email, self.settings, user, subject, text, body)
        return subject

    async def send_all(self) -> int:
        """Today's email to every subscriber that hasn't had it yet."""
        today = datetime.now(self.zone).date().isoformat()
        sent = 0
        for user, prefs in self.store.subscribers():
            if prefs["last_sent"] == today:
                continue
            try:
                await self.send_to(user, prefs["language"], prefs["hotel"])
                self.store.set_prefs(user, last_sent=today)
                sent += 1
            except Exception:
                log.exception("daily email to %s failed", user)
        return sent

    def next_run(self, now: datetime) -> datetime:
        return next_run(now, self.settings.digest_time)
