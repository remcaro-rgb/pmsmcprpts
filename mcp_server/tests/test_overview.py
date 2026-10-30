from datetime import date

from pms_mcp.overview import alerts, build, period_range


def test_period_ranges():
    today = date(2026, 10, 24)
    assert period_range(today, "mtd") == (date(2026, 10, 1), date(2026, 10, 23), date(2025, 10, 1), date(2025, 10, 23))
    assert period_range(date(2026, 11, 1), "mtd")[:2] == (date(2026, 10, 1), date(2026, 10, 31))  # the 1st: last month
    assert period_range(today, "last_month")[:2] == (date(2026, 9, 1), date(2026, 9, 30))
    assert period_range(today, "ytd")[:2] == (date(2026, 1, 1), date(2026, 10, 23))
    start, end, ly_start, ly_end = period_range(today, "last_7")
    assert (start, end) == (date(2026, 10, 17), date(2026, 10, 23)) and ly_start.weekday() == start.weekday()


def test_alerts():
    base = {"occupancy_today_change_pp": -0.061, "adr_period_change": 0.02, "revenue_period_change": -0.12,
            "occupancy_next_30": 0.42}
    assert [a["key"] for a in alerts(base)] == ["occupancy_today", "revenue", "next_30"]
    assert alerts({**base, "occupancy_today_change_pp": None, "revenue_period_change": 0.0,
                   "occupancy_next_30": 0.8}) == []


def test_gross_revenue_sums_every_department_beside_room_revenue():
    today = date(2026, 10, 24)
    # (code, today, stay date, rooms available, rooms sold, room revenue, total revenue)
    rows = [["FRA", today, date(2026, 10, 1), 10, 5, 500, 700], ["FRA", today, date(2026, 10, 2), 10, 5, 400, 600],
            ["FRA", today, date(2025, 10, 1), 10, 5, 300, 350], ["FRA", today, date(2025, 10, 2), 10, 5, 300, 350]]
    h = build(rows, {"FRA": (1, 2)})["FRA"]
    assert h["revenue_period"] == 900 and h["gross_revenue_period"] == 1300
    assert h["revenue_period_change"] == 0.5 and h["gross_revenue_period_change"] == round(1300 / 700 - 1, 6)
    assert h["series"]["gross_revenue_period"][:2] == [700, 1300]  # running total through the month


def test_gross_revenue_falls_back_to_room_revenue_when_the_total_is_unknown():
    today = date(2026, 10, 24)
    # An FNS-imported hotel: v_daily_kpis has NULL total revenue, only room revenue.
    rows = [["FRA", today, date(2026, 10, 1), 10, 5, 500, None], ["FRA", today, date(2026, 10, 2), 10, 5, 400, None],
            ["FRA", today, date(2025, 10, 1), 10, 5, 300, None], ["FRA", today, date(2025, 10, 2), 10, 5, 300, None]]
    h = build(rows, {"FRA": (1, 2)})["FRA"]
    assert h["gross_revenue_period"] == h["revenue_period"] == 900
    assert h["gross_revenue_period_change"] == h["revenue_period_change"] == 0.5
    assert h["series"]["gross_revenue_period"][:2] == [500, 900]
