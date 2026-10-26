"""Writes to the reporting database (as its owner, which row-level security doesn't restrict)."""

import json
import logging
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .config import Config

# db/init/06_fns.sql in the repository; mounted at /app/schema.sql in the container.
SCHEMA_PATHS = [Path("/app/schema.sql"), Path(__file__).resolve().parents[2] / "db" / "init" / "06_fns.sql"]
KNOWN_CURRENCIES = {1: "EUR", 2: "USD"}
log = logging.getLogger("fns_sync")


def ensure_schema(conn: psycopg.Connection) -> None:
    path = next((p for p in SCHEMA_PATHS if p.exists()), None)
    if path is None:
        raise RuntimeError("06_fns.sql not found (mount db/init/06_fns.sql at /app/schema.sql).")
    with conn.transaction():
        conn.execute(path.read_text())


def ensure_hotel(conn: psycopg.Connection, cfg: Config) -> int:
    """The hotels row for the FNS alojamiento (created on the first run)."""
    with conn.transaction():
        row = conn.execute("SELECT id FROM pms.hotels WHERE alojamiento_id = %s", (cfg.alojamiento_id,)).fetchone()
        clash = conn.execute("SELECT alojamiento_id FROM pms.hotels WHERE code = %s AND alojamiento_id <> %s",
                             (cfg.hotel_code, cfg.alojamiento_id)).fetchone()
        if clash:
            raise RuntimeError(f"Hotel code {cfg.hotel_code} is already used by another hotel; set FNS_HOTEL_CODE "
                               "to a free code.")
        if row:
            conn.execute("UPDATE pms.hotels SET code = %s, name = %s, city = %s, country = %s, timezone = %s "
                         "WHERE id = %s", (cfg.hotel_code, cfg.hotel_name, cfg.hotel_city, cfg.hotel_country,
                                           cfg.timezone, row[0]))
            if cfg.pms_id:
                conn.execute("UPDATE pms.hotels SET pms_id = %s WHERE id = %s", (cfg.pms_id, row[0]))
            return row[0]
        # hotels.pms_id must be unique and above 0; without FNS_PMS_ID use a value that can't clash
        # with real ones (administrators can change it in the Admin page).
        pms_id = cfg.pms_id or 900_000_000 + cfg.alojamiento_id
        return conn.execute(
            "INSERT INTO pms.hotels (code, name, city, country, star_rating, total_rooms, currency, timezone, "
            "opened_on, alojamiento_id, pms_id) VALUES (%s, %s, %s, %s, 3, 0, %s, %s, current_date, %s, %s) "
            "RETURNING id",
            (cfg.hotel_code, cfg.hotel_name, cfg.hotel_city, cfg.hotel_country, cfg.currency or "EUR",
             cfg.timezone, cfg.alojamiento_id, pms_id)).fetchone()[0]


def hotel_currency(conn: psycopg.Connection, hotel_id: int, cfg: Config) -> tuple[int, str]:
    """(FNS moneda_id, ISO code) to request and label amounts in: FNS_MONEDA_ID, else the currency
    of the accounting entries already imported, else FNS_CURRENCY when it is EUR or USD, else EUR.
    The API converts amounts to the requested currency, so the label always matches the id."""
    seen = dict(conn.execute(
        "SELECT moneda_id, currency FROM pms.fns_accounting_entries WHERE hotel_id = %s AND moneda_id IS NOT NULL "
        "AND currency IS NOT NULL GROUP BY 1, 2 ORDER BY count(*)", (hotel_id,)).fetchall())  # most used last
    if cfg.moneda_id:
        code = KNOWN_CURRENCIES.get(cfg.moneda_id) or seen.get(cfg.moneda_id) or cfg.currency
        if not code:
            log.warning("set FNS_CURRENCY to the code of FNS currency %s (e.g. COP)", cfg.moneda_id)
        return cfg.moneda_id, (code or "XXX").upper()[:3]
    if seen:
        moneda_id, code = list(seen.items())[-1]
        return moneda_id, code.upper()[:3]
    by_code = {v: k for k, v in KNOWN_CURRENCIES.items()}
    if cfg.currency in by_code:
        return by_code[cfg.currency], cfg.currency
    if cfg.currency:
        log.warning("amounts in EUR: set FNS_MONEDA_ID to FNS's id for %s to get them in %s",
                    cfg.currency, cfg.currency)
    return 1, "EUR"


def set_currency(conn: psycopg.Connection, hotel_id: int, currency: str) -> None:
    with conn.transaction():
        conn.execute("UPDATE pms.hotels SET currency = %s WHERE id = %s", (currency, hotel_id))


def set_total_rooms(conn: psycopg.Connection, hotel_id: int) -> None:
    with conn.transaction():
        conn.execute(
            "UPDATE pms.hotels SET total_rooms = coalesce((SELECT max(rooms_total + coalesce(rooms_blocked, 0)) "
            "FROM pms.fns_revenue_daily WHERE hotel_id = %s AND stay_date BETWEEN current_date - 30 "
            "AND current_date + 30), total_rooms) WHERE id = %s", (hotel_id, hotel_id))


def loaded_steps(conn: psycopg.Connection, hotel_id: int) -> set[str]:
    """Import steps that have loaded their history for the hotel."""
    return {r[0] for r in conn.execute("SELECT step FROM pms.fns_sync_steps WHERE hotel_id = %s", (hotel_id,))}


def mark_loaded(conn: psycopg.Connection, hotel_id: int, step: str, history_from) -> None:
    with conn.transaction():
        conn.execute("INSERT INTO pms.fns_sync_steps (hotel_id, step, history_from) VALUES (%s, %s, %s) "
                     "ON CONFLICT (hotel_id, step) DO UPDATE SET history_from = excluded.history_from, "
                     "loaded_at = now()", (hotel_id, step, history_from))


def has_accounting(conn: psycopg.Connection, hotel_id: int) -> bool:
    return conn.execute("SELECT EXISTS (SELECT 1 FROM pms.fns_accounting_entries WHERE hotel_id = %s)",
                        (hotel_id,)).fetchone()[0]


def _adapt(v: Any) -> Any:
    return Jsonb(v) if isinstance(v, (dict, list)) else v


def save(conn: psycopg.Connection, table: str, hotel_id: int | None, rows: Iterable[dict],
         conflict: tuple[str, ...], delete: tuple[str, tuple] | None = None) -> int:
    """Upsert rows into pms.<table> (adding hotel_id). `delete` = (SQL condition, params) first
    removes the rows of this hotel the API no longer returns for the requested window."""
    rows = list(rows)
    with conn.transaction():
        if delete:
            where, params = delete
            conn.execute(sql.SQL("DELETE FROM pms.{} WHERE hotel_id = %s AND ").format(sql.Identifier(table))
                         + sql.SQL(where), (hotel_id, *params))
        if not rows:
            return 0
        columns = (["hotel_id"] if hotel_id is not None else []) + list(rows[0])
        updates = [c for c in columns if c not in conflict]
        query = sql.SQL("INSERT INTO pms.{t} ({cols}) VALUES ({vals}) ON CONFLICT ({key}) DO {action}").format(
            t=sql.Identifier(table),
            cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
            vals=sql.SQL(", ").join(sql.Placeholder() * len(columns)),
            key=sql.SQL(", ").join(map(sql.Identifier, conflict)),
            action=sql.SQL("UPDATE SET {}").format(sql.SQL(", ").join(
                sql.SQL("{c} = excluded.{c}").format(c=sql.Identifier(c)) for c in updates))
            if updates else sql.SQL("NOTHING"))
        with conn.cursor() as cur:
            cur.executemany(query, [([hotel_id] if hotel_id is not None else [])
                                    + [_adapt(r.get(c)) for c in columns[1 if hotel_id is not None else 0:]]
                                    for r in rows])
    return len(rows)


def start_run(conn: psycopg.Connection, hotel_id: int, backfill: bool) -> int:
    with conn.transaction():
        return conn.execute("INSERT INTO pms.fns_sync_runs (hotel_id, backfill) VALUES (%s, %s) RETURNING id",
                            (hotel_id, backfill)).fetchone()[0]


def finish_run(conn: psycopg.Connection, run_id: int, status: str, calls: list[dict]) -> None:
    with conn.transaction():
        conn.execute("UPDATE pms.fns_sync_runs SET finished_at = now(), status = %s, calls = %s WHERE id = %s",
                     (status, Jsonb(json.loads(json.dumps(calls, default=str))), run_id))


def last_runs(conn: psycopg.Connection, limit: int = 10) -> list[tuple]:
    return conn.execute("SELECT r.id, h.code, r.started_at, r.finished_at, r.status, r.backfill, r.calls "
                        "FROM pms.fns_sync_runs r LEFT JOIN pms.hotels h ON h.id = r.hotel_id "
                        "ORDER BY r.id DESC LIMIT %s", (limit,)).fetchall()
