"""Hotels imported from FNSrooms (pms.fns_hotels), managed in the website's Admin page: adding one,
its settings, "Import now", and the progress of its imports. The fns-sync service does the
importing (fns_sync/__main__.py daemon): it picks up a new hotel within seconds, loads its history,
then imports it every day at its time; this module only reads and writes the database, and checks
a hotel's FNS account before it is saved."""

import base64
import hashlib
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx2
import psycopg
from cryptography.fernet import Fernet, InvalidToken
from psycopg.rows import dict_row

from .users import UserError

FNS_URL = "https://ms.fnsmanager.com"
MASTER = "/v1/maestros/alojamiento.php"
REVENUE = "/v1/ventas/revenue.php"
RESERVATIONS = "/v1/reservas/listado.php"
CHECK_TEXT = {
    "en": {
        "no_account": "Enter the FNS account (user and password): the server's .env has none.",
        "refused": lambda why: f"FNS refused the account for this hotel ({why}). Check the user, the password and "
                               "the alojamiento ID.",
        "no_answer": lambda kind: f"FNS didn't answer ({kind}). Try again in a few minutes.",
        "room_types": "Room types", "revenue": "Revenue", "reservations": "Reservations",
        "room_types_ok": lambda n: f"{n} room types",
        "no_room_types": "none for this alojamiento ID: check the ID",
        "answered": "answered",
        "needs_central": "need the central ID: enter it to import reservations",
        "all_ok": "The account works for this hotel.",
        "some_failed": "The account works, but not for everything: the parts marked ✕ won't be imported until "
                       "that is fixed (in FNS, or here).",
    },
    "es": {
        "no_account": "Escribe la cuenta de FNS (usuario y contraseña): el .env del servidor no tiene una.",
        "refused": lambda why: f"FNS rechazó la cuenta para este hotel ({why}). Revisa el usuario, la contraseña y "
                               "el ID de alojamiento.",
        "no_answer": lambda kind: f"FNS no respondió ({kind}). Inténtalo de nuevo en unos minutos.",
        "room_types": "Tipos de habitación", "revenue": "Ingresos", "reservations": "Reservas",
        "room_types_ok": lambda n: f"{n} tipos de habitación",
        "no_room_types": "ninguno para este ID de alojamiento: revisa el ID",
        "answered": "respondió",
        "needs_central": "necesitan el ID de central: escríbelo para importar las reservas",
        "all_ok": "La cuenta funciona para este hotel.",
        "some_failed": "La cuenta funciona, pero no para todo: lo marcado con ✕ no se importará hasta corregirlo "
                       "(en FNS o aquí).",
    },
}
# fns_sync.sync.HISTORY_STEPS: each loads the history once; a hotel is ready when all have.
HISTORY_STEPS = ("revenue", "production_cc", "sales_reservations", "reservations", "pos", "accounting", "exchange",
                 "production")
FIELDS = ("alojamiento_id", "central_id", "pms_id", "code", "name", "city", "country", "timezone", "moneda_id",
          "currency", "sync_time", "backfill_days", "enabled")
COLUMNS = ", ".join(f"f.{c}" for c in (*FIELDS, "id", "fns_user", "run_requested_at", "hotel_id", "created_at"))
UNIQUE = {"fns_hotels_alojamiento_id_key": "alojamiento_id", "fns_hotels_code_key": "code"}
LOG_LEVELS = ("error", "warning", "info")
# A hotel waiting this long while nothing imports: the fns-sync service is probably not running.
SERVICE_SILENT = timedelta(minutes=3)


def _fernet(key: str) -> Fernet:
    """As fns_sync/fns_sync/secret.py, which decrypts the passwords for the imports."""
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def encrypt(value: str, key: str) -> str:
    if not key:
        raise UserError("Set FNS_SECRET_KEY in the server's .env to save an FNS password per hotel, or leave the "
                        "account empty to use the one in .env.")
    return "fernet:" + _fernet(key).encrypt(value.encode()).decode()


def decrypt(stored: str, key: str) -> str | None:
    try:
        return _fernet(key).decrypt(stored.removeprefix("fernet:").encode()).decode()
    except InvalidToken:
        return None


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise UserError(f"{name!r} is not a time zone name like Europe/Madrid or America/Bogota.") from None


def _summary(run: dict | None) -> dict | None:
    if run is None:
        return None
    calls = run.pop("calls") or []
    failed = [c for c in calls if not c.get("ok") and not c.get("optional")]
    return {**run, "calls": len(calls), "rows": sum(c.get("rows", 0) for c in calls),
            "errors": [f"{c.get('method')} {c.get('window', '')}".strip() + f": {c.get('error')}" for c in failed[:8]],
            "failed_calls": len(failed)}


class FnsHotels:
    def __init__(self, dsn: str, secret_key: str = "", user: str = "", password: str = "",
                 base_url: str = FNS_URL, transport: httpx2.AsyncBaseTransport | None = None):
        self.dsn, self.secret_key = dsn, secret_key
        self.user, self.password = user, password
        self.base_url, self.transport = base_url.rstrip("/"), transport

    async def _connect(self) -> psycopg.AsyncConnection:
        return await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row, autocommit=True)

    async def _ready(self, conn) -> None:
        if not (await (await conn.execute("SELECT to_regclass('pms.fns_hotels') AS t")).fetchone())["t"]:
            raise UserError("The FNS import tables aren't there yet: start the fns-sync service once "
                            "(COMPOSE_PROFILES=fns in .env, then docker compose up -d).", 409)

    # --- reading -------------------------------------------------------------------------------------

    async def listing(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now().astimezone()
        async with await self._connect() as conn:
            await self._ready(conn)
            rows = await (await conn.execute(
                f"SELECT {COLUMNS}, f.fns_password IS NOT NULL AS has_password, h.currency AS hotel_currency, "
                "h.total_rooms FROM pms.fns_hotels f LEFT JOIN pms.hotels h ON h.id = f.hotel_id ORDER BY f.id")).fetchall()
            running_any = False
            for row in rows:
                await self._status(conn, row, now)
                running_any = running_any or row["state"] == "running"
            for row in rows:
                waiting_since = row.pop("_waiting_since")
                row["service_silent"] = (row["state"] == "queued" and not running_any and waiting_since is not None
                                         and now - waiting_since > SERVICE_SILENT)
        return {"hotels": rows, "default_account": bool(self.user and self.password),
                "can_save_passwords": bool(self.secret_key), "history_steps": len(HISTORY_STEPS)}

    async def _status(self, conn, row: dict, now: datetime) -> None:
        """Adds the hotel's state (running, queued, paused, scheduled), its live progress, its last
        finished import and when the next one starts."""
        hotel_id = row["hotel_id"]
        runs = await (await conn.execute(
            "SELECT id, started_at, finished_at, status, backfill, progress, calls FROM pms.fns_sync_runs "
            "WHERE hotel_id = %s ORDER BY id DESC LIMIT 2", (hotel_id,))).fetchall() if hotel_id else []
        steps = await (await conn.execute("SELECT step, history_from FROM pms.fns_sync_steps WHERE hotel_id = %s",
                                          (hotel_id,))).fetchall() if hotel_id else []
        last_ok = (await (await conn.execute(
            "SELECT max(started_at) AS t FROM pms.fns_sync_runs WHERE hotel_id = %s AND status IN ('ok', 'partial')",
            (hotel_id,))).fetchone())["t"] if hotel_id else None
        active = runs[0] if runs and runs[0]["status"] == "running" else None
        finished = next((r for r in runs if r["status"] != "running"), None)
        loaded = {s["step"] for s in steps}
        row["history"] = {"loaded": len(loaded & set(HISTORY_STEPS)), "total": len(HISTORY_STEPS),
                          "from": min((s["history_from"] for s in steps), default=None)}
        row["current"] = None
        if active:
            row["current"] = {"id": active["id"], "started_at": active["started_at"], "backfill": active["backfill"],
                              "progress": active["progress"] or {}}
        row["last"] = _summary(dict(finished)) if finished else None
        if row["last"]:
            row["last"].pop("progress", None)
        tz = zone(row["timezone"])
        local = now.astimezone(tz)
        slot = datetime.combine(local.date(), row["sync_time"], tzinfo=tz)
        if slot > now:
            slot -= timedelta(days=1)
        requested = row["run_requested_at"] and (not runs or row["run_requested_at"] > runs[0]["started_at"])
        pending = len(loaded & set(HISTORY_STEPS)) < len(HISTORY_STEPS)
        row["_waiting_since"] = None
        if active:
            row["state"] = "running"
        elif not row["enabled"]:
            row["state"] = "paused"
        elif requested or not runs:
            row["state"] = "queued"
            row["_waiting_since"] = row["run_requested_at"] if requested else row["created_at"]
        else:
            row["state"] = "scheduled"
        if not row["enabled"]:
            row["next_at"] = None
        elif pending or requested or not runs or last_ok is None or last_ok < slot:
            row["next_at"] = now  # as soon as the service is free (after FNS_RETRY_MINUTES if it just failed)
        else:
            row["next_at"] = slot + timedelta(days=1)
        row["sync_time"] = row["sync_time"].strftime("%H:%M")

    async def runs(self, fns_hotel_id: int, limit: int = 20) -> list[dict[str, Any]]:
        async with await self._connect() as conn:
            await self._ready(conn)
            rows = await (await conn.execute(
                "SELECT r.id, r.started_at, r.finished_at, r.status, r.backfill, r.calls FROM pms.fns_sync_runs r "
                "JOIN pms.fns_hotels f ON f.hotel_id = r.hotel_id WHERE f.id = %s ORDER BY r.id DESC LIMIT %s",
                (fns_hotel_id, limit))).fetchall()
        return [_summary(dict(r)) for r in rows]

    async def log(self, since: datetime | None = None, until: datetime | None = None, hotel_id: int | None = None,
                  levels: list[str] | None = None, search: str | None = None, before_id: int | None = None,
                  limit: int = 100) -> dict[str, Any]:
        """The import log, newest first, filtered; with the number of lines of each level that match
        (before paging), and the id to ask for the next page with (before_id)."""
        where, params = ["true"], []
        if since:
            where.append("l.at >= %s")
            params.append(since)
        if until:
            where.append("l.at < %s")
            params.append(until)
        if hotel_id:
            where.append("l.hotel_id = %s")
            params.append(hotel_id)
        if search:
            where.append("(l.message ILIKE %s OR l.command ILIKE %s)")
            params += [f"%{search}%"] * 2
        base = " AND ".join(where)
        chosen = [lv for lv in (levels or []) if lv in LOG_LEVELS] or list(LOG_LEVELS)
        async with await self._connect() as conn:
            await self._ready(conn)
            counts = {r["level"]: r["n"] for r in await (await conn.execute(
                f"SELECT l.level, count(*) AS n FROM pms.fns_sync_log l WHERE {base} GROUP BY 1", params)).fetchall()}
            rows = await (await conn.execute(
                f"SELECT l.id, l.at, l.level, l.message, l.hotel_id, h.code, l.run_id, l.command IS NOT NULL AS has_command, "
                f"l.output IS NOT NULL AS has_output FROM pms.fns_sync_log l LEFT JOIN pms.hotels h ON h.id = l.hotel_id "
                f"WHERE {base} AND l.level = ANY(%s){' AND l.id < %s' if before_id else ''} ORDER BY l.id DESC LIMIT %s",
                [*params, chosen, *([before_id] if before_id else []), limit + 1])).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        return {"entries": rows, "counts": {lv: counts.get(lv, 0) for lv in LOG_LEVELS},
                "next_before_id": rows[-1]["id"] if more else None}

    async def log_entry(self, entry_id: int) -> dict[str, Any]:
        """One line with its request (curl) and the API's answer."""
        async with await self._connect() as conn:
            await self._ready(conn)
            row = await (await conn.execute(
                "SELECT l.id, l.at, l.level, l.message, l.hotel_id, h.code, l.run_id, l.command, l.output "
                "FROM pms.fns_sync_log l LEFT JOIN pms.hotels h ON h.id = l.hotel_id WHERE l.id = %s",
                (entry_id,))).fetchone()
        if row is None:
            raise UserError("Log line not found (lines older than FNS_LOG_DAYS are deleted).", 404)
        return row

    # --- changes ---------------------------------------------------------------------------------------

    def _values(self, data: dict[str, Any]) -> dict[str, Any]:
        values = {k: v for k, v in data.items() if k in FIELDS}
        for k in ("code", "currency"):
            if isinstance(values.get(k), str):
                values[k] = values[k].strip().upper() or None
        for k in ("name", "city", "country", "timezone"):
            if isinstance(values.get(k), str):
                values[k] = values[k].strip()
        if values.get("timezone"):
            zone(values["timezone"])
        if "fns_user" in data:
            user = (data.get("fns_user") or "").strip()
            values["fns_user"] = user or None
            if not user:
                values["fns_password"] = None
            elif data.get("fns_password"):
                values["fns_password"] = encrypt(data["fns_password"], self.secret_key)
        elif data.get("fns_password"):
            values["fns_password"] = encrypt(data["fns_password"], self.secret_key)
        return values

    async def _code_free(self, conn, code: str, alojamiento_id: int | None, fns_hotel_id: int | None) -> None:
        """A code another hotel (sample or imported) already uses would clash in the reports."""
        row = await (await conn.execute(
            "SELECT h.id FROM pms.hotels h WHERE h.code = %s AND h.alojamiento_id IS DISTINCT FROM %s "
            "AND h.id IS DISTINCT FROM (SELECT hotel_id FROM pms.fns_hotels WHERE id = %s)",
            (code, alojamiento_id, fns_hotel_id))).fetchone()
        if row:
            raise UserError(f"Another hotel already uses the code {code}; choose a different code.")

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        values = self._values(data)
        if values.get("fns_user") and not values.get("fns_password"):
            raise UserError("Enter the FNS password of this account.")
        async with await self._connect() as conn:
            await self._ready(conn)
            await self._code_free(conn, values["code"], values["alojamiento_id"], None)
            async with self._errors():
                cols = ", ".join(values)
                row = await (await conn.execute(
                    f"INSERT INTO pms.fns_hotels ({cols}) VALUES ({', '.join(['%s'] * len(values))}) RETURNING id",
                    tuple(values.values()))).fetchone()
        return await self.get(row["id"])

    async def update(self, fns_hotel_id: int, data: dict[str, Any]) -> dict[str, Any]:
        values = self._values(data)
        if values.get("fns_user"):
            async with await self._connect() as conn:
                await self._ready(conn)
                old = await (await conn.execute("SELECT fns_user, fns_password FROM pms.fns_hotels WHERE id = %s",
                                                (fns_hotel_id,))).fetchone()
            if not values.get("fns_password") and (old is None or old["fns_user"] != values["fns_user"]
                                                   or not old["fns_password"]):
                raise UserError("Enter the FNS password of this account.")
        async with await self._connect() as conn:
            await self._ready(conn)
            if values.get("code"):
                await self._code_free(conn, values["code"], values.get("alojamiento_id"), fns_hotel_id)
            if values:
                async with self._errors():
                    sets = ", ".join(f"{k} = %s" for k in values)
                    done = await conn.execute(f"UPDATE pms.fns_hotels SET {sets}, updated_at = now() WHERE id = %s",
                                              (*values.values(), fns_hotel_id))
                    if done.rowcount == 0:
                        raise UserError("Hotel not found.", 404)
        return await self.get(fns_hotel_id)

    async def request_run(self, fns_hotel_id: int) -> dict[str, Any]:
        async with await self._connect() as conn:
            await self._ready(conn)
            done = await conn.execute("UPDATE pms.fns_hotels SET run_requested_at = now() WHERE id = %s",
                                      (fns_hotel_id,))
            if done.rowcount == 0:
                raise UserError("Hotel not found.", 404)
        return await self.get(fns_hotel_id)

    async def get(self, fns_hotel_id: int) -> dict[str, Any]:
        hotel = next((h for h in (await self.listing())["hotels"] if h["id"] == fns_hotel_id), None)
        if hotel is None:
            raise UserError("Hotel not found.", 404)
        return hotel

    def _errors(self):
        return _Errors()

    # --- checking an account -----------------------------------------------------------------------

    async def verify(self, data: dict[str, Any], fns_hotel_id: int | None = None,
                     language: str = "en") -> dict[str, Any]:
        """Tries the account given (else the hotel's saved one, else the one in .env) with three
        small requests: the hotel's room types, yesterday's and today's revenue, and their
        reservations (which need the central ID). Each is reported on its own, so a mistyped ID or
        password, or a method the account may not use, shows before the import starts."""
        say = CHECK_TEXT.get(language, CHECK_TEXT["en"])
        user, password = (data.get("fns_user") or "").strip(), data.get("fns_password") or ""
        if user and not password and fns_hotel_id:
            password = await self._saved_password(fns_hotel_id, user)
        if not user:
            user, password = self.user, self.password
        if not user or not password:
            raise UserError(say["no_account"])
        aloj, central = data["alojamiento_id"], data.get("central_id")
        today = datetime.now().date()
        days = {"start_date": (today - timedelta(days=1)).isoformat(), "end_date": today.isoformat()}
        extra = {"pms_id": data["pms_id"]} if data.get("pms_id") else {}
        # Some accounts refuse central_id "" or 0 as wrong credentials: left out when there is none.
        blank = {"central_id": ""} if central else {}
        checks: list[dict[str, Any]] = []
        try:
            async with httpx2.AsyncClient(base_url=self.base_url, auth=(user, password), transport=self.transport,
                                         timeout=httpx2.Timeout(60, connect=15),
                                         headers={"Accept": "application/json"}) as http:
                async def ask(path: str, filt: dict) -> tuple[bool, Any, str]:
                    response = await http.post(path, json={"filter": {**filt, **extra}})
                    try:
                        payload = response.json()
                    except ValueError:
                        payload = None
                    message = payload.get("mensaje") or payload.get("error") if isinstance(payload, dict) else None
                    ok = response.status_code < 400 and payload is not None and not (
                        isinstance(payload, dict) and payload and set(payload) <= {"mensaje", "error", "@attributes"})
                    return ok, payload, f"HTTP {response.status_code}" + (f": {message}" if message else "")

                ok, payload, why = await ask(MASTER, {**blank, "alojamiento_id": aloj, "listado": "th"})
                if not ok and blank and why.startswith(("HTTP 401", "HTTP 403")):
                    blank = {}  # some accounts refuse central_id "": as the import does, try without it
                    ok, payload, why = await ask(MASTER, {"alojamiento_id": aloj, "listado": "th"})
                if not ok:
                    return {"ok": False, "message": say["refused"](why), "checks": []}
                lists = {str(k).strip(): v for k, v in payload.items()} if isinstance(payload, dict) else {}
                room_types = len(lists["th"]) if isinstance(lists.get("th"), dict) else 0
                checks.append({"name": say["room_types"], "ok": room_types > 0,
                               "message": say["room_types_ok"](room_types) if room_types else say["no_room_types"]})
                ok, _, why = await ask(REVENUE, {**blank, "alojamiento_id": aloj, **days, "moneda_id": 1, "impuesto": 0})
                checks.append({"name": say["revenue"], "ok": ok, "message": say["answered"] if ok else why})
                if central:
                    ok, _, why = await ask(RESERVATIONS, {"central_id": central, "alojamiento_id": aloj, **days,
                                                          "estado": "Todas"})
                    checks.append({"name": say["reservations"], "ok": ok, "message": say["answered"] if ok else why})
                else:
                    checks.append({"name": say["reservations"], "ok": False, "message": say["needs_central"]})
        except httpx2.HTTPError as e:
            if not checks:
                return {"ok": False, "message": say["no_answer"](e.__class__.__name__), "checks": []}
            checks.append({"name": "FNS", "ok": False, "message": say["no_answer"](e.__class__.__name__)})
        all_ok = all(c["ok"] for c in checks)
        return {"ok": True, "room_types": room_types, "checks": checks,
                "message": say["all_ok"] if all_ok else say["some_failed"]}

    async def _saved_password(self, fns_hotel_id: int, user: str) -> str:
        async with await self._connect() as conn:
            row = await (await conn.execute("SELECT fns_user, fns_password FROM pms.fns_hotels WHERE id = %s",
                                            (fns_hotel_id,))).fetchone()
        if not row or row["fns_user"] != user or not row["fns_password"] or not self.secret_key:
            return ""
        return decrypt(row["fns_password"], self.secret_key) or ""


class _Errors:
    """Database refusals -> a message for the administrator."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, kind, error, tb):
        if isinstance(error, psycopg.errors.UniqueViolation):
            field = UNIQUE.get(getattr(error.diag, "constraint_name", "") or "", "")
            raise UserError({"alojamiento_id": "This alojamiento ID is already being imported.",
                             "code": "Another hotel already uses this code."}.get(field, "Already exists.")) from None
        if isinstance(error, psycopg.errors.CheckViolation):
            raise UserError("Some fields aren't valid (code: 2-12 capital letters or digits; currency: 3 letters).") \
                from None
        return False
