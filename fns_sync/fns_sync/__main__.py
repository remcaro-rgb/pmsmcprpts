"""Import the FNSrooms PMS API into the reporting database.

    python -m fns_sync check            # call each API method once and show what it returns (no data saved)
    python -m fns_sync check --date 2026-09-15   # the same for an earlier day
    python -m fns_sync run              # import now (the first run also loads FNS_BACKFILL_DAYS of history)
    python -m fns_sync run --backfill   # reload the full history
    python -m fns_sync history --from 2025-01-01 --plan   # the calls an earlier range needs (none made)
    python -m fns_sync history --from 2025-01-01          # load it (up to the day before the history
                                                          # already loaded; --to to choose; --pause 30)
    python -m fns_sync status           # the last imports
    python -m fns_sync daemon           # import every hotel daily (what the fns-sync service runs)

The hotels are added in the website's Admin page (FNS import), which shows each import's progress;
the hotel in .env (FNS_ALOJAMIENTO_ID...) is added on the service's first start. Commands take
--hotel CODE when there is more than one. Settings come from the environment: FNS_DATABASE_URL (the
database owner), FNS_USER and FNS_PASSWORD (the FNS account of the hotels without their own),
FNS_SECRET_KEY (decrypts the accounts saved in the Admin page); see .env.example for the others.
"""

import argparse
import dataclasses
import json
import logging
import re
import signal
import sys
import time
from datetime import date, datetime, timedelta

import psycopg

from . import runlog, store
from .client import ENDPOINTS, AuthError, FNSClient, FNSError, MissingRate
from .config import Config
from .sync import HISTORY_STEPS, STEPS, Sync, without_none

log = logging.getLogger("fns_sync")
DB_RETRY_SECONDS = 30
POLL_SECONDS = 15  # how often the service looks for hotels to import (new ones, "Import now")
FIELD_NAME = re.compile(r"[A-Za-z_@ ]{1,30}")


def _connect(cfg: Config) -> psycopg.Connection:
    if not cfg.database_url:
        raise SystemExit("Set FNS_DATABASE_URL (e.g. postgresql://pms:pms@db:5432/pms).")
    return psycopg.connect(cfg.database_url, autocommit=True)


def _shape(v, depth: int = 0) -> str:
    """The structure of a response without its values (safe to share: no guest data)."""
    if isinstance(v, dict):
        if not v:
            return "{}"
        keys = list(v)
        inner = _shape(v[keys[0]], depth + 1) if depth < 3 else "…"
        # Only field names are shown: ids, dates and tax ids (keys of some answers) are counted.
        named = all(FIELD_NAME.fullmatch(str(k)) for k in keys[:20])
        listed = ", ".join(map(str, keys[:12])) if named else f"{len(keys)} ids"
        return f"{{{listed}{', …' if named and len(keys) > 12 else ''}}} -> {inner}"
    if isinstance(v, list):
        return f"[{len(v)} × {_shape(v[0], depth + 1) if v and depth < 3 else '…'}]"
    return type(v).__name__


def check(cfg: Config, day: date | None = None) -> int:
    """One small call per method (the day before `day` and `day`, by default yesterday and today)
    to confirm the credentials and the API."""
    client = FNSClient(cfg, retries=0)
    today = day or datetime.now(cfg.tz).date()
    y, t = (today - timedelta(days=1)).isoformat(), today.isoformat()
    a, c = cfg.alojamiento_id, cfg.central
    common = {"alojamiento_id": a, "start_date": y, "end_date": t}
    bodies = {
        "master": {"filter": {"central_id": cfg.central_blank, "alojamiento_id": a, "listado": "th,cc,canales,segmentos"}},
        "exchange": {"central_id": c, "start_date": y, "end_date": t, "moneda_src_id": cfg.moneda_id or 1,
                     "moneda_dst_id": 2 if (cfg.moneda_id or 1) != 2 else 1},
        "production": {"filter": {**common, "central_id": c, "moneda_id": cfg.moneda_id or 1, "impuesto": 0,
                                  "fecha_simulacion": t, "fuente": "", "total": 0},
                       "group": ["canal_id", "segmento_id"]},
        "production_cc": {"filter": {**common, "central_id": c, "moneda_id": cfg.moneda_id or 1, "impuesto": 0}},
        "sales_reservations": {"filter": common},
        "pos": {"filter": {**common, "central_id": c, "tipo": 0}},
        "revenue": {"filter": {**common, "central_id": cfg.central_blank, "moneda_id": cfg.moneda_id or 1, "impuesto": 0}},
        "payments": {"filter": common},
        "invoices": {"filter": common},
        "accounting_production": {"filter": common},
        "reservations": {"filter": {**common, "central_id": c, "estado": "Todas", "verDetalles": 1}},
        "blocks": {"filter": {**common, "central_id": c}},
        "availability": {"filter": {**common, "central_id": c}},
    }
    if cfg.pms_id is not None:  # as the import sends it (not to the reservation, block and availability searches)
        for name, body in bodies.items():
            if name not in ("reservations", "blocks", "availability"):
                (body["filter"] if "filter" in body else body)["pms_id"] = cfg.pms_id
    failures = 0
    print(f"FNS API check for alojamiento {a} (central {c or 'none'}), {y} to {t}:")
    for name in ENDPOINTS:
        try:
            result = client.call(name, without_none(bodies[name]))
            print(f"  OK    {ENDPOINTS[name]:34} {'no data' if result is None else _shape(result)}")
        except AuthError as e:
            print(f"  DENIED {ENDPOINTS[name]:33} {e}")
            failures += 1
        except MissingRate as e:
            print(f"  NO RATE {ENDPOINTS[name]:32} {e} (the import retries these days on later nights; "
                  "try --date with an older day)")
        except FNSError as e:
            print(f"  ERROR {ENDPOINTS[name]:34} {e}")
            failures += 1
    client.close()
    print("All methods answered." if not failures else f"{failures} of {len(ENDPOINTS)} methods failed.")
    return 1 if failures else 0


def run_once(cfg: Config, backfill: bool | None, only: set[str] | None = None) -> dict:
    with _connect(cfg) as conn:
        sync = Sync(cfg)
        try:
            return sync.run(conn, backfill=backfill, only=only)
        finally:
            sync.client.close()


def history(cfg: Config, start: date, end: date | None, only: set[str] | None, plan_only: bool) -> int:
    """Load an earlier range of history (by default up to the day before the history already loaded)."""
    with _connect(cfg) as conn:
        if end is None:
            row = conn.execute("SELECT id FROM pms.hotels WHERE alojamiento_id = %s", (cfg.alojamiento_id,)).fetchone() \
                if conn.execute("SELECT to_regclass('pms.fns_sync_steps')").fetchone()[0] else None
            first = store.history_start(conn, row[0]) if row else None
            if first is None:
                print("fns_sync: no history loaded yet; pass --to, or let the first import run", file=sys.stderr)
                return 2
            end = first - timedelta(days=1)
        if end < start:
            print(f"fns_sync: nothing to load: the history already starts on {end + timedelta(days=1)}", file=sys.stderr)
            return 0
        sync = Sync(cfg)
        calls = sync.plan(start, end, only)
        total = sum(calls.values())
        print(f"History {start}..{end} ({(end - start).days + 1} days): {total} API calls "
              f"({', '.join(f'{s} {n}' for s, n in calls.items())}), {cfg.pause:g} s apart: "
              f"about {max(1, round(total * (cfg.pause + 3) / 60))} minutes. A range the API rejects is read "
              f"again in 30-day parts (more calls).")
        if plan_only:
            sync.client.close()
            return 0
        try:
            result = sync.history(conn, start, end, only=only)
        except ValueError as e:
            print(f"fns_sync: {e}", file=sys.stderr)
            return 2
        finally:
            sync.client.close()
    failed = [c for c in result["calls"] if not c.get("ok") and not c.get("optional")]
    print(json.dumps({"status": result["status"], "range": f"{start}..{end}", "calls": len(result["calls"]),
                      "rows": result["rows"], "loaded": result["loaded"], "failed_steps": result["failed_steps"],
                      "failed": failed[:10]}, indent=2, default=str))
    return 0 if result["status"] == "ok" else 1


def status(cfg: Config) -> None:
    with _connect(cfg) as conn:
        if not conn.execute("SELECT to_regclass('pms.fns_sync_runs')").fetchone()[0]:
            print("No imports yet. Start the fns-sync service (COMPOSE_PROFILES=fns in .env, then "
                  "docker compose up -d), or run one now: python -m fns_sync run")
            return
        for run_id, code, started, finished, state, backfill, calls in store.last_runs(conn):
            failed = [c for c in calls if not c.get("ok")]
            rows = sum(c.get("rows", 0) for c in calls)
            print(f"#{run_id} {code} {started:%Y-%m-%d %H:%M} {state:8} {'first import ' if backfill else ''}"
                  f"{len(calls)} calls, {rows} rows" + (f", {len(failed)} failed" if failed else ""))
            for c in failed[:5]:
                print(f"    {c.get('method')} {c.get('window', '')}: {c.get('error')}")
        for (hotel_id, code) in conn.execute("SELECT id, code FROM pms.hotels WHERE id IN "
                                             "(SELECT hotel_id FROM pms.fns_sync_runs) ORDER BY id").fetchall():
            pending = [s for s in HISTORY_STEPS if s not in store.loaded_steps(conn, hotel_id)]
            print(f"{code}: history loaded for all steps" if not pending
                  else f"{code}: history still to load for {', '.join(pending)} (the next run continues)")


def next_run(cfg: Config, now: datetime) -> datetime:
    at = datetime.combine(now.astimezone(cfg.tz).date(), cfg.run_at, tzinfo=cfg.tz)
    return at if at > now else at + timedelta(days=1)


def last_slot(cfg: Config, now: datetime) -> datetime:
    """The latest daily import time (FNS_SYNC_TIME, hotel time) at or before now."""
    at = datetime.combine(now.astimezone(cfg.tz).date(), cfg.run_at, tzinfo=cfg.tz)
    return at if at <= now else at - timedelta(days=1)


def due(cfg: Config, row: dict, times: dict, pending: bool, now: datetime) -> str | None:
    """Why the hotel's import should run now, or None. times: store.run_times."""
    if times["status"] == "running":
        return None
    retry = timedelta(minutes=cfg.retry_minutes)
    waited = times["finished"] is None or times["finished"] + retry <= now
    if row.get("run_requested_at") and (times["started"] is None or row["run_requested_at"] > times["started"]):
        return "requested in the Admin page"
    if times["started"] is None:
        return "first import"
    if pending:
        return "history still to load" if waited else None
    slot = last_slot(cfg, now)
    if times["last_ok"] is None or times["last_ok"] < slot:
        return "daily import" if times["started"] < slot or waited else None
    return None


def import_hotel(base: Config, conn: psycopg.Connection, row: dict, make_sync=Sync) -> dict | None:
    """One import of a pms.fns_hotels hotel; a hotel whose settings can't be used gets a failed run
    with the reason (shown in the Admin page) instead."""
    try:
        cfg = base.for_hotel(row)
    except ValueError as e:
        cfg = base.for_hotel(row, account=False)
        hotel_id = store.ensure_hotel(conn, cfg)
        store.link_hotel(conn, row["id"], hotel_id)
        run_id = store.start_run(conn, hotel_id, False)
        with runlog.context(hotel_id=hotel_id, run_id=run_id):
            log.error("%s", e)
        store.finish_run(conn, run_id, "failed", [{"method": "settings", "ok": False, "error": str(e)}])
        return None
    hotel_id = store.ensure_hotel(conn, cfg)
    store.link_hotel(conn, row["id"], hotel_id)
    sync = make_sync(cfg)
    try:
        return sync.run(conn)
    finally:
        sync.client.close()


def due_hotels(base: Config, conn: psycopg.Connection, now: datetime) -> list[tuple[dict, str]]:
    """The hotels to import now and why: the ones asked for in the Admin page first, then in the
    order they were added."""
    found = []
    for row in store.fns_hotels(conn):
        cfg = base.for_hotel(row, account=False)
        hotel_id = row["hotel_id"]
        pending = bool(set(HISTORY_STEPS) - (store.loaded_steps(conn, hotel_id) if hotel_id else set()))
        reason = due(cfg, row, store.run_times(conn, hotel_id) if hotel_id else
                     {"started": None, "finished": None, "status": None, "last_ok": None}, pending, now)
        if reason:
            found.append((row, reason))
    found.sort(key=lambda f: f[1] != "requested in the Admin page")
    return found


def next_due(base: Config, conn: psycopg.Connection, now: datetime) -> tuple[dict, str] | None:
    found = due_hotels(base, conn, now)
    return found[0] if found else None


def daemon(base: Config, poll: float = POLL_SECONDS) -> None:
    """Imports every hotel in pms.fns_hotels (the Admin page; the one in .env is added on the first
    start), one at a time: a new hotel loads its history first, then each imports daily at its
    FNS_SYNC_TIME (hotel time). A run the API cut short is retried after FNS_RETRY_MINUTES."""
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))

    def wait(seconds: float) -> None:
        end = time.monotonic() + seconds
        while not stop["now"] and time.monotonic() < end:
            time.sleep(min(1, seconds))  # short, so docker compose stop ends it promptly

    started = False
    while not stop["now"]:
        try:
            with _connect(base) as conn:
                if not started:
                    store.ensure_schema(conn)
                    store.add_env_hotel(conn, base)
                    if store.interrupt_running(conn):
                        log.info("an import was interrupted when the service stopped; it continues now")
                    started = True
                    log.info("importing %s", ", ".join(r["code"] for r in store.fns_hotels(conn)) or
                             "no hotels yet: add one in the website's Admin page (FNS import)")
                while not stop["now"]:
                    found = next_due(base, conn, datetime.now().astimezone())
                    if found is None:
                        wait(poll)
                        continue
                    row, reason = found
                    with runlog.context(hotel_id=row["hotel_id"]):
                        log.info("%s: %s", row["code"], reason)
                        try:
                            import_hotel(base, conn, row)
                        except (OSError, RuntimeError, ValueError) as e:
                            log.error("%s: import failed: %s", row["code"], e)
                            wait(poll)
                    store.prune_log(conn, base.log_days)
        except psycopg.OperationalError as e:
            # The database container may still be starting (or restarting): wait for it quietly.
            log.warning("database not reachable (%s); retrying in %d s", str(e).strip(), DB_RETRY_SECONDS)
            wait(DB_RETRY_SECONDS)
        except psycopg.Error as e:
            log.error("import failed: %s", e)
            wait(DB_RETRY_SECONDS)


def resolve(base: Config, code: str | None) -> Config:
    """The hotel a command is for: --hotel CODE, else the one in .env, else the only one added."""
    if code is None and base.has_hotel and not base.database_url:
        return Config.from_env()
    try:
        with _connect(base) as conn:
            rows = store.fns_hotels(conn, enabled_only=False) \
                if conn.execute("SELECT to_regclass('pms.fns_hotels')").fetchone()[0] else []
    except psycopg.OperationalError:
        rows = []
    if code:
        row = next((r for r in rows if r["code"] == code.upper()), None)
        if row is None:
            raise ValueError(f"no hotel {code.upper()}; hotels: {', '.join(r['code'] for r in rows) or 'none'}")
        return base.for_hotel(row)
    if base.has_hotel:  # the .env hotel, with its settings from the Admin page once it has been added
        row = next((r for r in rows if r["alojamiento_id"] == base.alojamiento_id), None)
        return base.for_hotel(row) if row else Config.from_env()
    if len(rows) == 1:
        return base.for_hotel(rows[0])
    raise ValueError("choose a hotel with --hotel CODE (" + (", ".join(r["code"] for r in rows) or
                     "none added yet: add one in the Admin page, or set FNS_ALOJAMIENTO_ID") + ")")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fns_sync", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    hotel = argparse.ArgumentParser(add_help=False)
    hotel.add_argument("--hotel", metavar="CODE", help="the hotel (its code); default: the one in .env, or the only one")
    c = sub.add_parser("check", parents=[hotel])
    c.add_argument("--date", type=date.fromisoformat, help="check this day (YYYY-MM-DD) instead of today")
    r = sub.add_parser("run", parents=[hotel])
    r.add_argument("--backfill", action="store_true", help="reload FNS_BACKFILL_DAYS of history")
    r.add_argument("--only", help="comma-separated steps, e.g. revenue,reservations")
    h = sub.add_parser("history", parents=[hotel], help="load an earlier range of history")
    h.add_argument("--from", dest="start", type=date.fromisoformat, required=True, help="first day (YYYY-MM-DD)")
    h.add_argument("--to", dest="end", type=date.fromisoformat,
                   help="last day (default: the day before the history already loaded)")
    h.add_argument("--only", help="comma-separated history steps, e.g. revenue,reservations")
    h.add_argument("--pause", type=float, help="seconds between API calls (default FNS_PAUSE, 1)")
    h.add_argument("--plan", action="store_true", help="show the calls it would make, without calling the API")
    sub.add_parser("status")
    sub.add_parser("daemon")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for name in ("httpx2", "httpx", "httpcore"):  # one line per request otherwise
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        base = Config.from_env(require_hotel=False)
        if args.command in ("daemon", "run", "history"):
            runlog.install(base.database_url)  # the Admin page's import log
        if args.command == "daemon":
            daemon(base)
            return 0
        if args.command == "status":
            status(base)
            return 0
        cfg = resolve(base, args.hotel)
    except ValueError as e:
        print(f"fns_sync: {e}", file=sys.stderr)
        return 2
    if args.command == "check":
        return check(cfg, args.date)
    if args.command == "history":
        if args.pause is not None:
            cfg = dataclasses.replace(cfg, pause=max(0.0, args.pause))
        steps = {s.strip() for s in args.only.split(",")} if args.only else None
        if steps and steps - set(HISTORY_STEPS):
            print(f"fns_sync: unknown steps {sorted(steps - set(HISTORY_STEPS))}; choose from "
                  f"{', '.join(HISTORY_STEPS)}", file=sys.stderr)
            return 2
        return history(cfg, args.start, args.end, steps, args.plan)
    only = {s.strip() for s in args.only.split(",")} if args.only else None
    if only and only - set(STEPS):
        print(f"fns_sync: unknown steps {sorted(only - set(STEPS))}; choose from {', '.join(STEPS)}", file=sys.stderr)
        return 2
    result = run_once(cfg, True if args.backfill else None, only)
    failed = [c for c in result["calls"] if not c.get("ok")]
    print(json.dumps({"status": result["status"], "loaded_history": result["backfill"], "calls": len(result["calls"]),
                      "rows": result["rows"], "history_still_to_load": result["pending"], "failed": failed[:10]},
                     indent=2, default=str))
    return 0 if result["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
