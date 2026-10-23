"""One import run: call every FNS method for the configured hotel and store the results.

Each method's data is saved in its own transaction, so one failing call doesn't lose the others;
the run is recorded in pms.fns_sync_runs with every call's window, row count and error."""

import logging
import time as _time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterator

import psycopg

from . import parse, store
from .client import AuthError, FNSClient, FNSError
from .config import Config

log = logging.getLogger("fns_sync")

MASTER_KINDS = ("th", "th_completo", "habitaciones", "cc", "ofertas", "canales", "subcanales", "segmentos",
                "agencias", "agentes", "empresas", "paises", "usuarios", "sucursales", "salones", "pv",
                "servicios", "usuariosGastro", "alojamientos", "clientes")
RESERVATION_STATES = ("Todas", "canceladas", "modificadas")
# FNS limits reservation and block searches to 30 days; other methods are chunked by month too.
CHUNK_DAYS = 30
SALES_AHEAD_DAYS = 90
BLOCKS_AHEAD_DAYS = 90
AVAILABILITY_AHEAD_DAYS = 180
# Steps of a run, in order (for `run --only`).
STEPS = ("master", "accounting", "exchange", "revenue", "production_cc", "production", "sales_reservations", "pos",
         "reservations", "blocks", "availability")


def windows(start: date, end: date, days: int = CHUNK_DAYS) -> Iterator[tuple[date, date]]:
    """Consecutive inclusive date ranges of at most `days` days covering start..end."""
    while start <= end:
        stop = min(end, start + timedelta(days=days - 1))
        yield start, stop
        start = stop + timedelta(days=1)


def iso(d: date) -> str:
    return d.isoformat()


class Sync:
    def __init__(self, cfg: Config, client: FNSClient | None = None, sleep: Callable[[float], None] = _time.sleep):
        self.cfg = cfg
        self.client = client or FNSClient(cfg)
        self.sleep = sleep
        self.calls: list[dict] = []

    # --- helpers ----------------------------------------------------------------------------------

    def _filter(self, **fields: Any) -> dict:
        f = dict(fields)
        if self.cfg.pms_id:
            f["pms_id"] = self.cfg.pms_id
        return f

    def _call(self, name: str, body: dict, window: str = "", optional: bool = False) -> Any:
        """Calls the API; on failure records it and returns None (AuthError stops the run)."""
        started = _time.monotonic()
        entry = {"method": name, "window": window}
        self.calls.append(entry)
        try:
            result = self.client.call(name, body)
            entry["ok"] = True
            return result
        except AuthError as e:
            entry.update(ok=False, error=str(e))
            raise
        except FNSError as e:
            entry.update(ok=False, error=str(e), optional=optional)
            log.warning("%s %s: %s", name, window, e)
            return None
        finally:
            entry["seconds"] = round(_time.monotonic() - started, 2)
            if self.cfg.pause:
                self.sleep(self.cfg.pause)

    def _stored(self, rows: int) -> None:
        self.calls[-1]["rows"] = self.calls[-1].get("rows", 0) + rows

    # --- the methods ------------------------------------------------------------------------------

    def master(self, conn, hotel_id: int) -> None:
        for kind in MASTER_KINDS:
            payload = self._call("master", {"filter": self._filter(
                central_id="", alojamiento_id=self.cfg.alojamiento_id, listado=kind)}, kind, optional=True)
            if payload is not None:
                rows = [r for r in parse.master(payload) if r["kind"] == kind] if isinstance(payload, dict) else []
                self._stored(store.save(conn, "fns_master_items", hotel_id, rows, ("hotel_id", "kind", "item_id")))

    def accounting(self, conn, hotel_id: int, start: date, end: date) -> None:
        for name, book in (("payments", "payments"), ("invoices", "invoices"),
                           ("accounting_production", "production")):
            for a, b in windows(start, end):
                payload = self._call(name, {"filter": self._filter(
                    alojamiento_id=self.cfg.alojamiento_id, start_date=iso(a), end_date=iso(b))}, f"{a}..{b}")
                if payload is None:
                    continue
                entries, lines, parties = parse.accounting(payload, book)
                n = store.save(conn, "fns_accounting_entries", hotel_id, entries, ("hotel_id", "book", "entry_id"))
                ids = [e["entry_id"] for e in entries]
                store.save(conn, "fns_accounting_lines", hotel_id, lines,
                           ("hotel_id", "book", "entry_id", "side", "line_key"),
                           delete=("book = %s AND entry_id = ANY(%s)", (book, ids)))
                store.save(conn, "fns_third_parties", hotel_id, parties, ("hotel_id", "tax_id"))
                self._stored(n)

    def exchange(self, conn, moneda_id: int, start: date, end: date) -> None:
        for target in self.cfg.exchange_to:
            if target == moneda_id:
                continue
            for a, b in windows(start, end):
                payload = self._call("exchange", self._filter(
                    central_id=self.cfg.central_id, start_date=iso(a), end_date=iso(b),
                    moneda_src_id=moneda_id, moneda_dst_id=target), f"{moneda_id}->{target} {a}..{b}", optional=True)
                if payload is not None:
                    self._stored(store.save(conn, "fns_exchange_rates", None, parse.exchange(payload, moneda_id, target),
                                            ("rate_date", "from_moneda_id", "to_moneda_id")))

    def revenue(self, conn, hotel_id: int, moneda_id: int, start: date, end: date) -> None:
        for a, b in windows(start, end):
            payload = self._call("revenue", {"filter": self._filter(
                alojamiento_id=self.cfg.alojamiento_id, central_id="", start_date=iso(a), end_date=iso(b),
                moneda_id=moneda_id, impuesto=0)}, f"{a}..{b}")
            if payload is not None:
                rows = [{**r, "fetched_at": datetime.now().astimezone()} for r in parse.revenue(payload)]
                self._stored(store.save(conn, "fns_revenue_daily", hotel_id, rows, ("hotel_id", "stay_date")))

    def production_cc(self, conn, hotel_id: int, moneda_id: int, start: date, end: date) -> None:
        for a, b in windows(start, end):
            payload = self._call("production_cc", {"filter": self._filter(
                alojamiento_id=self.cfg.alojamiento_id, central_id=self.cfg.central_id, start_date=iso(a),
                end_date=iso(b), moneda_id=moneda_id, impuesto=0)}, f"{a}..{b}")
            if payload is not None or self.calls[-1].get("ok"):
                self._stored(store.save(conn, "fns_production_cc", hotel_id,
                                        parse.production_cc(payload, self.cfg.alojamiento_id),
                                        ("hotel_id", "prod_date", "cc_id"),
                                        delete=("prod_date BETWEEN %s AND %s", (a, b))))

    def production(self, conn, hotel_id: int, moneda_id: int, start: date, end: date, today: date) -> None:
        # One call per day: the report groups by channel and segment but not by date.
        d = start
        while d <= end:
            payload = self._call("production", {"filter": self._filter(
                alojamiento_id=self.cfg.alojamiento_id, central_id=self.cfg.central_id, start_date=iso(d),
                end_date=iso(d), moneda_id=moneda_id, impuesto=0, fecha_simulacion=iso(today), fuente="",
                total=0), "group": ["canal_id", "segmento_id"]}, iso(d))
            if payload is not None or self.calls[-1].get("ok"):
                self._stored(store.save(conn, "fns_production", hotel_id,
                                        parse.production(payload, d, self.cfg.alojamiento_id),
                                        ("hotel_id", "prod_date", "channel_id", "segment_id"),
                                        delete=("prod_date = %s", (d,))))
            d += timedelta(days=1)

    def sales_reservations(self, conn, hotel_id: int, start: date, end: date) -> None:
        for a, b in windows(start, end):
            payload = self._call("sales_reservations", {"filter": self._filter(
                alojamiento_id=self.cfg.alojamiento_id, start_date=iso(a), end_date=iso(b))}, f"{a}..{b}")
            if payload is None:
                continue
            reservations, days = parse.sales_reservations(payload)
            now = datetime.now().astimezone()
            n = store.save(conn, "fns_sales_reservations", hotel_id, [{**r, "fetched_at": now} for r in reservations],
                           ("hotel_id", "reservation_id", "guest_name"))
            store.save(conn, "fns_sales_reservation_days", hotel_id, days,
                       ("hotel_id", "reservation_id", "guest_name", "prod_date"),
                       delete=("prod_date BETWEEN %s AND %s", (a, b)))
            self._stored(n)

    def pos(self, conn, hotel_id: int, start: date, end: date) -> None:
        for a, b in windows(start, end):
            payload = self._call("pos", {"filter": self._filter(
                central_id=self.cfg.central_id, alojamiento_id=self.cfg.alojamiento_id, start_date=iso(a),
                end_date=iso(b), tipo=0)}, f"{a}..{b}")
            if payload is not None or self.calls[-1].get("ok"):
                self._stored(store.save(conn, "fns_pos_sales", hotel_id, parse.pos(payload),
                                        ("hotel_id", "pos_id", "sale_date", "recipe_id"),
                                        delete=("sale_date BETWEEN %s AND %s", (a, b))))

    def reservations(self, conn, hotel_id: int, start: date, end: date) -> None:
        for state in RESERVATION_STATES:
            for a, b in windows(start, end):
                payload = self._call("reservations", {"filter": {
                    "central_id": self.cfg.central_id, "alojamiento_id": self.cfg.alojamiento_id,
                    "start_date": iso(a), "end_date": iso(b), "estado": state,
                    "verTitular": 1, "verHuespedes": 1, "verDetalles": 1, "verInhouse": 1}}, f"{state} {a}..{b}",
                    optional=state != "Todas")  # the cancelled and modified searches only add updates
                if payload is None:
                    continue
                bookings, rooms = parse.reservations(payload)
                now = datetime.now().astimezone()
                n = store.save(conn, "fns_reservations", hotel_id, [{**r, "fetched_at": now} for r in bookings],
                               ("hotel_id", "localizador"))
                store.save(conn, "fns_reservation_rooms", hotel_id, rooms, ("hotel_id", "localizador", "detail_id"),
                           delete=("localizador = ANY(%s)", ([r["localizador"] for r in bookings],)))
                self._stored(n)

    def blocks(self, conn, hotel_id: int, start: date, end: date) -> None:
        for a, b in windows(start, end):
            payload = self._call("blocks", {"filter": {
                "central_id": self.cfg.central_id, "alojamiento_id": self.cfg.alojamiento_id,
                "start_date": iso(a), "end_date": iso(b)}}, f"{a}..{b}")
            if payload is not None:
                self._stored(store.save(conn, "fns_room_blocks", hotel_id, parse.blocks(payload),
                                        ("hotel_id", "block_id")))

    def availability(self, conn, hotel_id: int, start: date, end: date) -> None:
        for a, b in windows(start, end):
            payload = self._call("availability", {"filter": {
                "start_date": iso(a), "end_date": iso(b), "central_id": self.cfg.central_id,
                "alojamiento_id": self.cfg.alojamiento_id}}, f"{a}..{b}")
            if payload is None:
                continue
            avail, rates = parse.availability(payload)
            now = datetime.now().astimezone()
            window = ("stay_date BETWEEN %s AND %s", (a, b))
            n = store.save(conn, "fns_availability", hotel_id, [{**r, "fetched_at": now} for r in avail],
                           ("hotel_id", "stay_date", "room_type_id"), delete=window)
            store.save(conn, "fns_rates", hotel_id, [{**r, "fetched_at": now} for r in rates],
                       ("hotel_id", "stay_date", "room_type_id", "rate_id", "occupancy"), delete=window)
            self._stored(n)

    # --- the run ----------------------------------------------------------------------------------

    def run(self, conn: psycopg.Connection, backfill: bool | None = None, today: date | None = None,
            only: set[str] | None = None) -> dict:
        """Import everything; returns {"run_id", "status", "calls"}."""
        cfg = self.cfg
        today = today or datetime.now(cfg.tz).date()
        store.ensure_schema(conn)
        hotel_id = store.ensure_hotel(conn, cfg)
        backfill = not store.has_history(conn, hotel_id) if backfill is None else backfill
        history = today - timedelta(days=cfg.backfill_days if backfill else cfg.refresh_days)
        run_id = store.start_run(conn, hotel_id, backfill)
        self.calls = []
        log.info("FNS import for %s (alojamiento %s): %s from %s", cfg.hotel_code, cfg.alojamiento_id,
                 "first import" if backfill else "daily refresh", history)
        steps = [
            ("master", lambda: self.master(conn, hotel_id)),
            ("accounting", lambda: self.accounting(conn, hotel_id, history, today)),
            ("currency", None),
            ("exchange", lambda: self.exchange(conn, ctx["moneda_id"], history, today)),
            ("revenue", lambda: self.revenue(conn, hotel_id, ctx["moneda_id"], history,
                                             today + timedelta(days=cfg.forward_days))),
            ("production_cc", lambda: self.production_cc(conn, hotel_id, ctx["moneda_id"], history, today)),
            ("production", lambda: self.production(conn, hotel_id, ctx["moneda_id"], history, today, today)),
            ("sales_reservations", lambda: self.sales_reservations(
                conn, hotel_id, history, today + timedelta(days=SALES_AHEAD_DAYS))),
            ("pos", lambda: self.pos(conn, hotel_id, history, today)),
            ("reservations", lambda: self.reservations(conn, hotel_id, history, today)),
            ("blocks", lambda: self.blocks(conn, hotel_id, min(history, today - timedelta(days=cfg.refresh_days)),
                                           today + timedelta(days=BLOCKS_AHEAD_DAYS))),
            ("availability", lambda: self.availability(
                conn, hotel_id, today, today + timedelta(days=min(cfg.forward_days, AVAILABILITY_AHEAD_DAYS)))),
        ]
        ctx: dict[str, Any] = {}
        status = "ok"
        try:
            for name, step in steps:
                if name == "currency":
                    ctx["moneda_id"], currency = store.hotel_currency(conn, hotel_id, cfg)
                    store.set_currency(conn, hotel_id, currency)
                    log.info("amounts in %s (FNS currency id %s)", currency, ctx["moneda_id"])
                    continue
                if only and name not in only:
                    continue
                try:
                    step()
                except (psycopg.Error, ValueError, TypeError, KeyError) as e:
                    # Unexpected data the parsers or the database rejected: record, go on.
                    self.calls.append({"method": name, "ok": False, "error": f"{e.__class__.__name__}: {e}"})
                    log.exception("storing %s failed", name)
            store.set_total_rooms(conn, hotel_id)
        except AuthError as e:
            log.error("%s", e)
            status = "failed"
        if status == "ok" and any(not c.get("ok") and not c.get("optional") for c in self.calls):
            status = "partial"
        store.finish_run(conn, run_id, status, self.calls)
        rows = sum(c.get("rows", 0) for c in self.calls)
        log.info("FNS import %s: %s calls, %s rows stored", status, len(self.calls), rows)
        return {"run_id": run_id, "status": status, "calls": self.calls, "rows": rows, "backfill": backfill}
