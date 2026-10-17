import pytest

from pms_mcp.sql_guard import UnsafeQueryError, check_read_only


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select * from reservations where arrival >= '2026-01-01';",
    "WITH m AS (SELECT date_trunc('month', stay_date) m, sum(rooms_sold) s FROM v_daily_kpis GROUP BY 1) "
    "SELECT * FROM m ORDER BY m",
    "SELECT channel FROM reservations UNION ALL SELECT 'x'",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY rate) FROM reservation_nights",
    "SELECT 'delete from hotels' AS harmless_string",
])
def test_allows_read_queries(sql):
    check_read_only(sql)


@pytest.mark.parametrize("sql, reason", [
    ("DELETE FROM hotels", "Only SELECT"),
    ("UPDATE hotels SET name = 'x'", "Only SELECT"),
    ("DROP TABLE hotels", "Only SELECT"),
    ("SELECT 1; DELETE FROM hotels", "exactly one statement"),
    ("SELECT 1; SELECT 2", "exactly one statement"),
    ("WITH x AS (DELETE FROM hotels RETURNING *) SELECT * FROM x", "DELETE"),
    ("SELECT * INTO new_table FROM hotels", "INTO"),
    ("SELECT * FROM hotels FOR UPDATE", "LOCK"),
    ("SELECT pg_sleep(30)", "pg_sleep"),
    ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
    ("SELECT set_config('statement_timeout', '0', false)", "set_config"),
    ("SELECT query_to_xml('delete from hotels', true, true, '')", "query_to_xml"),
    ("SET statement_timeout = 0", "Only SELECT"),
    ("COPY hotels TO STDOUT", "Only SELECT"),
    ("", "exactly one statement"),
])
def test_rejects_unsafe_queries(sql, reason):
    with pytest.raises(UnsafeQueryError, match=reason):
        check_read_only(sql)
