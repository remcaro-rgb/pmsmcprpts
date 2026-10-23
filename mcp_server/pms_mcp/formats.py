"""Value formats shared by charts and documents, inferred from column names and types."""

import math
import re
from datetime import date
from typing import Any, Literal

from .i18n import Lang, fmt_date

# "points": a difference between two ratios stored as fractions, shown in percentage points
# (occupancy 0.921 - 0.928 = -0.007 -> "-0.7 pts").
Kind = Literal["percent", "points", "currency", "integer", "decimal", "date", "text"]
KINDS = ("percent", "points", "currency", "integer", "decimal", "date", "text")

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
POINTS_NAMES = re.compile(r"(_pts$|_pp$|_points$)")
# English and Spanish column names (Spanish answers often name query columns in Spanish).
PERCENT_NAMES = re.compile(r"(occupancy|_rate$|^rate_pct$|_pct$|share|ratio|ocupaci|tasa|participaci|porcentaje)")
CURRENCY_NAMES = re.compile(r"(^rate$|adr|revpar|revenue|spend|amount|price|charges?$|^total$"
                            r"|ingreso|tarifa|gasto|monto|importe|precio)")
INTEGER_TYPES = {"int2", "int4", "int8"}
NUMERIC_TYPES = INTEGER_TYPES | {"numeric", "float4", "float8"}
# Money is in each hotel's currency (ISO 4217 code). EUR and USD get their symbol, any other
# currency its code and a space ("COP 1,234,000").
DEFAULT_CURRENCY = "EUR"
CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$"}
CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")


def normalize_currency(code: str | None) -> str:
    """Upper-cased ISO 4217 code; ValueError for anything that isn't three letters."""
    code = (code or DEFAULT_CURRENCY).strip().upper()
    if not CURRENCY_CODE.match(code):
        raise ValueError(f"Currency {code!r} is not an ISO 4217 code such as EUR, USD, COP or MXN.")
    return code


def currency_prefix(currency: str = DEFAULT_CURRENCY) -> str:
    """'€' for EUR, '$' for USD, otherwise the code and a space ('COP ')."""
    return CURRENCY_SYMBOLS.get(currency, f"{currency} ")


def infer_kind(name: str, pg_type: str, values: list[Any]) -> Kind:
    sample = [v for v in values[:50] if v is not None]
    if pg_type in ("date", "timestamp", "timestamptz") or (sample and all(
            isinstance(v, str) and ISO_DATE.match(v) for v in sample)):
        return "date"
    # bool is an int subclass: show flags such as fully_actual as Yes/No, not 1/0.
    if pg_type == "bool" or (sample and all(isinstance(v, bool) for v in sample)):
        return "text"
    if pg_type in NUMERIC_TYPES or (sample and all(isinstance(v, (int, float)) for v in sample)):
        lname = name.lower()
        if POINTS_NAMES.search(lname) and all(-1.5 <= v <= 1.5 for v in sample):
            return "points"
        if PERCENT_NAMES.search(lname) and all(-1.5 <= v <= 1.5 for v in sample):
            return "percent"
        if CURRENCY_NAMES.search(lname):
            return "currency"
        if pg_type in INTEGER_TYPES or all(float(v).is_integer() for v in sample):
            return "integer"
        return "decimal"
    return "text"


def to_date(value: Any) -> date | None:
    if isinstance(value, str) and ISO_DATE.match(value):
        return date.fromisoformat(value)
    return None


def format_value(value: Any, kind: Kind, lang: Lang = "en", currency: str = DEFAULT_CURRENCY) -> str:
    """Full-precision display value (tables, tooltips, KPI tiles)."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return ("Sí" if value else "No") if lang == "es" else ("Yes" if value else "No")
    if kind == "percent":
        return f"{value * 100:.1f}%"
    if kind == "points":
        return f"{value * 100:+.1f} {points_unit(lang)}"
    if kind == "currency":
        prefix = currency_prefix(currency)
        return f"{prefix}{value:,.0f}" if abs(value) >= 10_000 else f"{prefix}{value:,.2f}"
    if kind == "integer":
        return f"{value:,.0f}"
    if kind == "decimal":
        return f"{value:,.2f}"
    if kind == "date":
        d = to_date(value)
        return fmt_date(d, "day", lang) if d else str(value)
    return str(value)


def points_unit(lang: Lang) -> str:
    return "pp" if lang == "es" else "pts"


def format_headline(value: Any, kind: Kind, lang: Lang = "en", currency: str = DEFAULT_CURRENCY) -> str:
    """Display value for KPI tiles: large money and counts compacted (€11.1M) so they fit."""
    if isinstance(value, (int, float)) and abs(value) >= 100_000 and kind in ("currency", "integer", "decimal"):
        return (currency_prefix(currency) if kind == "currency" else "") + compact(value)
    return format_value(value, kind, lang, currency)


def compact(value: float) -> str:
    """1,284 -> 1.3K, 4,200,000 -> 4.2M (axis ticks)."""
    a = abs(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= limit:
            text = f"{value / limit:.1f}".rstrip("0").rstrip(".")
            return text + suffix
    return f"{value:g}" if not float(value).is_integer() else f"{value:.0f}"


def format_tick(value: float, kind: Kind, step: float, currency: str = DEFAULT_CURRENCY) -> str:
    if kind in ("percent", "points"):
        decimals = 0 if step >= 0.01 else 1
        return f"{value * 100:.{decimals}f}" + ("%" if kind == "percent" else "")
    if kind == "currency":
        return currency_prefix(currency) + compact(value)
    return compact(value)


def nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    """Round tick values covering [lo, hi] with steps of 1, 2, 2.5 or 5 x 10^k."""
    if hi == lo:
        hi = lo + (abs(lo) or 1)
    raw = (hi - lo) / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t < hi + step * 0.999:
        ticks.append(round(t, 10))
        t += step
    return ticks


def date_labels(values: list[str], lang: Lang = "en") -> tuple[list[str], list[str]]:
    """(short tick labels, full tooltip labels) for a sequence of ISO dates."""
    dates = [to_date(v) for v in values]
    if any(d is None for d in dates):
        return [str(v) for v in values], [str(v) for v in values]
    if all(d.day == 1 for d in dates):
        months = {d.month for d in dates}
        if months <= {1, 4, 7, 10} and len(dates) > 1:
            labels = [fmt_date(d, "quarter", lang) for d in dates]
            return labels, labels
        multi_year = len({d.year for d in dates}) > 1
        short = [fmt_date(d, "month_year_short" if multi_year else "month", lang) for d in dates]
        return short, [fmt_date(d, "month_year", lang) for d in dates]
    return [fmt_date(d, "day_month", lang) for d in dates], [fmt_date(d, "weekday", lang) for d in dates]
