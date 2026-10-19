"""Which hotels each user may see. The database enforces it (row-level security, see
db/init/04_hotel_access.sql); this module decides the value of pms.allowed_hotels per user.

PMS_HOTEL_ACCESS lists rules separated by ";" or new lines, each `who = hotels`:

    ann@hotel.example = LIS, OPO
    @lisbon-team.example = LIS
    * = *

`who` is an email address, an @domain, or * for everyone else; `hotels` is hotel codes or * for
all. The first matching rule wins in that order: email, then domain, then *. Unset, everyone
sees every hotel; set, anyone matching no rule sees none.

With PMS_USER_DIRECTORY=true these rules are replaced by the user directory (db/init/05_users.sh).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

ALL = "*"
CODE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


@dataclass(frozen=True)
class Scope:
    """What the database is told about a query's caller (see Database.query)."""
    user: str  # user-directory email ("" outside directory mode)
    hotels: str  # "*", "LIS,OPO" or "" for none


@dataclass(frozen=True)
class HotelAccess:
    rules: dict[str, str] = field(default_factory=dict)  # who -> "*" or "LIS,OPO"
    configured: bool = False
    # PMS_USER_DIRECTORY=true: the user directory (app.users / app.user_hotels, managed in the
    # website's admin page) decides, in the database; callers who aren't active users see nothing.
    directory: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "HotelAccess":
        access = cls.parse(env.get("PMS_HOTEL_ACCESS", ""))
        if env.get("PMS_USER_DIRECTORY", "").lower() in ("1", "true", "on", "yes"):
            if access.configured:
                raise ValueError("Use either PMS_USER_DIRECTORY or PMS_HOTEL_ACCESS, not both.")
            return cls(directory=True)
        return access

    def scope(self, user: str) -> Scope:
        if self.directory:
            return Scope(user.strip().lower(), "")
        return Scope("", self.hotels_for(user))

    @classmethod
    def parse(cls, spec: str) -> "HotelAccess":
        rules: dict[str, str] = {}
        for raw in re.split(r"[;\n]", spec):
            if not raw.strip():
                continue
            who, sep, hotels = raw.partition("=")
            who, hotels = who.strip().lower(), hotels.strip()
            if not sep or not who or not hotels:
                raise ValueError(f"PMS_HOTEL_ACCESS: expected `who = hotels`, got {raw.strip()!r}.")
            if who != ALL and "@" not in who:
                raise ValueError(f"PMS_HOTEL_ACCESS: {who!r} is not an email address, @domain or *.")
            if who in rules:
                raise ValueError(f"PMS_HOTEL_ACCESS: {who!r} is listed twice.")
            if hotels != ALL:
                codes = [c.strip().upper() for c in hotels.split(",") if c.strip()]
                bad = [c for c in codes if not CODE.match(c)]
                if bad or not codes:
                    raise ValueError(f"PMS_HOTEL_ACCESS: invalid hotel codes for {who!r}: {hotels!r}.")
                hotels = ",".join(codes)
            rules[who] = hotels
        return cls(rules, configured=bool(rules))

    def hotels_for(self, user: str) -> str:
        """The pms.allowed_hotels value for `user`: "*", "LIS,OPO", or "" for none."""
        if not self.configured:
            return ALL
        user = user.lower()
        domain = "@" + user.rsplit("@", 1)[1] if "@" in user else None
        for key in (user, domain, ALL):
            if key and key in self.rules:
                return self.rules[key]
        return ""
