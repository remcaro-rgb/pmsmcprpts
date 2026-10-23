"""A stand-in for the FNSrooms API, answering every method in the shapes of its OpenAPI spec
(https://ms.fnsmanager.com/api-doc/pms/json/api-schema.json), including its PHP quirks: numbers
as strings, [] for empty objects, "0000-00-00" dates and keys with stray spaces."""

import base64
import json
from datetime import date, timedelta

import httpx2

USER, PASSWORD = "fns-user", "fns-secret"


def _days(f):
    d, end = date.fromisoformat(f["start_date"]), date.fromisoformat(f["end_date"])
    while d <= end:
        yield d
        d += timedelta(days=1)


class FakeFNS:
    def __init__(self, alojamiento_id: int, today: date):
        self.aloj = alojamiento_id
        self.today = today
        self.calls: list[tuple[str, dict]] = []
        self.down: set[str] = set()  # paths that time out, as when the API stops answering

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path in self.down:
            raise httpx2.ConnectTimeout("The handshake operation timed out", request=request)
        expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx2.Response(403, json={"mensaje": "Los datos de acceso no son válidos"})
        body = json.loads(request.content)
        path = request.url.path
        self.calls.append((path, body))
        f = body.get("filter", body)
        if "alojamiento_id" in f and f["alojamiento_id"] not in ("", self.aloj, 0):
            return httpx2.Response(403, json={"@attributes": {"error_code": "1"},
                                              "error": "PMS not allowed to this property"})
        handler = getattr(self, path.strip("/").replace("/", "_").replace(".php", ""))
        result = handler(f, body)
        return result if isinstance(result, httpx2.Response) else httpx2.Response(200, json=result)

    # maestros
    def v1_maestros_alojamiento(self, f, body):
        lists = {
            "th": {"101": "Doble", "102": "Suite Junior"},
            "cc": {"1": "Alojamiento", "2": "Restaurante"},
            "canales": {"5": "Booking", "6": "Directo"},
            "segmentos": {"3": "Ocio", "4": "Empresa"},
            "ofertas": {"900": "Tarifa flexible"},
            "th_completo": {"101": {"id": "101", "nombre": "Doble", "capacidad": "2"}},
        }
        kind = f["listado"]
        if kind == "usuariosGastro":
            return httpx2.Response(422, json={"mensaje": "Listado no disponible"})
        return {(" " + kind if kind == "cc" else kind): lists.get(kind, [])}

    def v1_maestros_cambio(self, f, body):
        return [{d.isoformat(): "4089.5000000000"} for d in _days(f)]

    # ventas
    def v1_ventas_revenue(self, f, body):
        out = {}
        for d in _days(f):
            future = d >= self.today
            out[d.isoformat()] = {
                "num_hab_tot": "30" if d.day % 2 else 28, "fecha_mysql": d.isoformat(),
                "fecha": d.strftime("%d/%m/%Y"), "dia_semana": "Lun", "bloqueadas": 0 if d.day % 2 else 2,
                "ocupadas_totales": 21, "ocupadas": 20 if not future else 10, "ocupadas_sinprecio": 1,
                "dayuse": 0, "precio_total_act": "1600.50" if not future else 800.25, "comision": 115.11,
                "checkin": 8, "checkout": 11, "camas_extras": 1, "cunas": 1, "habitaciones_grupo": 0,
                "estancia_media": 1.58, "pax": 47, "pax_totales": 47, "adultos": 42, "adolescente": None,
                "nino": 4, "bebe": 1, "disponibles": 9, "precio_medio": 80.025, "porc_gen_ocu": 70,
                "porc_cos_ocu": 66.67, "revpar": 53.35, "canceladas": 2, "pax_sinprecio": 0,
            }
        out["total"] = {"precio_medio": 80.0, "ocupadas": 20 * len(out)}
        return out

    def v1_ventas_produccion_cc(self, f, body):
        return {str(self.aloj): {d.isoformat(): {"1": 1600.5, "2": "245.30"} for d in _days(f)}}

    def v1_ventas_produccion(self, f, body):
        assert body["group"] == ["canal_id", "segmento_id"]
        if date.fromisoformat(f["start_date"]) >= self.today - timedelta(days=1):  # as the real API answers
            return httpx2.Response(422, json={"mensaje": f"No existe tipo de cambio en la fecha: {f['start_date']} "
                                                         f"para la moneda con id: {f['moneda_id']}"})
        # The live API's layout: channels only, each amount in a one-element list.
        return {"0": [100.0], "5": [1350.5], "6": ["250.00"]}

    def v1_custom_ventas1(self, f, body):
        # One reservation staying the two nights before today, with the nights inside the range.
        stay = [d for d in (self.today - timedelta(days=2), self.today - timedelta(days=1)) if d in set(_days(f))]
        if not stay:
            return []
        guest = {
            "reservation_id": 92732, "nombre_titular": "María Rodríguez", "email_titular": "maria@example.com",
            "nombre_empresa": "", "nombre_agencia": "Travel Agency", "agente": "", "nombre_tarifa": "Tarifa flexible",
            "noches": 2, "fecha_reserva": "2026-09-01 10:15:00",
            "fecha_entrada": (self.today - timedelta(days=2)).isoformat(), "fecha_salida": self.today.isoformat(), "nombre_th": "Doble", "ocupacion": 2,
            "segmento": "Ocio", "subsegmento": "", "canal": "Booking", "genero": "F", "nacionalidad": "COL",
            "procedencia": "Bogotá", "motivo": "",
            "dias": [{"fecha_produccion": d.isoformat(), "rrev": 150.75, "orev": 0, "coste": 10, "cortesia": 0}
                     for d in stay],
        }
        return [{**guest, "nombre_huesped": "María Rodríguez", "edad": 34},
                {**guest, "nombre_huesped": "Juan Pérez", "edad": 36}]

    def v1_ventas_pos(self, f, body):
        return [{"alojamiento_id": self.aloj, "punto_de_venta_id": 1, "fecha": d.isoformat(), "receta_id": 55,
                 "codigo": "REC001", "cantidad": 5, "nombre": "Tarta de Queso", "valor": 25.5, "impuesto": 5.36,
                 "costo": 10.2} for d in _days(f)]

    # contabilidad
    def _accounting(self, f, source):
        return {"movimientos": {f"{source}_{d}": self._entry(source, d) for d in map(date.isoformat, _days(f))},
                "terceros": {"12345678Z": {"cif": "12345678Z", "nombre": "John Doe", "nombrecompleto": "John Doe",
                                           "tipo_documento": "NIF", "pais_iso": "ES"}}}

    @staticmethod
    def _entry(source, d):
        return {
            "identificador": f"{source}_{d}", "auxiliar_operativo": "R92732", "origen": "reservas", "fuente": source,
            "fecha": f"{d}T10:30:00", "moneda_id": 1, "currency": "EUR", "cif": "12345678Z", "fp_id": "1",
            "fp_codigo": "TARJETA", "tipocuenta": "Caja", "factura": None,
            "debito": {"0": {"cuenta": "57200001", "fp_id": "1", "descripcion": "Tarjeta", "importe": -150.75}},
            "credito": {"0": {"cuenta": "43000001", "descripcion": "Tarjeta", "importe": 150.75},
                        "IMP10": {"cuenta": "47700010", "descripcion": "IVA 10%", "importe": 13.7, "base": 137.05,
                                  "impuesto": 10, "cc": 1, "cc_nombre": "Alojamiento"}}}

    def v1_contabilidad_cobros(self, f, body):
        return self._accounting(f, "cobros")

    def v1_contabilidad_facturacion(self, f, body):
        return {"movimientos": [], "terceros": []}  # PHP's empty objects

    def v1_contabilidad_produccion(self, f, body):
        return self._accounting(f, "produccion")

    # reservas
    def v1_reservas_listado(self, f, body):
        days = list(_days(f))
        if len(days) > 30:
            return httpx2.Response(422, json={"@attributes": {"error_code": "2"}, "error": "Period not valid"})
        created = self.today - timedelta(days=3)
        if created not in days:
            return []
        state = {"Todas": "Confirmada", "canceladas": "Cancelada", "modificadas": "Modificada"}[f["estado"]]
        loc = {"Todas": "4882407816", "canceladas": "4882407999", "modificadas": "4882407816"}[f["estado"]]
        return {"92732": {  # the real API keys bookings by id
            "info": {"channel_id": 12, "reservation_ch_id": loc, "localizador": loc, "alojamiento_id": self.aloj,
                     "estado": state, "fecha_entrada": (self.today + timedelta(days=10)).isoformat(),
                     "fecha_salida": (self.today + timedelta(days=13)).isoformat(),
                     "valid_to": "0000-00-00 00:00:00", "guests": 2, "horallegada": "18:00:00",
                     "payment_model": "Al Hotel", "special_condition": "<strong>Desglose</strong>",
                     "moneda_id": 1, "paid_online": 0, "total_price": "450.00", "pay_on_arrival": 450,
                     "comision": 67.5, "creation_date": f"{created} 00:48:31",
                     "cancellation_date": "0000-00-00 00:00:00" if f["estado"] != "canceladas"
                     else f"{created} 09:00:00",
                     "updated_date": "0000-00-00 00:00:00", "tipo": "individual", "channel_nombre": "Booking",
                     "cod_res": "CHA_92732"},
            "inhouse": {"Check In": {"valor": "Pendiente", "updated_at": None, "updated_by": None}},
            "importes": {"pagado_online": 0, "pendiente": 450, "pago_llegada": 450, "total": "450.00",
                         "habitaciones": "450.00"},
            "details": {"116911": {"detail": {"reservation_id": "92732", "tipo_habitacion_id": "101",
                                              "occupancy": "2", "regimen_id": "1", "oferta_id": "900",
                                              "price": "409.09", "price_after_tax": "450.00",
                                              "client_name": "Jorge Prieto",
                                              "fecha_entrada": (self.today + timedelta(days=10)).isoformat(),
                                              "fecha_salida": (self.today + timedelta(days=13)).isoformat(),
                                              "noches": "3"}}},
            "cliente": {"nombre": "Jorge", "primerapellido": "Prieto", "email": "jorge@example.com",
                        "telefono": "+34 984 200 328", "pais": "ES"},
            "titular": {"nombre": "Jorge", "primerapellido": "Prieto", "email": "jorge@example.com",
                        "telefono": "+34 984 200 328", "pais": "ES"},
            "cuentas": [],
        }}

    def v1_reservas_bloqueos(self, f, body):
        if len(list(_days(f))) > 30:
            return httpx2.Response(400, json={"@attributes": {"error_code": "2"}, "error": "Period not valid"})
        start = date.fromisoformat(f["start_date"])
        if not start <= self.today + timedelta(days=5) <= date.fromisoformat(f["end_date"]):
            # The real API: "no blocks" is a 403.
            return httpx2.Response(403, json={"@attributes": {"error_code": "1"},
                                              "error": "No se han encontrado bloqueos"})
        return {"bloqueos": {"538": {
            "bloqueo_id": 538, "tipo_habitacion_id": 101, "nombre_propietario": "Doble", "habitacion_id": 36642,
            "nombre": "303", "alojamiento_id": self.aloj,
            "fecha_inicio": (self.today + timedelta(days=5)).isoformat(),
            "fecha_fin": (self.today + timedelta(days=6)).isoformat(), "razon": "Mantenimiento preventivo",
            "created_by": 5586, "created_at": "2026-10-01 10:48:44", "updated_by": None, "updated_at": None}}}

    # disponibilidad
    def v1_disponibilidad_consulta(self, f, body):
        return {"dayAvailibityRoomType": [  # sic, as the real API spells it
            {"roomType": rt, "availability": 5, "date": d.isoformat(),
             "rates": [{"rate_id": 900, "prices": [{"occupancy": 1, "price": 100.0}, {"occupancy": 2, "price": 120.5}],
                        "restrictions": {"minlos": 2, "closerate": 0, "closeonarrival": 0, "closeondeparture": 1,
                                         "release": 1}},
                       {"rate_id": 901, "prices": [], "restrictions": {"closerate": 1}}]}
            for d in _days(f) for rt in (101, 102)]}
