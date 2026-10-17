"""Seed the sample PMS database with deterministic synthetic data.

Simulates bookings day by day for a small hotel chain: seasonality, weekday/weekend
patterns, channel-specific lead times and cancellation rates, room-level inventory
(no double bookings), folios with ancillary spend, payments, housekeeping and reviews.

Usage:
    DATABASE_URL=postgresql://pms:pms@localhost:5432/pms python db/seed.py
    python db/seed.py --history-days 60 --future-days 30 --reset   # small dataset
"""

from __future__ import annotations

import argparse
import heapq
import math
import os
import random
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg
from faker import Faker

DEFAULT_BUSINESS_DATE = date(2026, 10, 17)

# Occupancy demand by weekday of arrival (Mon=0) and nightly rate by weekday of stay.
DOW_OCC = [0.92, 0.98, 1.0, 1.0, 1.08, 1.12, 0.85]
DOW_RATE = [0.95, 0.97, 0.98, 1.0, 1.08, 1.12, 0.94]

HOTELS = [
    dict(
        code="LIS", name="Tagus Riverside Hotel", city="Lisbon", country="PT", stars=4,
        tz="Europe/Lisbon", opened_on=date(2009, 5, 1), floors=8, rooms=220, base_occ=0.80,
        room_mix=[("STD", "Standard Double", 2, 0.45, 115), ("SUP", "Superior River View", 2, 0.30, 145),
                  ("DLX", "Deluxe King", 3, 0.18, 185), ("STE", "Junior Suite", 4, 0.07, 290)],
        season=[0.72, 0.76, 0.86, 0.96, 1.0, 1.05, 1.08, 1.08, 1.05, 0.98, 0.80, 0.84],
        countries={"PT": 22, "ES": 8, "GB": 14, "US": 14, "DE": 10, "FR": 10, "IT": 5, "NL": 5, "BR": 8, "IE": 4},
    ),
    dict(
        code="BCN", name="Eixample Grand Hotel", city="Barcelona", country="ES", stars=5,
        tz="Europe/Madrid", opened_on=date(2014, 3, 15), floors=9, rooms=180, base_occ=0.78,
        room_mix=[("STD", "Classic Room", 2, 0.40, 175), ("SUP", "Superior Balcony", 2, 0.30, 215),
                  ("DLX", "Deluxe Terrace", 3, 0.20, 275), ("STE", "Grand Suite", 4, 0.10, 460)],
        season=[0.70, 0.74, 0.85, 0.97, 1.02, 1.08, 1.12, 1.10, 1.06, 0.98, 0.78, 0.80],
        countries={"ES": 25, "GB": 15, "US": 15, "FR": 12, "DE": 10, "IT": 8, "NL": 5, "PT": 3, "BR": 3, "IE": 4},
    ),
    dict(
        code="OPO", name="Douro Plaza Hotel", city="Porto", country="PT", stars=4,
        tz="Europe/Lisbon", opened_on=date(2017, 6, 1), floors=7, rooms=200, base_occ=0.74,
        room_mix=[("STD", "Standard Twin/Double", 2, 0.50, 95), ("SUP", "Superior City View", 2, 0.28, 120),
                  ("DLX", "Deluxe Douro View", 3, 0.16, 160), ("STE", "Wine Suite", 4, 0.06, 240)],
        season=[0.68, 0.72, 0.84, 0.95, 1.02, 1.06, 1.10, 1.10, 1.06, 0.96, 0.76, 0.80],
        countries={"PT": 30, "ES": 12, "FR": 14, "GB": 10, "DE": 8, "US": 8, "BR": 10, "IT": 4, "NL": 2, "IE": 2},
    ),
]

FAKER_LOCALES = {"PT": "pt_PT", "ES": "es_ES", "GB": "en_GB", "US": "en_US", "DE": "de_DE",
                 "FR": "fr_FR", "IT": "it_IT", "NL": "nl_NL", "BR": "pt_BR", "IE": "en_IE"}

TAX = {"PT": {"room": 0.06, "fnb": 0.13, "other": 0.23},
       "ES": {"room": 0.10, "fnb": 0.10, "other": 0.21}}

CHANNEL_WEIGHTS = {"direct_web": 22, "phone": 5, "walk_in": 2, "ota": 40, "gds": 8, "corporate": 13, "wholesale": 10}
LEAD_MEAN_DAYS = {"direct_web": 45, "phone": 25, "walk_in": 0, "ota": 35, "gds": 14, "corporate": 10, "wholesale": 90}
CANCEL_P = {"direct_web": 0.12, "phone": 0.10, "walk_in": 0.0, "ota": 0.28, "gds": 0.15, "corporate": 0.12, "wholesale": 0.18}
NONREFUNDABLE_CANCEL_P = 0.03
NO_SHOW_P = 0.025
WARMUP_DAYS = 14  # simulate arrivals before data_start so the first days are not half empty
LEISURE_LOS = {1: 25, 2: 27, 3: 20, 4: 12, 5: 7, 6: 4, 7: 5}
BUSINESS_LOS = {1: 40, 2: 33, 3: 17, 4: 10}
BUSINESS_CHANNELS = {"corporate", "gds"}

# code, name, refundable, includes_breakfast, price_factor
RATE_PLANS = [
    ("BAR", "Best Available Rate", True, False, 1.00),
    ("BB", "Bed & Breakfast", True, True, 1.12),
    ("NRF", "Non-Refundable", False, False, 0.88),
    ("ADV14", "Advance Purchase 14 days", False, True, 0.85),
    ("CORP", "Corporate Negotiated", True, True, 1.00),
    ("WHL", "Wholesale Net", True, False, 0.78),
]

TRAVEL_AGENTS = [  # name, type, commission
    ("BookRoom", "ota", 0.17), ("TripNest", "ota", 0.15), ("StayFinder", "ota", 0.18),
    ("SunGate Travel", "wholesaler", 0.25), ("EuroBeds Wholesale", "wholesaler", 0.22),
    ("CorpTravel Partners", "tmc", 0.08), ("BizTrip Global", "tmc", 0.10),
]
OTA_WEIGHTS = [60, 30, 10]

INDUSTRIES = ["Technology", "Consulting", "Pharma", "Banking", "Automotive", "Energy", "Retail", "Telecom", "Logistics"]

STAFF_PLAN = [  # department, role, rooms per person (or fixed count if >= 1 and int)
    ("front_office", "Receptionist", 18), ("front_office", "Front Office Manager", 0),
    ("housekeeping", "Room Attendant", 9), ("housekeeping", "Housekeeping Supervisor", 55),
    ("fnb", "Waiter", 14), ("fnb", "Chef", 40), ("spa", "Therapist", 45),
    ("sales", "Sales Manager", 70), ("management", "General Manager", 0),
    ("management", "Revenue Manager", 0), ("maintenance", "Technician", 50),
]

REVIEW_COMMENTS = {
    "high": ["Fantastic stay, staff went above and beyond.", "Great location and spotless rooms.",
             "Loved the breakfast and the view.", "Would definitely come back!", "Perfect for a city break."],
    "mid": ["Good hotel overall, room a bit small.", "Nice stay but check-in took a while.",
            "Comfortable beds, average breakfast.", "Decent value for the price."],
    "low": ["Room was noisy and the AC did not work.", "Disappointing service at the front desk.",
            "Overpriced for what you get.", "Cleanliness was below expectations."],
}


@dataclass(slots=True)
class Reservation:
    id: int
    hotel: dict
    guest_id: int
    company_id: int | None
    travel_agent_id: int | None
    channel: str
    plan: tuple  # (id, code, refundable, includes_breakfast, factor)
    room_type_id: int
    room_id: int | None
    booked_at: datetime
    arrival: date
    departure: date
    adults: int
    children: int
    status: str
    cancelled_at: datetime | None
    rates: list[float] = field(default_factory=list)


class Seeder:
    def __init__(self, business_date: date, history_days: int, future_days: int, seed: int):
        self.bd = business_date
        self.start = business_date - timedelta(days=history_days)
        self.end_arrival = business_date + timedelta(days=future_days)
        self.rng = random.Random(seed)
        self.fakers = {}
        for i, (country, locale) in enumerate(sorted(FAKER_LOCALES.items())):
            f = Faker(locale)
            f.seed_instance(seed + i)
            self.fakers[country] = f
        self.rows: dict[str, list[tuple]] = {k: [] for k in (
            "hotels", "room_types", "rooms", "rate_plans", "companies", "travel_agents", "guests",
            "staff", "reservations", "reservation_nights", "folios", "folio_charges", "payments",
            "housekeeping_tasks", "reviews")}
        self.guests: list[list] = []  # [id, first, last, email, phone, country, created_at]
        self.company_guests: dict[int, list[int]] = {}
        self.reservations: list[Reservation] = []
        self.staff_by_hotel: dict[int, dict[str, list[int]]] = {}

    # ---------- helpers ----------

    def weighted(self, weights: dict):
        return self.rng.choices(list(weights), weights=list(weights.values()))[0]

    def poisson(self, lam: float) -> int:
        if lam < 30:
            limit, k, p = math.exp(-lam), 0, 1.0
            while True:
                p *= self.rng.random()
                if p <= limit:
                    return k
                k += 1
        return max(0, round(self.rng.gauss(lam, math.sqrt(lam))))

    def growth(self, d: date) -> float:
        return 1 + 0.04 * (d - self.start).days / 365

    @staticmethod
    def at(d: date, tz: ZoneInfo, hours: float) -> datetime:
        return datetime.combine(d, time(0), tzinfo=tz) + timedelta(hours=hours)

    # ---------- reference data ----------

    def build_reference(self):
        rng = self.rng
        rp_id = rt_id = room_id = staff_id = 0
        for hid, h in enumerate(HOTELS, start=1):
            h["id"] = hid
            h["zone"] = ZoneInfo(h["tz"])
            self.rows["hotels"].append((hid, h["code"], h["name"], h["city"], h["country"], h["stars"],
                                        h["rooms"], "EUR", h["tz"], h["opened_on"]))
            counts = [round(h["rooms"] * share) for _, _, _, share, _ in h["room_mix"]]
            counts[0] += h["rooms"] - sum(counts)
            h["room_types"], h["type_weights"] = [], []
            per_floor = math.ceil(h["rooms"] / h["floors"])
            n = 0
            for (code, name, max_occ, share, base), count in zip(h["room_mix"], counts):
                rt_id += 1
                h["room_types"].append({"id": rt_id, "code": code, "max_occ": max_occ, "base": base, "rooms": []})
                h["type_weights"].append(count)
                self.rows["room_types"].append((rt_id, hid, code, name, max_occ, base))
                for _ in range(count):
                    room_id += 1
                    floor, idx = divmod(n, per_floor)
                    n += 1
                    self.rows["rooms"].append((room_id, hid, rt_id, f"{floor + 1}{idx + 1:02d}", floor + 1, "in_service"))
                    h["room_types"][-1]["rooms"].append(room_id)
            h["plans"] = {}
            for code, name, refundable, breakfast, factor in RATE_PLANS:
                rp_id += 1
                h["plans"][code] = (rp_id, code, refundable, breakfast, factor)
                self.rows["rate_plans"].append((rp_id, hid, code, name, refundable, breakfast, factor))
            staff = {}
            fk = self.fakers[h["country"]]
            for dept, role, per in STAFF_PLAN:
                count = 1 if per == 0 else max(1, round(h["rooms"] / per))
                for _ in range(count):
                    staff_id += 1
                    tenure = max(0, (self.start - h["opened_on"]).days)
                    hired = h["opened_on"] + timedelta(days=rng.randint(0, tenure))
                    self.rows["staff"].append((staff_id, hid, fk.first_name(), fk.last_name(), dept, role, hired))
                    staff.setdefault(role, []).append(staff_id)
            self.staff_by_hotel[hid] = staff

        for cid in range(1, 61):
            country = self.weighted({"PT": 3, "ES": 3, "GB": 2, "US": 2, "DE": 2, "FR": 2, "NL": 1, "IT": 1})
            self.rows["companies"].append((cid, self.fakers[country].company(), rng.choice(INDUSTRIES), country,
                                           round(rng.uniform(0.05, 0.20), 3)))
            self.company_guests[cid] = []
        self.company_weights = [rng.paretovariate(1.2) for _ in range(60)]
        for i, (name, kind, comm) in enumerate(TRAVEL_AGENTS, start=1):
            self.rows["travel_agents"].append((i, name, kind, comm))

    # ---------- guests ----------

    def new_guest(self, hotel: dict, booked_at: datetime) -> int:
        country = self.weighted(hotel["countries"])
        fk = self.fakers[country]
        first, last = fk.first_name(), fk.last_name()
        local = unicodedata.normalize("NFKD", f"{first}.{last}").encode("ascii", "ignore").decode().lower()
        local = "".join(c for c in local if c.isalnum() or c == ".")
        gid = len(self.guests) + 1
        email = f"{local}{gid}@{self.rng.choice(['example.com', 'example.org', 'example.net'])}"
        self.guests.append([gid, first, last, email, fk.phone_number(), country, booked_at])
        return gid

    def pick_guest(self, hotel: dict, company_id: int | None, booked_at: datetime) -> int:
        rng = self.rng
        if company_id and self.company_guests[company_id] and rng.random() < 0.6:
            gid = rng.choice(self.company_guests[company_id])
        elif self.guests and rng.random() < 0.10:
            gid = rng.randint(1, len(self.guests))
        else:
            gid = self.new_guest(hotel, booked_at)
            if company_id:
                self.company_guests[company_id].append(gid)
        g = self.guests[gid - 1]
        g[6] = min(g[6], booked_at)
        return gid

    # ---------- booking simulation ----------

    def simulate(self):
        cutoff_by_hotel = {}
        avg_cancel = sum(CANCEL_P[c] * w for c, w in CHANNEL_WEIGHTS.items()) / sum(CHANNEL_WEIGHTS.values())
        for h in HOTELS:
            tz = h["zone"]
            cutoff = cutoff_by_hotel[h["id"]] = datetime.combine(self.bd, time(0), tzinfo=tz)
            busy = {rt["id"]: [] for rt in h["room_types"]}  # heap of (free_from, room_id)
            free = {rt["id"]: list(rt["rooms"]) for rt in h["room_types"]}
            d = self.start - timedelta(days=WARMUP_DAYS)
            while d <= self.end_arrival:
                for rt_id, heap in busy.items():
                    while heap and heap[0][0] <= d:
                        free[rt_id].append(heapq.heappop(heap)[1])
                occ = min(0.97, h["base_occ"] * h["season"][d.month - 1] * DOW_OCC[d.weekday()]
                          * (1 + 0.02 * (d - self.start).days / 365))
                lam = h["rooms"] * occ / 2.6 / (1 - avg_cancel) * 1.12
                for _ in range(self.poisson(lam)):
                    self.make_booking(h, d, cutoff, busy, free)
                d += timedelta(days=1)

    def make_booking(self, h, arrival, cutoff, busy, free):
        rng, tz = self.rng, h["zone"]
        weights = dict(CHANNEL_WEIGHTS)
        weights["corporate"] *= 2.0 if arrival.weekday() < 4 else 0.3
        channel = self.weighted(weights)
        lead = 0 if channel == "walk_in" else min(365, int(rng.expovariate(1 / LEAD_MEAN_DAYS[channel])))
        booked_on = arrival - timedelta(days=lead)
        booked_at = self.at(booked_on, tz, rng.uniform(14, 22) if lead == 0 else rng.uniform(7, 23.9))
        if booked_at >= cutoff:
            return  # not booked yet as of the business date
        los = self.weighted(BUSINESS_LOS if channel in BUSINESS_CHANNELS else LEISURE_LOS)
        departure = arrival + timedelta(days=los)
        rt = rng.choices(h["room_types"], weights=h["type_weights"])[0]

        plans = h["plans"]
        if channel == "corporate":
            plan = plans["CORP"]
        elif channel == "wholesale":
            plan = plans["WHL"]
        elif channel == "gds":
            plan = plans[rng.choice(["BAR", "CORP"])]
        elif channel == "walk_in":
            plan = plans["BAR"]
        else:
            options = {"BAR": 45, "BB": 25, "NRF": 20}
            if lead >= 14:
                options["ADV14"] = 15
            plan = plans[self.weighted(options)]

        company_id = travel_agent_id = None
        if channel == "corporate" or (channel == "gds" and rng.random() < 0.6):
            company_id = rng.choices(range(1, 61), weights=self.company_weights)[0]
        if channel == "ota":
            travel_agent_id = rng.choices([1, 2, 3], weights=OTA_WEIGHTS)[0]
        elif channel == "wholesale":
            travel_agent_id = rng.choice([4, 5])
        elif channel == "gds":
            travel_agent_id = rng.choice([6, 7])

        cancelled_at = None
        if rng.random() < (CANCEL_P[channel] if plan[2] else NONREFUNDABLE_CANCEL_P):
            window_end = self.at(arrival, tz, 23.9)  # last chance to cancel is the arrival day
            cancelled_at = booked_at + (window_end - booked_at) * rng.random()
            if cancelled_at >= cutoff:
                cancelled_at = None  # will cancel later; still on the books today

        room_id = None
        if cancelled_at is None:
            if not free[rt["id"]]:
                return  # room type sold out
            pool = free[rt["id"]]
            i = rng.randrange(len(pool))
            pool[i], pool[-1] = pool[-1], pool[i]
            room_id = pool.pop()
            heapq.heappush(busy[rt["id"]], (departure, room_id))

        if cancelled_at is not None:
            status = "cancelled"
        elif arrival >= self.bd:
            status = "confirmed"
        elif channel != "walk_in" and rng.random() < NO_SHOW_P:
            status = "no_show"
        elif departure < self.bd:
            status = "checked_out"
        else:
            status = "checked_in"

        if channel in BUSINESS_CHANNELS:
            adults, children = (1 if rng.random() < 0.9 else 2), 0
        else:
            adults = self.weighted({1: 20, 2: 65, 3: 10, 4: 5})
            children = self.weighted({0: 85, 1: 10, 2: 5})
        adults = min(adults, rt["max_occ"])
        children = min(children, rt["max_occ"] - adults)

        discount = self.rows["companies"][company_id - 1][4] if company_id else 0
        noise = rng.lognormvariate(0, 0.06)
        rates = []
        for i in range(los):
            s = arrival + timedelta(days=i)
            season = 1 + (h["season"][s.month - 1] - 1) * 1.6
            rates.append(round(rt["base"] * season * DOW_RATE[s.weekday()] * plan[4] * (1 - discount)
                               * self.growth(s) * noise, 2))

        rid = len(self.reservations) + 1
        guest_id = self.pick_guest(h, company_id, booked_at)
        self.reservations.append(Reservation(
            rid, h, guest_id, company_id, travel_agent_id, channel, plan, rt["id"], room_id, booked_at,
            arrival, departure, adults, children, status, cancelled_at, rates))

    # ---------- folios, housekeeping, reviews ----------

    def build_transactions(self):
        rng = self.rng
        folio_id = charge_id = payment_id = task_id = review_id = 0
        charges, payments, tasks, reviews = (self.rows[k] for k in
                                             ("folio_charges", "payments", "housekeeping_tasks", "reviews"))
        for r in self.reservations:
            h, tz = r.hotel, r.hotel["zone"]
            tax = TAX[h["country"]]
            self.rows["reservations"].append((
                r.id, f"{h['code']}-{r.id:06d}", h["id"], r.guest_id, r.company_id, r.travel_agent_id,
                r.channel, r.plan[0], r.room_type_id, r.room_id, r.booked_at, r.arrival, r.departure,
                r.adults, r.children, r.status, r.cancelled_at))
            for i, rate in enumerate(r.rates):
                self.rows["reservation_nights"].append((r.id, r.arrival + timedelta(days=i), rate))

            charged_nights = []
            if r.status in ("checked_in", "checked_out"):
                charged_nights = [i for i in range(len(r.rates)) if r.arrival + timedelta(days=i) < self.bd]
            elif r.status == "no_show" and not r.plan[2]:
                charged_nights = [0]
            if not charged_nights:
                continue

            folio_id += 1
            opened = self.at(r.arrival, tz, rng.uniform(14, 21))
            closed = self.at(r.departure, tz, rng.uniform(7, 11.9)) if r.status == "checked_out" else None
            if r.status == "no_show":
                closed = self.at(r.arrival + timedelta(days=1), tz, 3)
            self.rows["folios"].append((folio_id, r.id, opened, closed, "open" if closed is None else "closed"))

            total = 0.0
            stars5 = h["stars"] == 5
            price_level = h["room_mix"][0][4] / 115  # ancillary prices scale with the hotel's rates

            def post(d, hours, dept, desc, amount):
                nonlocal charge_id, total
                charge_id += 1
                amount = round(amount, 2)
                t = round(amount * tax["room" if dept == "room" else "fnb" if dept == "fnb" else "other"], 2)
                charges.append((charge_id, folio_id, self.at(d, tz, hours), dept, desc, amount, t))
                total += amount + t

            for i in charged_nights:
                s = r.arrival + timedelta(days=i)
                post(s, 23.5, "room", "Room charge", r.rates[i])
                if r.status == "no_show":
                    break
                if not r.plan[3] and rng.random() < 0.30:
                    post(s + timedelta(days=1), rng.uniform(7.5, 10.5), "fnb", "Breakfast",
                         16 * price_level * (r.adults + 0.5 * r.children))
                if rng.random() < 0.15:
                    post(s, rng.uniform(19, 22), "fnb", "Restaurant", rng.uniform(20, 50) * price_level * r.adults)
                if rng.random() < 0.25:
                    post(s, rng.uniform(18, 23.4), "fnb", "Bar", rng.uniform(6, 30) * price_level)
                if rng.random() < (0.10 if stars5 else 0.05):
                    post(s, rng.uniform(10, 19), "spa", "Spa treatment", rng.uniform(60, 160) * price_level)
                if rng.random() < 0.10:
                    post(s, 23.4, "minibar", "Minibar", rng.uniform(4, 25))
                if rng.random() < 0.08:
                    post(s, 23.45, "parking", "Parking", 18 * price_level)

            if closed is not None:
                payment_id += 1
                if r.channel == "wholesale" or (r.channel == "corporate" and rng.random() < 0.5):
                    method = "invoice"
                elif r.channel == "ota" and rng.random() < 0.5:
                    method = "virtual_card"
                else:
                    method = self.weighted({"credit_card": 75, "debit_card": 20, "cash": 5})
                payments.append((payment_id, folio_id, method, round(total, 2), closed))

            # Housekeeping: stayover cleans while in house, departure clean on checkout day.
            if r.status in ("checked_in", "checked_out"):
                staff = self.staff_by_hotel[h["id"]]
                for i in range(1, len(r.rates) + 1):
                    d = r.arrival + timedelta(days=i)
                    if d > self.bd:
                        break
                    kind = "departure_clean" if d == r.departure else "stayover"
                    if d == self.bd:
                        status, minutes = "pending", None
                    elif kind == "stayover" and rng.random() < 0.07:
                        status, minutes = "skipped", None
                    else:
                        status = "done"
                        minutes = rng.randint(25, 45) if kind == "departure_clean" else rng.randint(15, 25)
                    task_id += 1
                    tasks.append((task_id, h["id"], r.room_id, d, kind, status,
                                  rng.choice(staff["Room Attendant"]), minutes))
                    if kind == "departure_clean" and status == "done" and rng.random() < 0.3:
                        task_id += 1
                        tasks.append((task_id, h["id"], r.room_id, d, "inspection", "done",
                                      rng.choice(staff["Housekeeping Supervisor"]), rng.randint(5, 10)))

            if r.status == "checked_out" and rng.random() < 0.22:
                created = self.at(r.departure + timedelta(days=rng.randint(1, 14)), tz, rng.uniform(8, 23))
                if created.date() < self.bd:
                    score = min(10.0, max(1.0, round(rng.gauss(8.7 if stars5 else 8.3, 1.1), 1)))
                    band = "high" if score >= 8 else "mid" if score >= 6 else "low"
                    review_id += 1
                    source = self.weighted({"google": 35, "booking_com": 35, "tripadvisor": 15, "internal_survey": 15})
                    reviews.append((review_id, r.id, source, score, rng.choice(REVIEW_COMMENTS[band]), created))

        # Loyalty tier from completed stays across the chain.
        stays: dict[int, int] = {}
        for r in self.reservations:
            if r.status == "checked_out":
                stays[r.guest_id] = stays.get(r.guest_id, 0) + 1
        for g in self.guests:
            n = stays.get(g[0], 0)
            tier = "platinum" if n >= 6 else "gold" if n >= 4 else "silver" if n >= 2 else "none"
            self.rows["guests"].append((*g[:6], tier, g[6]))

    def run(self):
        self.build_reference()
        self.simulate()
        self.build_transactions()
        return self.rows


COLUMNS = {
    "hotels": "id, code, name, city, country, star_rating, total_rooms, currency, timezone, opened_on",
    "room_types": "id, hotel_id, code, name, max_occupancy, base_rate",
    "rooms": "id, hotel_id, room_type_id, number, floor, status",
    "rate_plans": "id, hotel_id, code, name, refundable, includes_breakfast, price_factor",
    "companies": "id, name, industry, country, negotiated_discount",
    "travel_agents": "id, name, agent_type, commission_pct",
    "guests": "id, first_name, last_name, email, phone, country, loyalty_tier, created_at",
    "staff": "id, hotel_id, first_name, last_name, department, role, hired_on",
    "reservations": "id, confirmation_no, hotel_id, guest_id, company_id, travel_agent_id, channel, "
                    "rate_plan_id, room_type_id, room_id, booked_at, arrival, departure, adults, children, "
                    "status, cancelled_at",
    "reservation_nights": "reservation_id, stay_date, rate",
    "folios": "id, reservation_id, opened_at, closed_at, status",
    "folio_charges": "id, folio_id, posted_at, department, description, amount, tax_amount",
    "payments": "id, folio_id, method, amount, paid_at",
    "housekeeping_tasks": "id, hotel_id, room_id, task_date, task_type, status, staff_id, minutes_spent",
    "reviews": "id, reservation_id, source, score, comment, created_at",
}
SERIAL_TABLES = [t for t in COLUMNS if t != "reservation_nights"]


def load(conn: psycopg.Connection, rows: dict, business_date: date, data_start: date):
    with conn.cursor() as cur:
        cur.execute("SET search_path TO pms")
        cur.execute("INSERT INTO system_settings (business_date, data_start) VALUES (%s, %s)",
                    (business_date, data_start))
        for table, cols in COLUMNS.items():
            with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as copy:
                for row in rows[table]:
                    copy.write_row(row)
            print(f"  {table:<20} {len(rows[table]):>9,} rows", file=sys.stderr)
        for table in SERIAL_TABLES:
            cur.execute(f"SELECT setval(pg_get_serial_sequence('pms.{table}', 'id'), "
                        f"coalesce((SELECT max(id) FROM {table}), 0) + 1, false)")
        cur.execute("ANALYZE")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dsn", default=os.environ.get("DATABASE_URL"), help="defaults to $DATABASE_URL")
    p.add_argument("--business-date", type=date.fromisoformat, default=DEFAULT_BUSINESS_DATE)
    p.add_argument("--history-days", type=int, default=730)
    p.add_argument("--future-days", type=int, default=180)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--reset", action="store_true", help="truncate existing data first")
    args = p.parse_args(argv)
    if not args.dsn:
        p.error("set --dsn or DATABASE_URL")

    with psycopg.connect(args.dsn) as conn:
        has_data = conn.execute("SELECT EXISTS (SELECT 1 FROM pms.hotels)").fetchone()[0]
        if has_data and not args.reset:
            print("pms already seeded; use --reset to reseed", file=sys.stderr)
            return
        if has_data:
            conn.execute("TRUNCATE " + ", ".join(f"pms.{t}" for t in [*COLUMNS, "system_settings"]) + " CASCADE")

        print(f"Generating data {args.business_date - timedelta(days=args.history_days)} .. "
              f"{args.business_date} (+{args.future_days} days on the books)", file=sys.stderr)
        seeder = Seeder(args.business_date, args.history_days, args.future_days, args.seed)
        rows = seeder.run()
        load(conn, rows, args.business_date, seeder.start)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
