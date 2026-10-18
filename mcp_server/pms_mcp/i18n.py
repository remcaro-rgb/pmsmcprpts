"""Text the chart and document tools add themselves (dates, column headers, source lines), in
English or Latin American Spanish. Titles and commentary come from the caller in its language."""

from datetime import date
from typing import Literal

Lang = Literal["en", "es"]

MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"]
MONTHS_FULL_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                  "septiembre", "octubre", "noviembre", "diciembre"]
WEEKDAYS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def fmt_date(d: date, style: str, lang: Lang = "en") -> str:
    """Styles: day "17 Oct 2026", day_month "17 Oct", weekday "Sat 17 Oct 2026", month "Oct",
    month_year_short "Oct '26", month_year "October 2026", quarter "Q4 2026"."""
    if lang == "es":
        m, full = MONTHS_ES[d.month - 1], MONTHS_FULL_ES[d.month - 1]
        return {
            "day": f"{d.day} {m} {d.year}",
            "day_month": f"{d.day} {m}",
            "weekday": f"{WEEKDAYS_ES[d.weekday()]} {d.day} {m} {d.year}",
            "month": m,
            "month_year_short": f"{m} {d:%y}",
            "month_year": f"{full} de {d.year}",
            "quarter": f"T{(d.month - 1) // 3 + 1} {d.year}",
        }[style]
    return {
        "day": d.strftime("%-d %b %Y"),
        "day_month": d.strftime("%-d %b"),
        "weekday": d.strftime("%a %-d %b %Y"),
        "month": d.strftime("%b"),
        "month_year_short": d.strftime("%b '%y"),
        "month_year": d.strftime("%B %Y"),
        "quarter": f"Q{(d.month - 1) // 3 + 1} {d.year}",
    }[style]


# Accents restored in Spanish column names spelled out from SQL identifiers (ocupacion -> Ocupación).
ACCENTS_ES = {
    "ocupacion": "ocupación", "cancelacion": "cancelación",
    "participacion": "participación", "habitacion": "habitación", "variacion": "variación",
    "telefono": "teléfono", "anticipacion": "anticipación", "periodo": "período", "estadia": "estadía",
    "estadias": "estadías", "dias": "días", "ultima": "última", "ultimo": "último", "categoria": "categoría",
    "puntuacion": "puntuación", "resena": "reseña", "resenas": "reseñas", "pais": "país", "huesped": "huésped",
    "huespedes": "huéspedes", "comision": "comisión", "promocion": "promoción",
    "anio": "año", "trafico": "tráfico", "numero": "número",
}

# Column headers in Spanish for the database's usual result columns; others are spelled out from
# the column name.
COLUMNS_ES = {
    "adr": "ADR", "revpar": "RevPAR", "occupancy": "Ocupación", "period": "Período", "hotel_code": "Hotel",
    "hotel": "Hotel", "hotel_name": "Hotel", "hotel_id": "ID de hotel", "city": "Ciudad", "country": "País",
    "room_revenue": "Ingresos por habitaciones", "fnb_revenue": "Ingresos de A&B",
    "spa_revenue": "Ingresos de spa", "other_revenue": "Otros ingresos", "total_revenue": "Ingresos totales",
    "revenue": "Ingresos", "rooms_available": "Habitaciones disponibles", "rooms_sold": "Habitaciones vendidas",
    "room_nights": "Noches-habitación", "nights": "Noches", "reservations": "Reservas",
    "cancellations": "Cancelaciones", "cancellation_rate": "Tasa de cancelación", "no_shows": "No presentados",
    "channel": "Canal", "arrival_month": "Mes de llegada", "stay_date": "Fecha de estadía",
    "booked_on": "Fecha de reserva", "cancelled_on": "Fecha de cancelación", "lead_days": "Días de anticipación",
    "avg_lead_days": "Anticipación promedio (días)", "guest_id": "ID de huésped", "guest": "Huésped",
    "guest_name": "Huésped", "stays": "Estadías", "hotels_visited": "Hoteles visitados",
    "first_stay": "Primera estadía", "last_stay": "Última estadía", "total_spend": "Gasto total",
    "room_spend": "Gasto en habitaciones", "ancillary_spend": "Gasto adicional", "rate_plan_code": "Plan tarifario",
    "room_type_code": "Tipo de habitación", "is_actual": "Real", "fully_actual": "Completamente real",
    "score": "Puntuación", "avg_score": "Puntuación promedio", "source": "Fuente", "department": "Departamento",
    "amount": "Monto", "month": "Mes", "year": "Año", "quarter": "Trimestre", "week": "Semana", "date": "Fecha",
    "count": "Cantidad", "total": "Total", "share": "Participación",
}

TEXT = {
    "en": {
        "source": "Source: hotel PMS database · data as of {date}",
        "showing": "Showing {shown} of {total} rows",
        "about": "About",
        "generated": "Generated",
        "as_of": "Data as of (business date)",
        "sheet": "Sheet",
        "rows": "Rows",
        "query": "Source query",
        "sheet_default": "Sheet",
    },
    "es": {
        "source": "Fuente: base de datos del PMS · datos al {date}",
        "showing": "Mostrando {shown} de {total} filas",
        "about": "Acerca de",
        "generated": "Generado",
        "as_of": "Datos al (fecha de negocio)",
        "sheet": "Hoja",
        "rows": "Filas",
        "query": "Consulta de origen",
        "sheet_default": "Hoja",
    },
}


def text(key: str, lang: Lang = "en", **values) -> str:
    return TEXT[lang][key].format(**values)
