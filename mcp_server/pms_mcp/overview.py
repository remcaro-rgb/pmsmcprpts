"""The home screen's key figures per hotel: today, a period (this month so far by default) and the
next 30 days, each against the same days a year earlier, a short daily series for the small trend
lines, and alerts for figures well below last year's."""

from datetime import date, timedelta
from typing import Any

# Daily rows around each hotel's "today" (its first stay date that isn't an actual yet).
DAILY = """
WITH k AS (
    SELECT hotel_id, hotel_code, stay_date, is_actual, rooms_available, rooms_sold, room_revenue, total_revenue
    FROM pms.v_daily_kpis {where}
), t AS (
    SELECT hotel_id, coalesce(min(stay_date) FILTER (WHERE NOT is_actual), max(stay_date) + 1) AS today
    FROM k GROUP BY hotel_id
)
SELECT k.hotel_code, t.today, k.stay_date, k.rooms_available, k.rooms_sold, k.room_revenue,
       k.total_revenue
FROM k JOIN t USING (hotel_id)
WHERE k.stay_date BETWEEN t.today - 740 AND t.today + 29
ORDER BY 1, 3"""

# Arrivals and departures today, from the sample tables and (when imported) FNSrooms.
MOVES = """
SELECT h.code,
       count(*) FILTER (WHERE r.arrival = d.today) AS arrivals,
       count(*) FILTER (WHERE r.departure = d.today) AS departures
FROM pms.reservations r
JOIN pms.hotels h ON h.id = r.hotel_id
JOIN unnest(%(codes)s::text[], %(days)s::date[]) AS d(code, today) ON d.code = h.code
WHERE r.status IN ('confirmed', 'checked_in', 'checked_out')
  AND (r.arrival = d.today OR r.departure = d.today)
GROUP BY h.code"""

MOVES_FNS = """
SELECT h.code,
       count(*) FILTER (WHERE r.arrival = d.today) AS arrivals,
       count(*) FILTER (WHERE r.departure = d.today) AS departures
FROM pms.fns_reservations r
JOIN pms.hotels h ON h.id = r.hotel_id
JOIN unnest(%(codes)s::text[], %(days)s::date[]) AS d(code, today) ON d.code = h.code
WHERE coalesce(r.status, '') NOT ILIKE 'cancel%%'
  AND (r.arrival = d.today OR r.departure = d.today)
GROUP BY h.code"""

SERIES_DAYS = 14

PERIODS = ("mtd", "last_month", "last_7", "last_30", "ytd")

# Alerts: changes against the same days a year earlier at or past these, and low occupancy ahead.
ALERT_OCCUPANCY_PP = -0.05
ALERT_ADR = -0.05
ALERT_REVENUE = -0.10
ALERT_NEXT_30 = 0.5


def _num(v: Any) -> float:
    try:
        return float(v) if v is not None and not isinstance(v, bool) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _day(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


Day = tuple[float, float, float, float]  # rooms available, rooms sold, room revenue, gross (total) revenue
NO_DAY: Day = (0.0, 0.0, 0.0, 0.0)


def _sums(days: dict[date, Day], start: date, end: date) -> Day:
    avail = sold = revenue = gross = 0.0
    d = start
    while d <= end:
        a, s, r, g = days.get(d, NO_DAY)
        avail, sold, revenue, gross = avail + a, sold + s, revenue + r, gross + g
        d += timedelta(days=1)
    return avail, sold, revenue, gross


def _ratio(n: float, d: float) -> float | None:
    return round(n / d, 6) if d else None


def _change(now: float | None, before: float | None) -> float | None:
    """Relative change (0.082 = +8.2%)."""
    return round(now / before - 1, 6) if now is not None and before else None


def _diff(now: float | None, before: float | None) -> float | None:
    """Difference in occupancy points (0.061 = +6.1 pp)."""
    return round(now - before, 6) if now is not None and before is not None else None


def year_before(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year - 1, day=28)


def period_range(today: date, period: str) -> tuple[date, date, date, date]:
    """(start, end, start a year earlier, end a year earlier) of a period of actuals ending yesterday:
    this month so far (on the 1st, last month), last month, the last 7 or 30 days (compared with
    the same weekdays 52 weeks earlier) or this year so far."""
    end = today - timedelta(days=1)
    if period in ("last_7", "last_30"):
        start = today - timedelta(days=7 if period == "last_7" else 30)
        return start, end, start - timedelta(days=364), end - timedelta(days=364)
    if period == "last_month":
        end = end.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif period == "ytd":
        start = end.replace(month=1, day=1)
    else:
        start = end.replace(day=1)
    return start, end, year_before(start), year_before(end)


def alerts(figures: dict[str, Any]) -> list[dict[str, Any]]:
    """Figures well below last year's, or low occupancy ahead: [{key, value}]."""
    out = []
    checks = [("occupancy_today", figures["occupancy_today_change_pp"], ALERT_OCCUPANCY_PP),
              ("adr", figures["adr_period_change"], ALERT_ADR),
              ("revenue", figures["revenue_period_change"], ALERT_REVENUE)]
    for key, value, limit in checks:
        if value is not None and value <= limit:
            out.append({"key": key, "value": value})
    if figures["occupancy_next_30"] is not None and figures["occupancy_next_30"] < ALERT_NEXT_30:
        out.append({"key": "next_30", "value": figures["occupancy_next_30"]})
    return out


def summarize(code: str, today: date, days: dict[date, Day],
              moves: tuple[int, int] | None, period: str = "mtd") -> dict[str, Any]:
    """Key figures for one hotel from its daily (rooms available, rooms sold, room revenue, gross revenue)."""
    month_start, month_end, ly_start, ly_end = period_range(today, period)
    a, s, r, g = _sums(days, month_start, month_end)
    la, ls, lr, lg = _sums(days, ly_start, ly_end)
    adr, adr_ly = _ratio(r, s), _ratio(lr, ls)
    revpar, revpar_ly = _ratio(r, a), _ratio(lr, la)

    # Same weekday a year earlier (52 weeks back) for a single day.
    occ_today = _ratio(*_sums(days, today, today)[1::-1])
    occ_ly = _ratio(*_sums(days, today - timedelta(days=364), today - timedelta(days=364))[1::-1])

    fa, fs, fr, _ = _sums(days, today, today + timedelta(days=29))

    def daily(start: date, n: int, pick) -> list[float | None]:
        out = []
        for i in range(n):
            da, ds, dr, _ = days.get(start + timedelta(days=i), NO_DAY)
            out.append(pick(da, ds, dr))
        return out

    series_start = today - timedelta(days=SERIES_DAYS)
    running, running_gross, cumulative, cumulative_gross = 0.0, 0.0, [], []
    for _, _, dr, dg in (days.get(month_start + timedelta(days=i), NO_DAY)
                         for i in range((month_end - month_start).days + 1)):
        running, running_gross = running + dr, running_gross + dg
        cumulative.append(round(running, 2))
        cumulative_gross.append(round(running_gross, 2))
    figures = {
        "hotel_code": code,
        "today": today.isoformat(),
        "period": {"key": period, "start": month_start.isoformat(), "end": month_end.isoformat()},
        "occupancy_today": occ_today,
        "occupancy_today_change_pp": _diff(occ_today, occ_ly),
        "arrivals_today": moves[0] if moves else None,
        "departures_today": moves[1] if moves else None,
        "adr_period": adr, "adr_period_change": _change(adr, adr_ly),
        "revpar_period": revpar, "revpar_period_change": _change(revpar, revpar_ly),
        "revenue_period": round(r, 2), "revenue_period_change": _change(r, lr),
        "gross_revenue_period": round(g, 2), "gross_revenue_period_change": _change(g, lg),
        "occupancy_next_30": _ratio(fs, fa), "revenue_next_30": round(fr, 2),
        "series": {
            "occupancy": daily(series_start, SERIES_DAYS, lambda a, s, r: _ratio(s, a)),
            "adr": daily(series_start, SERIES_DAYS, lambda a, s, r: _ratio(r, s)),
            "revpar": daily(series_start, SERIES_DAYS, lambda a, s, r: _ratio(r, a)),
            "revenue_period": cumulative,
            "gross_revenue_period": cumulative_gross,
            "occupancy_next_30": daily(today, 30, lambda a, s, r: _ratio(s, a)),
        },
    }
    figures["alerts"] = alerts(figures)
    return figures


def build(daily_rows: list[list[Any]], moves: dict[str, tuple[int, int]],
          period: str = "mtd") -> dict[str, dict[str, Any]]:
    """Per hotel code, from DAILY's rows and MOVES' counts."""
    hotels: dict[str, tuple[date, dict[date, Day]]] = {}
    for code, today, stay_date, avail, sold, revenue, gross in daily_rows:
        # Hotels imported from FNSrooms have no total revenue (NULL): gross is at least the rooms.
        hotels.setdefault(code, (_day(today), {}))[1][_day(stay_date)] = (
            _num(avail), _num(sold), _num(revenue), _num(revenue if gross is None else gross))
    return {code: summarize(code, today, days, moves.get(code), period) for code, (today, days) in hotels.items()}
