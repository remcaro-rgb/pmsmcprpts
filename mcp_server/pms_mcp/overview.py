"""The home screen's key figures per hotel: today, this month so far and the next 30 days, each
against the same days a year earlier, plus a short daily series for the small trend lines."""

from datetime import date, timedelta
from typing import Any

# Daily rows around each hotel's "today" (its first stay date that isn't an actual yet).
DAILY = """
WITH k AS (
    SELECT hotel_id, hotel_code, stay_date, is_actual, rooms_available, rooms_sold, room_revenue
    FROM pms.v_daily_kpis {where}
), t AS (
    SELECT hotel_id, coalesce(min(stay_date) FILTER (WHERE NOT is_actual), max(stay_date) + 1) AS today
    FROM k GROUP BY hotel_id
)
SELECT k.hotel_code, t.today, k.stay_date, k.rooms_available, k.rooms_sold, k.room_revenue
FROM k JOIN t USING (hotel_id)
WHERE k.stay_date BETWEEN t.today - 400 AND t.today + 29
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


def _num(v: Any) -> float:
    try:
        return float(v) if v is not None and not isinstance(v, bool) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _day(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _sums(days: dict[date, tuple[float, float, float]], start: date, end: date) -> tuple[float, float, float]:
    avail = sold = revenue = 0.0
    d = start
    while d <= end:
        a, s, r = days.get(d, (0.0, 0.0, 0.0))
        avail, sold, revenue = avail + a, sold + s, revenue + r
        d += timedelta(days=1)
    return avail, sold, revenue


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


def summarize(code: str, today: date, days: dict[date, tuple[float, float, float]],
              moves: tuple[int, int] | None) -> dict[str, Any]:
    """Key figures for one hotel from its daily (rooms available, rooms sold, room revenue)."""
    # This month so far (actuals up to yesterday); on the 1st, last month.
    month_end = today - timedelta(days=1)
    month_start = month_end.replace(day=1)
    a, s, r = _sums(days, month_start, month_end)
    la, ls, lr = _sums(days, year_before(month_start), year_before(month_end))
    adr, adr_ly = _ratio(r, s), _ratio(lr, ls)
    revpar, revpar_ly = _ratio(r, a), _ratio(lr, la)

    # Same weekday a year earlier (52 weeks back) for a single day.
    occ_today = _ratio(*_sums(days, today, today)[1::-1])
    occ_ly = _ratio(*_sums(days, today - timedelta(days=364), today - timedelta(days=364))[1::-1])

    fa, fs, fr = _sums(days, today, today + timedelta(days=29))

    def daily(start: date, n: int, pick) -> list[float | None]:
        out = []
        for i in range(n):
            da, ds, dr = days.get(start + timedelta(days=i), (0.0, 0.0, 0.0))
            out.append(pick(da, ds, dr))
        return out

    series_start = today - timedelta(days=SERIES_DAYS)
    running, cumulative = 0.0, []
    for _, _, dr in (days.get(month_start + timedelta(days=i), (0.0, 0.0, 0.0))
                     for i in range((month_end - month_start).days + 1)):
        running += dr
        cumulative.append(round(running, 2))
    return {
        "hotel_code": code,
        "today": today.isoformat(),
        "month": {"start": month_start.isoformat(), "end": month_end.isoformat()},
        "occupancy_today": occ_today,
        "occupancy_today_change_pp": _diff(occ_today, occ_ly),
        "arrivals_today": moves[0] if moves else None,
        "departures_today": moves[1] if moves else None,
        "adr_month": adr, "adr_month_change": _change(adr, adr_ly),
        "revpar_month": revpar, "revpar_month_change": _change(revpar, revpar_ly),
        "revenue_month": round(r, 2), "revenue_month_change": _change(r, lr),
        "occupancy_next_30": _ratio(fs, fa), "revenue_next_30": round(fr, 2),
        "series": {
            "occupancy": daily(series_start, SERIES_DAYS, lambda a, s, r: _ratio(s, a)),
            "adr": daily(series_start, SERIES_DAYS, lambda a, s, r: _ratio(r, s)),
            "revpar": daily(series_start, SERIES_DAYS, lambda a, s, r: _ratio(r, a)),
            "revenue_month": cumulative,
            "occupancy_next_30": daily(today, 30, lambda a, s, r: _ratio(s, a)),
        },
    }


def build(daily_rows: list[list[Any]], moves: dict[str, tuple[int, int]]) -> dict[str, dict[str, Any]]:
    """Per hotel code, from DAILY's rows and MOVES' counts."""
    hotels: dict[str, tuple[date, dict[date, tuple[float, float, float]]]] = {}
    for code, today, stay_date, avail, sold, revenue in daily_rows:
        hotels.setdefault(code, (_day(today), {}))[1][_day(stay_date)] = (_num(avail), _num(sold), _num(revenue))
    return {code: summarize(code, today, days, moves.get(code)) for code, (today, days) in hotels.items()}
