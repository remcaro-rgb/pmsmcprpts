from datetime import date

from pms_mcp.overview import alerts, period_range


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
