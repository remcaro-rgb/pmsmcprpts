"""One import run: call every FNS method for the configured hotel and store the results.

Each method asks for its whole date range in one call (reservations, blocks and availability: 30
days, the API's limit); when the API rejects a long range or is too slow with it, that range is read again in 30-day
parts. Each answer is saved in its own transaction, so one failing call doesn't lose the others;
the run is recorded in pms.fns_sync_runs with every call's window, row count and error."""

import logging
import time as _time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterator

import psycopg

from . import parse, store
from .client import AuthError, FNSClient, FNSError, MissingRate, TooSlow, Unreachable
from .config import Config

log = logging.getLogger("fns_sync")

MASTER_KINDS = ("th", "th_completo", "habitaciones", "cc", "ofertas", "canales", "subcanales", "segmentos",
                "agencias", "agentes", "empresas", "paises", "usuarios", "sucursales", "salones", "pv",
                "servicios", "usuariosGastro", "alojamientos", "clientes")
RESERVATION_STATES = ("Todas", "canceladas", "modificadas")
# FNS limits reservation, block and availability searches to 30 days; other ranges fall back to this.
CHUNK_DAYS = 30
SALES_AHEAD_DAYS = 90
BLOCKS_AHEAD_DAYS = 90
AVAILABILITY_AHEAD_DAYS = 180
# Steps of a run (for `run --only`): the most asked-about data first, the slow day-by-day report last.
STEPS = ("master", "revenue", "production_cc", "sales_reservations", "reservations", "availability", "blocks",
         "pos", "accounting", "exchange", "production")
# Steps that load FNS_BACKFILL_DAYS of history the first time (then only the recent days).
HISTORY_STEPS = ("revenue", "production_cc", "sales_reservations", "reservations", "pos", "accounting", "exchange",
                 "production")
# Calls in a row that may fail to connect before the run gives up (the API is down or blocking us).
MAX_UNREACHABLE = 3


class StopRun(Exception):
    pass


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
        self.unreachable = 0

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
            self.unreachable = 0
            return result
        except AuthError as e:
            entry.update(ok=False, error=str(e))
            raise
        except Unreachable as e:
            entry.update(ok=False, error=str(e))
            log.warning("%s %s: %s", name, window, e)
            self.unreachable += 1
            if self.unreachable >= MAX_UNREACHABLE:
                raise StopRun(f"the FNS API didn't answer {self.unreachable} calls in a row; stopping this run "
                              f"(the import resumes where it stopped)") from e
            return None
        except MissingRate as e:
            # The days without a rate yet are read again by the next nights' refresh.
            entry.update(ok=False, error=str(e), optional=True, split=True)
            log.warning("%s %s: %s", name, window, e)
            return None
        except (TooSlow, FNSError) as e:
            entry.update(ok=False, error=str(e), optional=optional, split=True)
            log.warning("%s %s: %s", name, window, e)
            return None
        finally:
            entry["seconds"] = round(_time.monotonic() - started, 2)
            if self.cfg.pause:
                self.sleep(self.cfg.pause)

    def _stored(self, rows: int) -> None:
        self.calls[-1]["rows"] = self.calls[-1].get("rows", 0) + rows

    def _ranged(self, name: str, body: Callable[[date, date], dict], start: date, end: date, label: str = "",
                optional: bool = False, max_days: int | None = None) -> Iterator[tuple[date, date, Any]]:
        """(from, to, answer) for start..end, in one call or in `max_days` parts. A long call the API
        rejects or is too slow with is made again in CHUNK_DAYS parts. Answers may be None (no data)."""
        span = max_days or max((end - start).days + 1, 1)
        for a, b in windows(start, end, span):
            payload = self._call(name, body(a, b), f"{label}{a}..{b}", optional)
            entry = self.calls[-1]
            if entry.get("ok"):
                yield a, b, payload
            elif entry.get("split") and (b - a).days >= CHUNK_DAYS:
                entry["optional"] = True  # replaced by the shorter calls below
                log.info("%s: reading %s..%s in %s-day parts instead", name, a, b, CHUNK_DAYS)
                for c, d in windows(a, b):
                    payload = self._call(name, body(c, d), f"{label}{c}..{d}", optional)
                    if self.calls[-1].get("ok"):
                        yield c, d, payload

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
            body = lambda a, b: {"filter": self._filter(  # noqa: E731
                alojamiento_id=self.cfg.alojamiento_id, start_date=iso(a), end_date=iso(b))}
            for a, b, payload in self._ranged(name, body, start, end):
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
            body = lambda a, b: self._filter(  # noqa: E731
                central_id=self.cfg.central_id, start_date=iso(a), end_date=iso(b),
                moneda_src_id=moneda_id, moneda_dst_id=target)
            for a, b, payload in self._ranged("exchange", body, start, end, f"{moneda_id}->{target} ", optional=True):
                if payload is not None:
                    self._stored(store.save(conn, "fns_exchange_rates", None, parse.exchange(payload, moneda_id, target),
                                            ("rate_date", "from_moneda_id", "to_moneda_id")))

    def revenue(self, conn, hotel_id: int, moneda_id: int, start: date, end: date) -> None:
        body = lambda a, b: {"filter": self._filter(  # noqa: E731
            alojamiento_id=self.cfg.alojamiento_id, central_id="", start_date=iso(a), end_date=iso(b),
            moneda_id=moneda_id, impuesto=0)}
        for a, b, payload in self._ranged("revenue", body, start, end):
            if payload is not None:
                rows = [{**r, "fetched_at": datetime.now().astimezone()} for r in parse.revenue(payload)]
                self._stored(store.save(conn, "fns_revenue_daily", hotel_id, rows, ("hotel_id", "stay_date")))

    def production_cc(self, conn, hotel_id: int, moneda_id: int, start: date, end: date) -> None:
        body = lambda a, b: {"filter": self._filter(  # noqa: E731
            alojamiento_id=self.cfg.alojamiento_id, central_id=self.cfg.central_id, start_date=iso(a),
            end_date=iso(b), moneda_id=moneda_id, impuesto=0)}
        for a, b, payload in self._ranged("production_cc", body, start, end):
            self._stored(store.save(conn, "fns_production_cc", hotel_id,
                                    parse.production_cc(payload, self.cfg.alojamiento_id),
                                    ("hotel_id", "prod_date", "cc_id"),
                                    delete=("prod_date BETWEEN %s AND %s", (a, b))))

    def production(self, conn, hotel_id: int, moneda_id: int, start: date, end: date, today: date) -> None:
        """The report groups by channel but has no dates, so a range gives one total per channel for
        it. The history before the refresh window is one call (stored as one period); the recent
        days are one call each, so they stay daily."""
        body = lambda a, b: {"filter": self._filter(  # noqa: E731
            alojamiento_id=self.cfg.alojamiento_id, central_id=self.cfg.central_id, start_date=iso(a),
            end_date=iso(b), moneda_id=moneda_id, impuesto=0, fecha_simulacion=iso(today), fuente="",
            total=0), "group": ["canal_id", "segmento_id"]}

        def save(payload, a: date, b: date) -> None:
            rows = [{**r, "period_end": b} for r in parse.production(payload, a, self.cfg.alojamiento_id)]
            self._stored(store.save(conn, "fns_production", hotel_id, rows,
                                    ("hotel_id", "prod_date", "channel_id", "segment_id"),
                                    delete=("prod_date BETWEEN %s AND %s", (a, b))))

        daily_from = max(start, today - timedelta(days=self.cfg.refresh_days))
        for a, b, payload in self._ranged("production", body, start, daily_from - timedelta(days=1)):
            save(payload, a, b)
        for d, _, payload in self._ranged("production", body, daily_from, end, max_days=1):
            save(payload, d, d)

    def sales_reservations(self, conn, hotel_id: int, start: date, end: date) -> None:
        body = lambda a, b: {"filter": self._filter(  # noqa: E731
            alojamiento_id=self.cfg.alojamiento_id, start_date=iso(a), end_date=iso(b))}
        for a, b, payload in self._ranged("sales_reservations", body, start, end):
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
        body = lambda a, b: {"filter": self._filter(  # noqa: E731
            central_id=self.cfg.central_id, alojamiento_id=self.cfg.alojamiento_id, start_date=iso(a),
            end_date=iso(b), tipo=0)}
        for a, b, payload in self._ranged("pos", body, start, end):
            self._stored(store.save(conn, "fns_pos_sales", hotel_id, parse.pos(payload),
                                    ("hotel_id", "pos_id", "sale_date", "recipe_id"),
                                    delete=("sale_date BETWEEN %s AND %s", (a, b))))

    def reservations(self, conn, hotel_id: int, start: date, end: date) -> None:
        for state in RESERVATION_STATES:
            body = lambda a, b: {"filter": {  # noqa: E731
                "central_id": self.cfg.central_id, "alojamiento_id": self.cfg.alojamiento_id,
                "start_date": iso(a), "end_date": iso(b), "estado": state,
                "verTitular": 1, "verHuespedes": 1, "verDetalles": 1, "verInhouse": 1}}
            # The cancelled and modified searches only add updates.
            for a, b, payload in self._ranged("reservations", body, start, end, f"{state} ",
                                              optional=state != "Todas", max_days=CHUNK_DAYS):
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
        body = lambda a, b: {"filter": {  # noqa: E731
            "central_id": self.cfg.central_id, "alojamiento_id": self.cfg.alojamiento_id,
            "start_date": iso(a), "end_date": iso(b)}}
        for a, b, payload in self._ranged("blocks", body, start, end, max_days=CHUNK_DAYS):
            if payload is not None:
                self._stored(store.save(conn, "fns_room_blocks", hotel_id, parse.blocks(payload),
                                        ("hotel_id", "block_id")))

    def availability(self, conn, hotel_id: int, start: date, end: date) -> None:
        body = lambda a, b: {"filter": {  # noqa: E731
            "start_date": iso(a), "end_date": iso(b), "central_id": self.cfg.central_id,
            "alojamiento_id": self.cfg.alojamiento_id}}
        for a, b, payload in self._ranged("availability", body, start, end, max_days=CHUNK_DAYS):
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
        """Import everything; returns {"run_id", "status", "calls", "rows", "backfill", "pending"}.
        Each history step loads FNS_BACKFILL_DAYS until it has done so once (backfill=True: again),
        so an interrupted first import resumes where it stopped."""
        cfg = self.cfg
        today = today or datetime.now(cfg.tz).date()
        store.ensure_schema(conn)
        hotel_id = store.ensure_hotel(conn, cfg)
        loaded = set() if backfill else store.loaded_steps(conn, hotel_id)
        refresh_from = today - timedelta(days=cfg.refresh_days)
        history_from = today - timedelta(days=cfg.backfill_days)
        wanted = [s for s in HISTORY_STEPS if not only or s in only]
        backfilling = [s for s in wanted if s not in loaded]
        run_id = store.start_run(conn, hotel_id, bool(backfilling))
        self.calls, self.unreachable = [], 0
        log.info("FNS import for %s (alojamiento %s): %s", cfg.hotel_code, cfg.alojamiento_id,
                 f"loading history from {history_from} for {', '.join(backfilling)}" if backfilling
                 else f"daily refresh from {refresh_from}")

        def since(step: str) -> date:
            return refresh_from if step in loaded else history_from

        ahead = lambda days: today + timedelta(days=days)  # noqa: E731
        ctx: dict[str, Any] = {}
        steps = {
            "master": lambda: self.master(conn, hotel_id),
            "revenue": lambda: self.revenue(conn, hotel_id, ctx["moneda_id"], since("revenue"), ahead(cfg.forward_days)),
            "production_cc": lambda: self.production_cc(conn, hotel_id, ctx["moneda_id"], since("production_cc"), today),
            "sales_reservations": lambda: self.sales_reservations(conn, hotel_id, since("sales_reservations"),
                                                                  ahead(SALES_AHEAD_DAYS)),
            "reservations": lambda: self.reservations(conn, hotel_id, since("reservations"), today),
            "availability": lambda: self.availability(conn, hotel_id, today,
                                                      ahead(min(cfg.forward_days, AVAILABILITY_AHEAD_DAYS))),
            "blocks": lambda: self.blocks(conn, hotel_id, refresh_from, ahead(BLOCKS_AHEAD_DAYS)),
            "pos": lambda: self.pos(conn, hotel_id, since("pos"), today),
            "accounting": lambda: self.accounting(conn, hotel_id, since("accounting"), today),
            "exchange": lambda: self.exchange(conn, ctx["moneda_id"], since("exchange"), today),
            "production": lambda: self.production(conn, hotel_id, ctx["moneda_id"], since("production"), today, today),
        }
        order = list(STEPS)
        if not cfg.moneda_id and not store.has_accounting(conn, hotel_id):
            order.remove("accounting")  # the hotel's currency comes from the accounting entries
            order.insert(1, "accounting")
        status = "ok"
        try:
            for name in order:
                if name not in ("master", "accounting") and "moneda_id" not in ctx:  # amounts need the currency
                    ctx["moneda_id"], currency = store.hotel_currency(conn, hotel_id, cfg)
                    store.set_currency(conn, hotel_id, currency)
                    log.info("amounts in %s (FNS currency id %s)", currency, ctx["moneda_id"])
                if only and name not in only:
                    continue
                first = len(self.calls)
                try:
                    steps[name]()
                except (psycopg.Error, ValueError, TypeError, KeyError) as e:
                    # Unexpected data the parsers or the database rejected: record, go on.
                    self.calls.append({"method": name, "ok": False, "error": f"{e.__class__.__name__}: {e}"})
                    log.exception("storing %s failed", name)
                failed = any(not c.get("ok") and not c.get("optional") for c in self.calls[first:])
                if name in backfilling and not failed:
                    store.mark_loaded(conn, hotel_id, name, history_from)
                    loaded.add(name)
                    log.info("%s: history loaded", name)
            store.set_total_rooms(conn, hotel_id)
        except (AuthError, StopRun) as e:
            log.error("%s", e)
            status = "failed"
        if status == "ok" and any(not c.get("ok") and not c.get("optional") for c in self.calls):
            status = "partial"
        store.finish_run(conn, run_id, status, self.calls)
        rows = sum(c.get("rows", 0) for c in self.calls)
        pending = [s for s in wanted if s not in loaded]
        log.info("FNS import %s: %s calls, %s rows stored%s", status, len(self.calls), rows,
                 f"; history still to load: {', '.join(pending)}" if pending else "")
        return {"run_id": run_id, "status": status, "calls": self.calls, "rows": rows,
                "backfill": bool(backfilling), "pending": pending}
