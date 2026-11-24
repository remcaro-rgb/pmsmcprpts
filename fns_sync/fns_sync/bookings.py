"""Active bookings of the imported hotels, straight from the FNS API (`python -m fns_sync bookings`):
the guest's name, the booking number, the check-in date and the email, as CSV.

FNS's reservation search (reservas/listado) finds bookings by the day they were made, at most 30
days per call, so this asks for the active ones (estado "activas") made in the last `created_days`
days, 30 days at a time, and keeps those whose stay hasn't ended (checking in today or later, or
staying now)."""

import csv
import logging
from datetime import date, timedelta
from typing import IO, Iterable

from . import parse
from .client import AuthError, FNSClient, FNSError
from .config import Config
from .sync import CHUNK_DAYS, windows, without_none

log = logging.getLogger("fns_sync")
COLUMNS = ("hotel", "name", "booking_number", "check_in", "email")


def _name(b: dict) -> str:
    """The holder's name (else the client's), first name and surname."""
    for who in ("holder", "client"):
        name = " ".join(p for p in (b.get(f"{who}_name"), b.get(f"{who}_surname")) if p)
        if name:
            return name
    return ""


def active_bookings(cfg: Config, client: FNSClient, today: date, created_days: int = 365) -> list[dict]:
    """The hotel's active bookings that haven't ended, one row each, by check-in date."""
    found: dict[str, dict] = {}
    for a, b in windows(today - timedelta(days=created_days), today, CHUNK_DAYS):
        body = {"filter": without_none({
            "central_id": cfg.central, "alojamiento_id": cfg.alojamiento_id, "start_date": a.isoformat(),
            "end_date": b.isoformat(), "estado": "activas", "verTitular": 1, "verHuespedes": 1})}
        payload = client.call("reservations", body)
        bookings, _ = parse.reservations(payload) if payload is not None else ([], [])
        for bk in bookings:
            ends = bk.get("departure") or bk.get("arrival")
            if bk.get("cancelled_at") or "cancel" in (bk.get("status") or "").lower() or ends is None or ends < today:
                continue
            found[bk["localizador"]] = {
                "hotel": cfg.hotel_code, "name": _name(bk), "booking_number": bk["localizador"],
                "check_in": bk.get("arrival"), "email": bk.get("holder_email") or bk.get("client_email") or ""}
    return sorted(found.values(), key=lambda r: (r["check_in"] or date.max, r["booking_number"]))


def write_csv(rows: Iterable[dict], out: IO[str]) -> int:
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    n = 0
    for row in rows:
        writer.writerow({**row, "check_in": row["check_in"].isoformat() if row["check_in"] else ""})
        n += 1
    return n


def for_hotels(configs: Iterable[Config], today: date, created_days: int,
               make_client=lambda cfg: FNSClient(cfg)) -> tuple[list[dict], list[str]]:
    """Every hotel's active bookings, and a line per hotel FNS refused (the others still count)."""
    rows, problems = [], []
    for cfg in configs:
        client = make_client(cfg)
        try:
            hotel_rows = active_bookings(cfg, client, today, created_days)
            rows += hotel_rows
            log.info("%s: %s active bookings", cfg.hotel_code, len(hotel_rows))
        except (AuthError, FNSError) as e:
            problems.append(f"{cfg.hotel_code}: {e}")
            log.error("%s: %s", cfg.hotel_code, e)
        finally:
            client.close()
    return rows, problems
