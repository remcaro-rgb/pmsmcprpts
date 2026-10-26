"""User accounts and their hotels (the user directory, db/init/05_users.sh), managed by
administrators in the website. Which hotels' data a user can see is enforced by the database on
every query the model runs (row-level security); this module only stores the accounts."""

import base64
import hashlib
import hmac
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

MIN_PASSWORD = 10
# scrypt cost: ~50 ms and 16 MiB per check.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(key)}"


def check_password(password: str, stored: str | None) -> bool:
    """Constant-time check. With no stored hash it still does the work, so the time taken doesn't
    reveal whether an account exists."""
    try:
        _, n, r, p, salt, key = (stored or "").split("$")
        salt_b, key_b = base64.b64decode(salt), base64.b64decode(key)
        n, r, p = int(n), int(r), int(p)
    except ValueError:
        salt_b, key_b, n, r, p = b"\0" * 16, b"", SCRYPT_N, SCRYPT_R, SCRYPT_P
    actual = hashlib.scrypt(password.encode(), salt=salt_b, n=n, r=r, p=p, dklen=32)
    return bool(key_b) and hmac.compare_digest(actual, key_b)


class UserError(ValueError):
    """A request the directory refuses; the message is shown to the administrator."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class User:
    id: int
    uniqueid: str | None
    name: str
    email: str
    phone: str | None
    notes: str | None
    is_admin: bool
    active: bool
    has_password: bool
    hotel_ids: list[int]
    created_at: datetime

    def public(self) -> dict[str, Any]:
        return {**asdict(self), "created_at": self.created_at.isoformat()}


USER_SQL = """
SELECT u.id, u.uniqueid, u.name, u.email, u.phone, u.notes, u.is_admin, u.active,
       u.password_hash IS NOT NULL AS has_password, u.created_at,
       coalesce(array_agg(uh.hotel_id ORDER BY uh.hotel_id) FILTER (WHERE uh.hotel_id IS NOT NULL), '{}')
         AS hotel_ids
FROM app.users u LEFT JOIN app.user_hotels uh ON uh.user_id = u.id
"""

# Unique constraints -> the field the administrator has to change.
UNIQUE_FIELDS = {"users_email_key": "email", "users_uniqueid_key": "uniqueid",
                 "hotels_alojamiento_id_key": "alojamiento_id", "hotels_pms_id_key": "pms_id"}
USER_FIELDS = ("uniqueid", "name", "email", "phone", "notes", "is_admin", "active")


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class UserDirectory:
    def __init__(self, dsn: str):
        self.dsn = dsn

    async def _connect(self) -> psycopg.AsyncConnection:
        return await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row)

    @staticmethod
    def _user(row: dict) -> User:
        return User(**row)

    async def _one(self, conn, where: str, params: tuple) -> User | None:
        row = await (await conn.execute(f"{USER_SQL} WHERE {where} GROUP BY u.id", params)).fetchone()
        return self._user(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        async with await self._connect() as conn:
            return await self._one(conn, "u.email = %s", (email.strip().lower(),))

    async def get(self, user_id: int) -> User | None:
        async with await self._connect() as conn:
            return await self._one(conn, "u.id = %s", (user_id,))

    async def verify(self, login: str, password: str) -> User | None:
        """The active user with this email or unique ID and password, else None."""
        login = login.strip()
        async with await self._connect() as conn:
            row = await (await conn.execute(
                "SELECT id, password_hash FROM app.users WHERE active AND (email = lower(%s) OR uniqueid = %s)",
                (login, login))).fetchone()
            ok = check_password(password, row["password_hash"] if row else None)
            return await self._one(conn, "u.id = %s", (row["id"],)) if row and ok else None

    async def list_users(self) -> list[User]:
        async with await self._connect() as conn:
            rows = await (await conn.execute(f"{USER_SQL} GROUP BY u.id ORDER BY lower(u.name), u.id")).fetchall()
            return [self._user(r) for r in rows]

    async def create(self, data: dict[str, Any]) -> User:
        data = {k: _clean(v) for k, v in data.items()}
        password = data.pop("password", None)
        hotel_ids = data.pop("hotel_ids", None) or []
        if not password:
            raise UserError("Set a password.")
        values = {k: data.get(k) for k in USER_FIELDS if data.get(k) is not None}
        values["email"] = (values.get("email") or "").lower()
        values["password_hash"] = hash_password(password)
        async with await self._connect() as conn:
            async with self._errors(), conn.transaction():
                cols = ", ".join(values)
                row = await (await conn.execute(
                    f"INSERT INTO app.users ({cols}) VALUES ({', '.join(['%s'] * len(values))}) RETURNING id",
                    tuple(values.values()))).fetchone()
                await self._set_hotels(conn, row["id"], hotel_ids)
            return await self._one(conn, "u.id = %s", (row["id"],))

    async def update(self, user_id: int, data: dict[str, Any], acting_admin: str) -> User:
        """Change only the fields given. Keeps at least one active administrator."""
        data = {k: _clean(v) for k, v in data.items()}
        password = data.pop("password", None)
        hotel_ids = data.pop("hotel_ids", None)
        values = {k: data[k] for k in USER_FIELDS if k in data}
        if "email" in values:
            if not values["email"]:
                raise UserError("Email can't be empty.")
            values["email"] = values["email"].lower()
        if "name" in values and not values["name"]:
            raise UserError("Name can't be empty.")
        for flag in ("is_admin", "active"):
            if flag in values and values[flag] is None:
                values.pop(flag)
        if password:
            values["password_hash"] = hash_password(password)
        async with await self._connect() as conn:
            async with self._errors(), conn.transaction():
                current = await self._one(conn, "u.id = %s", (user_id,))
                if current is None:
                    raise UserError("User not found.", 404)
                demoting = current.is_admin and current.active and (
                    values.get("is_admin") is False or values.get("active") is False)
                if demoting:
                    if current.email == acting_admin:
                        raise UserError("You can't remove your own administrator access or deactivate yourself.")
                    await self._keep_an_admin(conn, user_id)
                if values:
                    sets = ", ".join(f"{k} = %s" for k in values)
                    await conn.execute(f"UPDATE app.users SET {sets}, updated_at = now() WHERE id = %s",
                                       (*values.values(), user_id))
                if hotel_ids is not None:
                    await self._set_hotels(conn, user_id, hotel_ids)
            return await self._one(conn, "u.id = %s", (user_id,))

    async def delete(self, user_id: int, acting_admin: str) -> None:
        async with await self._connect() as conn:
            async with conn.transaction():
                current = await self._one(conn, "u.id = %s", (user_id,))
                if current is None:
                    raise UserError("User not found.", 404)
                if current.email == acting_admin:
                    raise UserError("You can't delete your own account.")
                if current.is_admin and current.active:
                    await self._keep_an_admin(conn, user_id)
                await conn.execute("DELETE FROM app.users WHERE id = %s", (user_id,))

    async def list_hotels(self) -> list[dict[str, Any]]:
        async with await self._connect() as conn:
            return await (await conn.execute(
                "SELECT id, code, name, city, country, alojamiento_id, pms_id FROM pms.hotels ORDER BY id")).fetchall()

    async def update_hotel(self, hotel_id: int, values: dict[str, int]) -> dict[str, Any]:
        values = {k: v for k, v in values.items() if k in ("alojamiento_id", "pms_id") and v is not None}
        async with await self._connect() as conn:
            async with self._errors(), conn.transaction():
                if values:
                    sets = ", ".join(f"{k} = %s" for k in values)
                    await conn.execute(f"UPDATE pms.hotels SET {sets} WHERE id = %s", (*values.values(), hotel_id))
                row = await (await conn.execute(
                    "SELECT id, code, name, city, country, alojamiento_id, pms_id FROM pms.hotels WHERE id = %s",
                    (hotel_id,))).fetchone()
                if row is None:
                    raise UserError("Hotel not found.", 404)
                return row

    async def upsert_admin(self, email: str, name: str, password: str) -> User:
        """For the command line: create the administrator, or reset an existing account to one."""
        email = email.strip().lower()
        async with await self._connect() as conn:
            async with self._errors(), conn.transaction():
                await conn.execute(
                    "INSERT INTO app.users (name, email, password_hash, is_admin, active) VALUES (%s, %s, %s, true, true) "
                    "ON CONFLICT (email) DO UPDATE SET name = excluded.name, password_hash = excluded.password_hash, "
                    "is_admin = true, active = true, updated_at = now()",
                    (name.strip(), email, hash_password(password)))
            return await self._one(conn, "u.email = %s", (email,))

    @staticmethod
    async def _set_hotels(conn, user_id: int, hotel_ids: list[int]) -> None:
        ids = sorted({int(h) for h in hotel_ids})
        known = await (await conn.execute("SELECT id FROM pms.hotels WHERE id = ANY(%s)", (ids,))).fetchall()
        if len(known) != len(ids):
            raise UserError("Unknown hotel.")
        await conn.execute("DELETE FROM app.user_hotels WHERE user_id = %s", (user_id,))
        for hotel_id in ids:
            await conn.execute("INSERT INTO app.user_hotels (user_id, hotel_id) VALUES (%s, %s)", (user_id, hotel_id))

    @staticmethod
    async def _keep_an_admin(conn, user_id: int) -> None:
        others = await (await conn.execute(
            "SELECT count(*) AS n FROM app.users WHERE is_admin AND active AND id <> %s", (user_id,))).fetchone()
        if not others["n"]:
            raise UserError("There must be at least one active administrator.")

    @staticmethod
    def _errors():
        return _DatabaseErrors()


class _DatabaseErrors:
    """Turns constraint violations into messages for the administrator."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if isinstance(exc, psycopg.errors.UniqueViolation):
            field = UNIQUE_FIELDS.get(exc.diag.constraint_name or "", "value")
            raise UserError(f"That {field} is already in use.", 409) from exc
        if isinstance(exc, psycopg.errors.CheckViolation):
            raise UserError("A value is out of range (IDs must be whole numbers above 0; emails need an @).") from exc
        return False
