"""Settings from the environment (.env through Docker Compose), and per hotel from pms.fns_hotels
(the hotels added in the website's Admin page)."""

import dataclasses
import os
from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_URL = "https://ms.fnsmanager.com"


def _int(env, name, default=None, positive=True):
    raw = (env.get(name) or "").strip()
    if not raw:
        if default is None:
            raise ValueError(f"{name} is required.")
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number (it is {raw!r}).") from None
    if positive and value <= 0:
        raise ValueError(f"{name} must be above 0.")
    return value


def _seconds(env, name, default):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number of seconds (it is {raw!r}).") from None
    if value < 0:
        raise ValueError(f"{name} can't be negative.")
    return value


@dataclass(frozen=True)
class Config:
    user: str
    password: str = field(repr=False)
    central_id: int
    alojamiento_id: int
    pms_id: int | None = None
    database_url: str = ""
    base_url: str = BASE_URL
    # The hotel as it appears in the reports.
    hotel_code: str = "FRA"
    hotel_name: str = "Fragata"
    hotel_city: str = ""
    hotel_country: str = ""
    timezone: str = "Europe/Madrid"
    # FNS currency id of the hotel's own currency (1 = EUR, 2 = USD) and its ISO code; amounts are
    # requested in it. Unset: taken from the accounting entries, else EUR.
    moneda_id: int | None = None
    currency: str | None = None
    # Also store daily exchange rates from the hotel's currency to these FNS currency ids.
    exchange_to: tuple[int, ...] = (1, 2)
    # When the daily import runs (hotel time), how far back it refreshes, how far ahead it reads
    # on-the-books business, and how much history the first import loads.
    run_at: time = time(3, 0)
    refresh_days: int = 7
    forward_days: int = 365
    backfill_days: int = 365
    # Seconds between API calls, to be gentle with the API (FNS_PAUSE).
    pause: float = 1.0
    # After a run the API cut short, try again this many minutes later instead of the next night.
    retry_minutes: int = 60
    # Decrypts the FNS passwords saved per hotel in the Admin page.
    secret_key: str = field(default="", repr=False)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @classmethod
    def from_env(cls, env=None, require_hotel: bool = True) -> "Config":
        """require_hotel=False: the settings shared by every hotel (the hotel itself may come from
        pms.fns_hotels; FNS_ALOJAMIENTO_ID then only adds that hotel on the first start)."""
        env = os.environ if env is None else env
        required = ("FNS_USER", "FNS_PASSWORD", "FNS_CENTRAL_ID", "FNS_ALOJAMIENTO_ID") if require_hotel else ()
        missing = [n for n in required if not (env.get(n) or "").strip()]
        if missing:
            raise ValueError(f"Set {', '.join(missing)} in .env (credentials from FNSrooms).")
        timezone = _timezone((env.get("FNS_TIMEZONE") or "Europe/Madrid").strip(), "FNS_TIMEZONE")
        run_at = (env.get("FNS_SYNC_TIME") or "03:00").strip()
        try:
            hh, mm = run_at.split(":")
            run_at_time = time(int(hh), int(mm))
        except ValueError:
            raise ValueError(f"FNS_SYNC_TIME must look like 03:00 (it is {run_at!r}).") from None
        exchange = tuple(int(x) for x in (env.get("FNS_EXCHANGE_TO") or "1,2").replace(" ", "").split(",") if x)
        currency = (env.get("FNS_CURRENCY") or "").strip().upper() or None
        if currency and len(currency) != 3:
            raise ValueError(f"FNS_CURRENCY must be a 3-letter code like EUR or COP (it is {currency!r}).")
        code = (env.get("FNS_HOTEL_CODE") or "FRA").strip().upper()
        return cls(
            user=(env.get("FNS_USER") or "").strip(),
            password=env.get("FNS_PASSWORD") or "",
            central_id=_int(env, "FNS_CENTRAL_ID", 0 if not require_hotel else None, positive=require_hotel),
            alojamiento_id=_int(env, "FNS_ALOJAMIENTO_ID", 0 if not require_hotel else None, positive=require_hotel),
            pms_id=_int(env, "FNS_PMS_ID", 0, positive=False) or None,
            database_url=(env.get("FNS_DATABASE_URL") or env.get("DATABASE_URL") or "").strip(),
            base_url=(env.get("FNS_BASE_URL") or BASE_URL).rstrip("/"),
            hotel_code=code,
            hotel_name=(env.get("FNS_HOTEL_NAME") or "Fragata").strip(),
            hotel_city=(env.get("FNS_HOTEL_CITY") or "").strip(),
            hotel_country=(env.get("FNS_HOTEL_COUNTRY") or "").strip(),
            timezone=timezone,
            moneda_id=_int(env, "FNS_MONEDA_ID", 0, positive=False) or None,
            currency=currency,
            exchange_to=exchange,
            run_at=run_at_time,
            refresh_days=_int(env, "FNS_REFRESH_DAYS", 7),
            forward_days=_int(env, "FNS_FORWARD_DAYS", 365),
            backfill_days=_int(env, "FNS_BACKFILL_DAYS", 365),
            retry_minutes=_int(env, "FNS_RETRY_MINUTES", 60),
            secret_key=env.get("FNS_SECRET_KEY") or "",
        )

    @property
    def has_hotel(self) -> bool:
        return self.alojamiento_id > 0 and self.central_id > 0

    def for_hotel(self, row: dict, account: bool = True) -> "Config":
        """This configuration for a pms.fns_hotels row: its ids, name and schedule, and its own FNS
        account when it has one (else the one in .env). account=False: without checking the account."""
        from .secret import decrypt

        user, password = (row.get("fns_user") or "").strip(), self.password
        if not user:
            user = self.user
        elif account:
            if not row.get("fns_password"):
                raise ValueError(f"hotel {row['code']}: enter the FNS password for {user} in the Admin page.")
            password = decrypt(row["fns_password"], self.secret_key)
        if account and (not user or not password):
            raise ValueError(f"hotel {row['code']}: no FNS account. Enter one in the Admin page, or set FNS_USER "
                             "and FNS_PASSWORD in .env.")
        return dataclasses.replace(
            self, user=user, password=password, central_id=row["central_id"], alojamiento_id=row["alojamiento_id"],
            pms_id=row.get("pms_id") or None, hotel_code=row["code"], hotel_name=row["name"],
            hotel_city=row.get("city") or "", hotel_country=row.get("country") or "",
            timezone=_timezone(row.get("timezone") or self.timezone, f"hotel {row['code']} time zone"),
            moneda_id=row.get("moneda_id") or None, currency=row.get("currency") or None,
            run_at=row.get("sync_time") or self.run_at, backfill_days=row.get("backfill_days") or self.backfill_days)


def _timezone(name: str, label: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"{label} {name!r} is not a time zone name like Europe/Madrid or America/Bogota.") from None
    return name
