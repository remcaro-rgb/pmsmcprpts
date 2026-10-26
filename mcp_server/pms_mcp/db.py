"""Read-only query execution against the PMS database."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql as pgsql


class QueryError(Exception):
    pass


@dataclass
class QueryResult:
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    truncated: bool


def to_json_value(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime, time)):
        return v.isoformat()
    if isinstance(v, timedelta):
        return v.total_seconds()
    if isinstance(v, (list, tuple)):
        return [to_json_value(x) for x in v]
    return str(v)


class Database:
    def __init__(self, dsn: str, statement_timeout_ms: int = 15000):
        self.dsn = dsn
        self.statement_timeout_ms = statement_timeout_ms

    async def query(self, query: str | pgsql.Composable, params: dict | None = None,
                    max_rows: int = 50_000, hotels: str = "", user: str = "") -> QueryResult:
        """Run one query in a READ ONLY transaction and return at most max_rows rows.

        The database limits which hotels' rows the query can see (row-level security):
        `user` is a user-directory email, whose assigned hotels (all for an administrator) apply;
        otherwise `hotels` ("*", "LIS,OPO", or "" for none, the default) does."""
        try:
            async with await psycopg.AsyncConnection.connect(self.dsn) as conn:
                async with conn.transaction():
                    await conn.execute("SET TRANSACTION READ ONLY")
                    await conn.execute("SET LOCAL search_path = pms")
                    await conn.execute(pgsql.SQL("SET LOCAL statement_timeout = {}").format(
                        pgsql.Literal(self.statement_timeout_ms)))
                    await conn.execute(pgsql.SQL("SET LOCAL pms.allowed_hotels = {}").format(
                        pgsql.Literal(hotels)))
                    await conn.execute(pgsql.SQL("SET LOCAL pms.user_email = {}").format(
                        pgsql.Literal(user)))
                    async with conn.cursor() as cur:
                        # Prepared, so exactly one statement runs: a second one could change settings.
                        await cur.execute(query, params, prepare=True)
                        if cur.description is None:
                            return QueryResult([], [], False)
                        rows = await cur.fetchmany(max_rows + 1)
                        columns = []
                        for d in cur.description:
                            info = conn.adapters.types.get(d.type_code)
                            columns.append({"name": d.name, "type": info.name if info else str(d.type_code)})
        except psycopg.errors.QueryCanceled as e:
            raise QueryError(f"Query exceeded the {self.statement_timeout_ms // 1000}s time limit; "
                             "aggregate more or filter to a smaller date range.") from e
        except psycopg.Error as e:
            raise QueryError(str(e).strip()) from e
        truncated = len(rows) > max_rows
        return QueryResult(columns, [[to_json_value(v) for v in r] for r in rows[:max_rows]], truncated)
