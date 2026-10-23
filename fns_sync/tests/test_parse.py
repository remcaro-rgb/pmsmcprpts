"""Parsing FNS responses, including the PHP quirks, and the settings."""

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from fns_sync import parse
from fns_sync.config import Config
from fns_sync.sync import windows

ENV = {"FNS_USER": "u", "FNS_PASSWORD": "p", "FNS_CENTRAL_ID": "1765", "FNS_ALOJAMIENTO_ID": "7376"}


def test_values():
    assert parse.num("164.16") == Decimal("164.16") and parse.num(24) == 24 and parse.num("") is None
    assert parse.num("1,5") == Decimal("1.5") and parse.num("n/a") is None and parse.num(True) is None
    assert parse.integer("30") == 30 and parse.integer("2.5") is None
    assert parse.day("0000-00-00") is None and parse.day("15/07/2024") == date(2024, 7, 15)
    assert parse.stamp("0000-00-00 00:00:00") is None
    assert parse.stamp("2024-01-15T10:30:00") == datetime(2024, 1, 15, 10, 30)
    assert parse.clock("18:00:00") == time(18) and parse.text("  ") is None
    assert list(parse.items([])) == [] and dict(parse.items({" cc": 1})) == {"cc": 1}


def test_master_and_revenue():
    rows = parse.master({"th": {"22854": "Doble"}, " cc": [], "th_completo": {"1": {"id": 1, "nombre": "Doble"}}})
    assert rows == [{"kind": "th", "item_id": "22854", "name": "Doble", "data": None},
                    {"kind": "th_completo", "item_id": "1", "name": "Doble", "data": {"id": 1, "nombre": "Doble"}}]
    days = parse.revenue({"2025-01-01": {"num_hab_tot": "30", "ocupadas": 21, "precio_total_act": 1487.22,
                                         "adolescente": None, "fecha_mysql": "2025-01-01"},
                          "total": {"ocupadas": 84}})
    assert len(days) == 1 and days[0]["rooms_total"] == 30 and days[0]["room_revenue"] == Decimal("1487.22")
    assert days[0]["teens"] is None


def test_production():
    nested = {"22": {"5": {"3": 100, "total": 100}, "6": {"3": "50.5"}, "total": 150.5}, "total": {"total": 150.5}}
    assert parse.production(nested, date(2024, 9, 2), 22) == [
        {"prod_date": date(2024, 9, 2), "channel_id": "5", "segment_id": "3", "amount": Decimal(100)},
        {"prod_date": date(2024, 9, 2), "channel_id": "6", "segment_id": "3", "amount": Decimal("50.5")}]
    # Without the alojamiento level, or with fewer levels than asked for.
    assert parse.production({"5": {"3": 1}}, date(2024, 9, 2), 22)[0]["channel_id"] == "5"
    assert parse.production({"22": {"1": 1500.75, "total": 1}}, date(2024, 9, 2), 22)[0]["segment_id"] == "1"
    assert parse.production_cc({"22": {"2024-09-15": {"1": 1250.5}}, "410": {"2024-09-15": {"10": 9}}}, 22) == [
        {"prod_date": date(2024, 9, 15), "cc_id": "1", "amount": Decimal("1250.5")}]


def test_accounting_and_reservations():
    entries, lines, parties = parse.accounting({"movimientos": {"RC_1": {
        "identificador": "RC_1", "fecha": "2024-01-15T10:30:00", "moneda_id": 1, "currency": "EUR",
        "debito": {"0": {"cuenta": "572", "importe": -150.75}}, "credito": {"0": {"cuenta": "430", "importe": 150.75}}}},
        "terceros": {"X": {"cif": "X", "nombre": "John"}}}, "payments")
    assert entries[0]["entry_id"] == "RC_1" and [ln["side"] for ln in lines] == ["debit", "credit"]
    assert parties == [{"tax_id": "X", "name": "John", "full_name": None, "document_type": None, "address": None,
                        "city": None, "email": None, "country_iso": None}]
    assert parse.accounting({"movimientos": [], "terceros": []}, "invoices") == ([], [], [])

    bookings, rooms = parse.reservations([{"info": {"localizador": "123", "estado": "Confirmada",
                                                    "cancellation_date": "0000-00-00 00:00:00",
                                                    "total_price": "164.16"},
                                           "inhouse": {"Check In": {"valor": "Realizado",
                                                                    "updated_at": "2025-10-07 13:25:15"}},
                                           "details": {"9": {"detail": {"tipo_habitacion_id": "22531", "noches": "7"}}}}])
    assert bookings[0]["cancelled_at"] is None and bookings[0]["total_price"] == Decimal("164.16")
    assert bookings[0]["checked_in_at"] == datetime(2025, 10, 7, 13, 25, 15)
    assert rooms[0]["room_type_id"] == "22531" and rooms[0]["nights"] == 7

    avail, rates = parse.availability({"dayAvailabilityRoomType": [{"roomType": 1, "availability": 5,
                                       "date": "2025-11-09", "rates": [{"rate_id": 0, "prices": [],
                                                                        "restrictions": {"closerate": 1}}]}]})
    assert avail[0]["available"] == 5 and rates[0]["occupancy"] == 0 and rates[0]["closed"] is True


def test_windows():
    w = list(windows(date(2026, 1, 1), date(2026, 3, 1)))
    assert w[0] == (date(2026, 1, 1), date(2026, 1, 30)) and w[-1][1] == date(2026, 3, 1)
    assert all((b - a).days < 30 for a, b in w)
    assert list(windows(date(2026, 1, 2), date(2026, 1, 1))) == []


def test_settings():
    cfg = Config.from_env({**ENV, "FNS_PASSWORD": "s3cr3t-value"})
    assert (cfg.central_id, cfg.alojamiento_id, cfg.hotel_name, cfg.hotel_code) == (1765, 7376, "Fragata", "FRA")
    assert "s3cr3t" not in repr(cfg)  # never in logs
    with pytest.raises(ValueError, match="FNS_PASSWORD"):
        Config.from_env({**ENV, "FNS_PASSWORD": ""})
    with pytest.raises(ValueError, match="whole number"):
        Config.from_env({**ENV, "FNS_ALOJAMIENTO_ID": "abc"})
    with pytest.raises(ValueError, match="time zone"):
        Config.from_env({**ENV, "FNS_TIMEZONE": "Mars/Base"})
    assert Config.from_env({**ENV, "FNS_SYNC_TIME": "04:30", "FNS_CURRENCY": "cop"}).currency == "COP"
