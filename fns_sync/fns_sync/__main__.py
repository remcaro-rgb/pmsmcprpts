"""Import the FNSrooms PMS API into the reporting database.

    python -m fns_sync check            # call each API method once and show what it returns (no data saved)
    python -m fns_sync run              # import now (the first run also loads FNS_BACKFILL_DAYS of history)
    python -m fns_sync run --backfill   # reload the full history
    python -m fns_sync status           # the last imports
    python -m fns_sync daemon           # import every day at FNS_SYNC_TIME (what the fns-sync service runs)

Settings come from the environment: FNS_USER, FNS_PASSWORD, FNS_CENTRAL_ID, FNS_ALOJAMIENTO_ID and
FNS_DATABASE_URL (the database owner); see .env.example for the optional ones.
"""

import argparse
import json
import logging
import re
import signal
import sys
import time
from datetime import datetime, timedelta

import psycopg

from . import store
from .client import ENDPOINTS, AuthError, FNSClient, FNSError
from .config import Config
from .sync import STEPS, Sync

log = logging.getLogger("fns_sync")
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


def check(cfg: Config) -> int:
    """One small call per method (yesterday and today) to confirm the credentials and the API."""
    client = FNSClient(cfg, retries=0)
    today = datetime.now(cfg.tz).date()
    y, t = (today - timedelta(days=1)).isoformat(), today.isoformat()
    a, c = cfg.alojamiento_id, cfg.central_id
    common = {"alojamiento_id": a, "start_date": y, "end_date": t}
    bodies = {
        "master": {"filter": {"central_id": "", "alojamiento_id": a, "listado": "th,cc,canales,segmentos"}},
        "exchange": {"central_id": c, "start_date": y, "end_date": t, "moneda_src_id": cfg.moneda_id or 1,
                     "moneda_dst_id": 2 if (cfg.moneda_id or 1) != 2 else 1},
        "production": {"filter": {**common, "central_id": c, "moneda_id": cfg.moneda_id or 1, "impuesto": 0,
                                  "fecha_simulacion": t, "fuente": "", "total": 0},
                       "group": ["canal_id", "segmento_id"]},
        "production_cc": {"filter": {**common, "central_id": c, "moneda_id": cfg.moneda_id or 1, "impuesto": 0}},
        "sales_reservations": {"filter": common},
        "pos": {"filter": {**common, "central_id": c, "tipo": 0}},
        "revenue": {"filter": {**common, "central_id": "", "moneda_id": cfg.moneda_id or 1, "impuesto": 0}},
        "payments": {"filter": common},
        "invoices": {"filter": common},
        "accounting_production": {"filter": common},
        "reservations": {"filter": {**common, "central_id": c, "estado": "Todas", "verDetalles": 1}},
        "blocks": {"filter": {**common, "central_id": c}},
        "availability": {"filter": {**common, "central_id": c}},
    }
    failures = 0
    print(f"FNS API check for alojamiento {a} (central {c}), {y} to {t}:")
    for name in ENDPOINTS:
        try:
            result = client.call(name, bodies[name])
            print(f"  OK    {ENDPOINTS[name]:34} {'no data (404)' if result is None else _shape(result)}")
        except AuthError as e:
            print(f"  DENIED {ENDPOINTS[name]:33} {e}")
            failures += 1
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


def status(cfg: Config) -> None:
    with _connect(cfg) as conn:
        for run_id, code, started, finished, state, backfill, calls in store.last_runs(conn):
            failed = [c for c in calls if not c.get("ok")]
            rows = sum(c.get("rows", 0) for c in calls)
            print(f"#{run_id} {code} {started:%Y-%m-%d %H:%M} {state:8} {'first import ' if backfill else ''}"
                  f"{len(calls)} calls, {rows} rows" + (f", {len(failed)} failed" if failed else ""))
            for c in failed[:5]:
                print(f"    {c.get('method')} {c.get('window', '')}: {c.get('error')}")


def next_run(cfg: Config, now: datetime) -> datetime:
    at = datetime.combine(now.date(), cfg.run_at, tzinfo=cfg.tz)
    return at if at > now else at + timedelta(days=1)


def daemon(cfg: Config) -> None:
    """Import now unless today's import already ran, then every day at FNS_SYNC_TIME."""
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    with _connect(cfg) as conn:
        store.ensure_schema(conn)
        last = conn.execute("SELECT max(r.started_at) FROM pms.fns_sync_runs r JOIN pms.hotels h ON h.id = r.hotel_id "
                            "WHERE h.alojamiento_id = %s AND r.status IN ('ok', 'partial')",
                            (cfg.alojamiento_id,)).fetchone()[0]
    due = last is None or last.astimezone(cfg.tz).date() < datetime.now(cfg.tz).date()
    while not stop["now"]:
        if due:
            try:
                run_once(cfg, None)
            except (psycopg.Error, OSError, RuntimeError) as e:
                log.error("import failed: %s", e)
        wake = next_run(cfg, datetime.now(cfg.tz))
        log.info("next import at %s", wake.strftime("%Y-%m-%d %H:%M %Z"))
        while not stop["now"] and datetime.now(cfg.tz) < wake:
            time.sleep(1)  # short, so docker compose stop ends it promptly
        due = True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fns_sync", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--backfill", action="store_true", help="reload FNS_BACKFILL_DAYS of history")
    r.add_argument("--only", help="comma-separated steps, e.g. revenue,reservations")
    sub.add_parser("status")
    sub.add_parser("daemon")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for name in ("httpx2", "httpx", "httpcore"):  # one line per request otherwise
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        cfg = Config.from_env()
    except ValueError as e:
        print(f"fns_sync: {e}", file=sys.stderr)
        return 2
    if args.command == "check":
        return check(cfg)
    if args.command == "status":
        status(cfg)
        return 0
    if args.command == "daemon":
        daemon(cfg)
        return 0
    only = {s.strip() for s in args.only.split(",")} if args.only else None
    if only and only - set(STEPS):
        print(f"fns_sync: unknown steps {sorted(only - set(STEPS))}; choose from {', '.join(STEPS)}", file=sys.stderr)
        return 2
    result = run_once(cfg, True if args.backfill else None, only)
    failed = [c for c in result["calls"] if not c.get("ok")]
    print(json.dumps({"status": result["status"], "first_import": result["backfill"], "calls": len(result["calls"]),
                      "rows": result["rows"], "failed": failed[:10]}, indent=2, default=str))
    return 0 if result["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
