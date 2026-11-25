"""Active bookings of the imported hotels, straight from the FNS API (`python -m fns_sync bookings`):
the guest's name, the booking number, the check-in date and the email, as CSV.

FNS's reservation search (reservas/listado) takes at most 30 days per call, and what the days mean
depends on when they are: up to today it finds bookings by the day they were made, after today by
their stay (whatever day they were made). So this asks for the active ones (estado "activas") made
in the last `created_days` days, then for the ones staying after today, 30 days at a time, until
FUTURE_EMPTY windows in a row bring nothing new (or `ahead_days`), and keeps the stays that haven't
ended (checking in today or later, or staying now)."""

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
FUTURE_EMPTY = 4  # windows after today with no new booking before stopping
AHEAD_DAYS = 3 * 365


def _name(b: dict) -> str:
    """The holder's name (else the client's), first name and surname."""
    for who in ("holder", "client"):
        name = " ".join(p for p in (b.get(f"{who}_name"), b.get(f"{who}_surname")) if p)
        if name:
            return name
    return ""


def _windows(today: date, created_days: int, ahead_days: int):
    yield from windows(today - timedelta(days=created_days), today, CHUNK_DAYS)
    yield from windows(today + timedelta(days=1), today + timedelta(days=ahead_days), CHUNK_DAYS)


def active_bookings(cfg: Config, client: FNSClient, today: date, created_days: int = 365,
                    ahead_days: int = AHEAD_DAYS) -> list[dict]:
    """The hotel's active bookings that haven't ended, one row each, by check-in date."""
    found: dict[str, dict] = {}
    empty_run = 0
    for a, b in _windows(today, created_days, ahead_days):
        if a > today and empty_run >= FUTURE_EMPTY:
            break
        before = len(found)
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
        if a > today:  # a long stay comes back in every window it touches: count only new bookings
            empty_run = empty_run + 1 if len(found) == before else 0
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
