"""Turn FNS API responses into table rows (dicts keyed by column name).

The API is PHP-backed: numbers often arrive as strings, empty objects as [], missing dates as
"0000-00-00 00:00:00", and some keys carry stray spaces. These functions accept all of that and
never raise on a single odd value: it becomes NULL."""

from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


def num(v: Any) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip().replace(",", ".") if isinstance(v, str) else str(v)
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def integer(v: Any) -> int | None:
    n = num(v)
    return int(n) if n is not None and n == n.to_integral_value() else None


def text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def key(v: Any) -> str:
    return "" if v is None else str(v).strip()


def day(v: Any) -> date | None:
    s = text(v)
    if not s or s.startswith("0000"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def stamp(v: Any) -> datetime | None:
    s = text(v)
    if not s or s.startswith("0000"):
        return None
    try:
        return datetime.fromisoformat(s.replace("T", " ")[:19])
    except ValueError:
        d = day(s)
        return datetime.combine(d, time()) if d else None


def clock(v: Any) -> time | None:
    s = text(v)
    if not s:
        return None
    try:
        return time.fromisoformat(s[:8])
    except ValueError:
        return None


def flag(v: Any) -> bool | None:
    n = integer(v)
    return None if n is None else n != 0


def items(v: Any) -> Iterable[tuple[str, Any]]:
    """(key, value) pairs of a JSON object, or of a list by position ([] is PHP's empty object)."""
    if isinstance(v, dict):
        return [(key(k), x) for k, x in v.items()]
    if isinstance(v, list):
        return [(str(i), x) for i, x in enumerate(v)]
    return []


def values(v: Any) -> list[Any]:
    return [x for _, x in items(v)]


# --- maestros -------------------------------------------------------------------------------------

def master(payload: Any) -> list[dict]:
    rows = []
    for kind, entries in items(payload):
        for item_id, value in items(entries):
            if isinstance(value, dict):
                name = next((text(value.get(k)) for k in ("nombre", "name", "descripcion", "nombre_th",
                                                          "codigo") if text(value.get(k))), None)
                rows.append({"kind": kind, "item_id": key(value.get("id")) or item_id, "name": name,
                             "data": value})
            else:
                rows.append({"kind": kind, "item_id": item_id, "name": text(value), "data": None})
    return rows


def exchange(payload: Any, from_id: int, to_id: int) -> list[dict]:
    rows = []
    for entry in values(payload) if isinstance(payload, list) else [payload]:
        for k, rate in items(entry):
            d, r = day(k), num(rate)
            if d and r is not None:
                rows.append({"rate_date": d, "from_moneda_id": from_id, "to_moneda_id": to_id, "rate": r})
    return rows


# --- ventas ---------------------------------------------------------------------------------------

REVENUE_COLUMNS = {
    "rooms_total": ("num_hab_tot", integer), "rooms_blocked": ("bloqueadas", integer),
    "rooms_sold": ("ocupadas", integer), "rooms_occupied": ("ocupadas_totales", integer),
    "rooms_complimentary": ("ocupadas_sinprecio", integer), "rooms_unsold": ("disponibles", integer),
    "day_use": ("dayuse", integer), "group_rooms": ("habitaciones_grupo", integer),
    "room_revenue": ("precio_total_act", num), "commission": ("comision", num),
    "adr": ("precio_medio", num), "occupancy_pct": ("porc_cos_ocu", num),
    "occupancy_all_pct": ("porc_gen_ocu", num), "revpar": ("revpar", num),
    "arrivals": ("checkin", integer), "departures": ("checkout", integer),
    "avg_length_of_stay": ("estancia_media", num), "extra_beds": ("camas_extras", integer),
    "cribs": ("cunas", integer), "guests": ("pax", integer), "guests_total": ("pax_totales", integer),
    "adults": ("adultos", integer), "teens": ("adolescente", integer), "children": ("nino", integer),
    "babies": ("bebe", integer), "no_shows": ("reservas_noshow", integer),
    "cancellations": ("canceladas", integer),
}


def revenue(payload: Any) -> list[dict]:
    rows = []
    for k, metrics in items(payload):
        if k.lower() == "total" or not isinstance(metrics, dict):
            continue
        d = day(metrics.get("fecha_mysql")) or day(k)
        if not d:
            continue
        row = {"stay_date": d}
        for column, (source, convert) in REVENUE_COLUMNS.items():
            row[column] = convert(metrics.get(source))
        rows.append(row)
    return rows


def production_cc(payload: Any, alojamiento_id: int) -> list[dict]:
    totals: dict[tuple, Decimal] = defaultdict(Decimal)
    for aloj, by_date in items(payload):
        if aloj != str(alojamiento_id):
            continue
        for d, by_cc in items(by_date):
            prod_date = day(d)
            for cc, amount in items(by_cc):
                a = num(amount)
                if prod_date and a is not None and cc.lower() != "total":
                    totals[(prod_date, cc)] += a
    return [{"prod_date": d, "cc_id": cc, "amount": a} for (d, cc), a in sorted(totals.items())]


def _leaves(node: Any, path: tuple = ()) -> Iterable[tuple[tuple, Decimal]]:
    if isinstance(node, (dict, list)):
        for k, v in items(node):
            if k.lower() != "total":
                yield from _leaves(v, path + (k,))
    else:
        a = num(node)
        if a is not None:
            yield path, a


def production(payload: Any, prod_date: date, alojamiento_id: int, levels: int = 2) -> list[dict]:
    """Production of one day grouped by `levels` fields (channel, segment). The response nests by
    alojamiento first and then by each group field; deeper levels are summed."""
    leaves = list(_leaves(payload))
    if leaves and all(p and p[0] == str(alojamiento_id) for p, _ in leaves) and \
            any(len(p) > levels for p, _ in leaves):
        leaves = [(p[1:], a) for p, a in leaves]
    totals: dict[tuple, Decimal] = defaultdict(Decimal)
    for path, amount in leaves:
        dims = (tuple(path[:levels]) + ("",) * levels)[:levels]
        totals[dims] += amount
    return [{"prod_date": prod_date, "channel_id": c, "segment_id": s, "amount": a}
            for (c, s), a in sorted(totals.items())]


def sales_reservations(payload: Any) -> tuple[list[dict], list[dict]]:
    reservations: dict[tuple, dict] = {}
    days: dict[tuple, dict] = {}
    for item in values(payload):
        if not isinstance(item, dict):
            continue
        rid = integer(item.get("reservation_id"))
        if rid is None:
            continue
        guest = key(item.get("nombre_huesped"))
        reservations.setdefault((rid, guest), {
            "reservation_id": rid, "guest_name": guest,
            "holder_name": text(item.get("nombre_titular")), "holder_email": text(item.get("email_titular")),
            "company": text(item.get("nombre_empresa")), "agency": text(item.get("nombre_agencia")),
            "agent": text(item.get("agente")), "rate_name": text(item.get("nombre_tarifa")),
            "nights": integer(item.get("noches")), "booked_at": stamp(item.get("fecha_reserva")),
            "arrival": day(item.get("fecha_entrada")), "departure": day(item.get("fecha_salida")),
            "room_type": text(item.get("nombre_th")), "occupancy": integer(item.get("ocupacion")),
            "segment": text(item.get("segmento")), "subsegment": text(item.get("subsegmento")),
            "channel": text(item.get("canal")), "guest_age": integer(item.get("edad")),
            "guest_gender": text(item.get("genero")), "nationality": text(item.get("nacionalidad")),
            "origin": text(item.get("procedencia")), "reason": text(item.get("motivo")),
        })
        for d in values(item.get("dias")):
            if not isinstance(d, dict) or not day(d.get("fecha_produccion")):
                continue
            k = (rid, guest, day(d.get("fecha_produccion")))
            days[k] = {"reservation_id": rid, "guest_name": guest, "prod_date": k[2],
                       "room_revenue": num(d.get("rrev")), "other_revenue": num(d.get("orev")),
                       "cost": num(d.get("coste")), "courtesy": num(d.get("cortesia"))}
    return list(reservations.values()), list(days.values())


def pos(payload: Any) -> list[dict]:
    rows: dict[tuple, dict] = {}
    for item in values(payload):
        if not isinstance(item, dict):
            continue
        d = day(item.get("fecha"))
        k = (key(item.get("punto_de_venta_id")), d, key(item.get("receta_id")) or key(item.get("codigo")))
        if not d:
            continue
        row = rows.setdefault(k, {"pos_id": k[0], "sale_date": d, "recipe_id": k[2],
                                  "code": text(item.get("codigo")), "name": text(item.get("nombre")),
                                  "quantity": Decimal(0), "value": Decimal(0), "tax": Decimal(0),
                                  "cost": Decimal(0)})
        for column, source in (("quantity", "cantidad"), ("value", "valor"), ("tax", "impuesto"),
                               ("cost", "costo")):
            row[column] += num(item.get(source)) or 0
    return list(rows.values())


# --- contabilidad ---------------------------------------------------------------------------------

def accounting(payload: Any, book: str) -> tuple[list[dict], list[dict], list[dict]]:
    entries, lines, parties = [], [], []
    payload = payload if isinstance(payload, dict) else {}
    for entry_key, m in items(payload.get("movimientos")):
        if not isinstance(m, dict):
            continue
        entry_id = key(m.get("identificador")) or entry_key
        entries.append({
            "book": book, "entry_id": entry_id, "entry_at": stamp(m.get("fecha")),
            "operational_ref": text(m.get("auxiliar_operativo")), "origin": text(m.get("origen")),
            "moneda_id": integer(m.get("moneda_id")), "currency": text(m.get("currency")),
            "tax_id": text(m.get("cif")), "document": text(m.get("documento")),
            "invoice_id": text(m.get("factura_id")), "invoice_code": text(m.get("factura_codigo")),
            "invoice_type": text(m.get("factura_tipo")), "payment_method_id": text(m.get("fp_id")),
            "payment_method": text(m.get("fp_codigo")), "account_type": text(m.get("tipocuenta")),
        })
        for side, source in (("debit", "debito"), ("credit", "credito")):
            for line_key, ln in items(m.get(source)):
                if not isinstance(ln, dict):
                    continue
                lines.append({
                    "book": book, "entry_id": entry_id, "side": side, "line_key": line_key,
                    "account": text(ln.get("cuenta")), "description": text(ln.get("descripcion")),
                    "amount": num(ln.get("importe")), "tax_base": num(ln.get("base")),
                    "tax_rate": num(ln.get("impuesto")), "cc_id": text(ln.get("cc")),
                    "cc_name": text(ln.get("cc_nombre")), "payment_method_id": text(ln.get("fp_id")),
                })
    for tax_id, t in items(payload.get("terceros")):
        if not isinstance(t, dict):
            continue
        parties.append({
            "tax_id": key(t.get("cif")) or tax_id, "name": text(t.get("nombre")),
            "full_name": text(t.get("nombrecompleto")), "document_type": text(t.get("tipo_documento")),
            "address": text(t.get("direccion")), "city": text(t.get("ciudad")),
            "email": text(t.get("email")), "country_iso": text(t.get("pais_iso")),
        })
    return entries, lines, parties


# --- reservas -------------------------------------------------------------------------------------

def _person(p: Any, prefix: str) -> dict:
    p = p if isinstance(p, dict) else {}
    return {f"{prefix}_name": text(p.get("nombre")), f"{prefix}_surname": text(p.get("primerapellido")),
            f"{prefix}_email": text(p.get("email")), f"{prefix}_phone": text(p.get("telefono")),
            f"{prefix}_country": text(p.get("pais"))}


def _done_at(inhouse: dict, name: str) -> datetime | None:
    state = inhouse.get(name)
    if isinstance(state, dict) and (text(state.get("valor")) or "").lower().startswith("realiz"):
        return stamp(state.get("updated_at"))
    return None


def reservations(payload: Any) -> tuple[list[dict], list[dict]]:
    out: dict[str, dict] = {}
    rooms: dict[tuple, dict] = {}
    for b in values(payload):
        if not isinstance(b, dict) or not isinstance(b.get("info"), dict):
            continue
        info = b["info"]
        loc = key(info.get("localizador")) or key(info.get("reservation_ch_id")) or key(info.get("cod_res"))
        if not loc:
            continue
        inhouse = b.get("inhouse") if isinstance(b.get("inhouse"), dict) else {}
        amounts = b.get("importes") if isinstance(b.get("importes"), dict) else {}
        out[loc] = {
            "localizador": loc, "status": text(info.get("estado")),
            "channel_id": integer(info.get("channel_id")), "channel": text(info.get("channel_nombre")),
            "channel_reservation_id": text(info.get("reservation_ch_id")),
            "booking_code": text(info.get("cod_res")), "booking_type": text(info.get("tipo")),
            "arrival": day(info.get("fecha_entrada")), "departure": day(info.get("fecha_salida")),
            "guests": integer(info.get("guests")), "arrival_time": clock(info.get("horallegada")),
            "payment_model": text(info.get("payment_model")),
            "total_price": num(info.get("total_price")) if num(info.get("total_price")) is not None
            else num(amounts.get("total")),
            "paid_online": num(info.get("paid_online")) if num(info.get("paid_online")) is not None
            else num(amounts.get("pagado_online")),
            "pay_on_arrival": num(info.get("pay_on_arrival")), "amount_pending": num(amounts.get("pendiente")),
            "commission": num(info.get("comision")), "moneda_id": integer(info.get("moneda_id")),
            "booked_at": stamp(info.get("creation_date")) or stamp(info.get("created_at")),
            "cancelled_at": stamp(info.get("cancellation_date")),
            "modified_at": stamp(info.get("updated_date")) or stamp(info.get("updated_at")),
            "checked_in_at": _done_at(inhouse, "Check In"), "checked_out_at": _done_at(inhouse, "Check Out"),
            "paid_at": _done_at(inhouse, "Cobrado"),
            **_person(b.get("cliente"), "client"), **_person(b.get("titular"), "holder"),
            "special_conditions": text(info.get("special_condition")),
        }
        for detail_id, wrapper in items(b.get("details")):
            d = wrapper.get("detail") if isinstance(wrapper, dict) and isinstance(wrapper.get("detail"), dict) \
                else wrapper
            if not isinstance(d, dict):
                continue
            rooms[(loc, detail_id)] = {
                "localizador": loc, "detail_id": detail_id, "reservation_id": integer(d.get("reservation_id")),
                "room_type_id": text(d.get("tipo_habitacion_id")), "occupancy": integer(d.get("occupancy")),
                "meal_plan_id": text(d.get("regimen_id")), "offer_id": text(d.get("oferta_id")),
                "price": num(d.get("price")), "price_after_tax": num(d.get("price_after_tax")),
                "client_name": text(d.get("client_name")), "arrival": day(d.get("fecha_entrada")),
                "departure": day(d.get("fecha_salida")), "nights": integer(d.get("noches")),
            }
    return list(out.values()), list(rooms.values())


def blocks(payload: Any) -> list[dict]:
    source = payload.get("bloqueos") if isinstance(payload, dict) else payload
    rows = []
    for block_key, b in items(source):
        if not isinstance(b, dict):
            continue
        rows.append({
            "block_id": key(b.get("bloqueo_id")) or block_key,
            "room_type_id": text(b.get("tipo_habitacion_id")), "room_type": text(b.get("nombre_propietario")),
            "room_id": text(b.get("habitacion_id")), "room": text(b.get("nombre")),
            "start_date": day(b.get("fecha_inicio")), "end_date": day(b.get("fecha_fin")),
            "reason": text(b.get("razon")), "created_at": stamp(b.get("created_at")),
            "updated_at": stamp(b.get("updated_at")),
        })
    return rows


# --- disponibilidad -------------------------------------------------------------------------------

def availability(payload: Any) -> tuple[list[dict], list[dict]]:
    # The API spells it "dayAvailibityRoomType"; the spec "dayAvailabilityRoomType".
    days = next((v for k, v in payload.items() if k.lower().startswith("dayavail")), None) \
        if isinstance(payload, dict) else payload
    avail: dict[tuple, dict] = {}
    rates: dict[tuple, dict] = {}
    for entry in values(days):
        if not isinstance(entry, dict):
            continue
        d, rt = day(entry.get("date")), key(entry.get("roomType"))
        if not d or not rt:
            continue
        avail[(d, rt)] = {"stay_date": d, "room_type_id": rt, "available": integer(entry.get("availability"))}
        for rate in values(entry.get("rates")):
            if not isinstance(rate, dict):
                continue
            r = rate.get("restrictions") if isinstance(rate.get("restrictions"), dict) else {}
            base = {"stay_date": d, "room_type_id": rt, "rate_id": key(rate.get("rate_id")),
                    "min_stay": integer(r.get("minlos")), "closed": flag(r.get("closerate")),
                    "closed_to_arrival": flag(r.get("closeonarrival")),
                    "closed_to_departure": flag(r.get("closeondeparture")),
                    "release_days": integer(r.get("release"))}
            prices = [p for p in values(rate.get("prices")) if isinstance(p, dict)]
            for p in prices or [{}]:
                occ = integer(p.get("occupancy")) or 0
                rates[(d, rt, base["rate_id"], occ)] = {**base, "occupancy": occ, "price": num(p.get("price"))}
    return list(avail.values()), list(rates.values())
