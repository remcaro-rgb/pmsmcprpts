"""Value formats shared by charts and documents, inferred from column names and types."""

import math
import re
from datetime import date
from typing import Any, Literal

from .i18n import Lang, fmt_date

Kind = Literal["percent", "currency", "integer", "decimal", "date", "text"]
KINDS = ("percent", "currency", "integer", "decimal", "date", "text")

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERCENT_NAMES = re.compile(r"(occupancy|_rate$|^rate_pct$|_pct$|share|ratio)")
CURRENCY_NAMES = re.compile(r"(^rate$|adr|revpar|revenue|spend|amount|price|charges?$|^total$)")
INTEGER_TYPES = {"int2", "int4", "int8"}
NUMERIC_TYPES = INTEGER_TYPES | {"numeric", "float4", "float8"}
CURRENCY_SYMBOL = "€"


def infer_kind(name: str, pg_type: str, values: list[Any]) -> Kind:
    sample = [v for v in values[:50] if v is not None]
    if pg_type in ("date", "timestamp", "timestamptz") or (sample and all(
            isinstance(v, str) and ISO_DATE.match(v) for v in sample)):
        return "date"
    if pg_type in NUMERIC_TYPES or (sample and all(isinstance(v, (int, float)) for v in sample)):
        lname = name.lower()
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


def format_value(value: Any, kind: Kind, lang: Lang = "en") -> str:
    """Full-precision display value (tables, tooltips, KPI tiles)."""
    if value is None:
        return "—"
    if kind == "percent":
        return f"{value * 100:.1f}%"
    if kind == "currency":
        return f"{CURRENCY_SYMBOL}{value:,.0f}" if abs(value) >= 10_000 else f"{CURRENCY_SYMBOL}{value:,.2f}"
    if kind == "integer":
        return f"{value:,.0f}"
    if kind == "decimal":
        return f"{value:,.2f}"
    if kind == "date":
        d = to_date(value)
        return fmt_date(d, "day", lang) if d else str(value)
    return str(value)


def format_headline(value: Any, kind: Kind, lang: Lang = "en") -> str:
    """Display value for KPI tiles: large money and counts compacted (€11.1M) so they fit."""
    if isinstance(value, (int, float)) and abs(value) >= 100_000 and kind in ("currency", "integer", "decimal"):
        return (CURRENCY_SYMBOL if kind == "currency" else "") + compact(value)
    return format_value(value, kind, lang)


def compact(value: float) -> str:
    """1,284 -> 1.3K, 4,200,000 -> 4.2M (axis ticks)."""
    a = abs(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= limit:
            text = f"{value / limit:.1f}".rstrip("0").rstrip(".")
            return text + suffix
    return f"{value:g}" if not float(value).is_integer() else f"{value:.0f}"


def format_tick(value: float, kind: Kind, step: float) -> str:
    if kind == "percent":
        decimals = 0 if step >= 0.01 else 1
        return f"{value * 100:.{decimals}f}%"
    if kind == "currency":
        return CURRENCY_SYMBOL + compact(value)
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
