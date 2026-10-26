"""HTTP client for the FNSrooms PMS API (https://ms.fnsmanager.com/api-doc/pms/).

Every method is a POST with a JSON body (usually {"filter": {...}}) and HTTP Basic credentials."""

import json
import re
import time
from typing import Any

import httpx2

from .config import Config

ENDPOINTS = {
    "master": "/v1/maestros/alojamiento.php",
    "exchange": "/v1/maestros/cambio.php",
    "production": "/v1/ventas/produccion.php",
    "production_cc": "/v1/ventas/produccion_cc.php",
    "sales_reservations": "/v1/custom/ventas1.php",
    "pos": "/v1/ventas/pos.php",
    "revenue": "/v1/ventas/revenue.php",
    "payments": "/v1/contabilidad/cobros.php",
    "invoices": "/v1/contabilidad/facturacion.php",
    "accounting_production": "/v1/contabilidad/produccion.php",
    "reservations": "/v1/reservas/listado.php",
    "blocks": "/v1/reservas/bloqueos.php",
    "availability": "/v1/disponibilidad/consulta.php",
}


class FNSError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AuthError(FNSError):
    """Wrong credentials, or the account may not read this hotel: stop the run."""


class Unreachable(FNSError):
    """The API didn't answer (timeouts, refused or dropped connections) after the retries."""


class TooSlow(FNSError):
    """The API accepted the request but didn't finish the answer in time (e.g. a long date range)."""


class RangeTooLong(FNSError):
    """The API refuses the date range as too long (disponibilidad says so with a 403)."""


class MissingRate(FNSError):
    """FNS has no exchange rate for the requested currency on a date (usually the latest days)."""


# Answers that mean "nothing to return" whatever their status (bloqueos.php says it with a 403).
NO_DATA = re.compile(r"no se (han )?encontrad|sin (datos|resultados)|no hay (datos|resultados|registros)", re.I)
MISSING_RATE = re.compile(r"no existe tipo de cambio", re.I)
RANGE_TOO_LONG = re.compile(r"rango de fechas no puede|superior a \d+ d[ií]as|period not valid", re.I)


def _message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("mensaje", "error", "message"):
            if payload.get(key):
                return str(payload[key])
    return fallback


class FNSClient:
    def __init__(self, config: Config, transport: httpx2.BaseTransport | None = None,
                 retries: int = 2, sleep=time.sleep):
        self.config = config
        self.retries = retries
        self.sleep = sleep
        self.http = httpx2.Client(base_url=config.base_url, auth=(config.user, config.password),
                                  timeout=httpx2.Timeout(300, connect=20), transport=transport,
                                  headers={"Accept": "application/json"})

    def close(self) -> None:
        self.http.close()

    def call(self, name: str, body: dict[str, Any]) -> Any:
        """The decoded JSON response, or None when the API has no data for the request (404, or a
        "No se han encontrado..." message)."""
        path = ENDPOINTS[name]
        for attempt in range(self.retries + 1):
            try:
                r = self.http.post(path, json=body)
            except httpx2.ReadTimeout as e:
                # Not retried: the same request would be as slow. The caller can ask for less.
                raise TooSlow(f"{path}: no answer within {self.http.timeout.read:.0f} s") from e
            except httpx2.TransportError as e:
                if attempt == self.retries:
                    raise Unreachable(f"{path}: could not reach the API ({e.__class__.__name__}: {e})") from e
                self.sleep(2 ** (attempt + 1))
                continue
            if r.status_code >= 500 and attempt < self.retries:
                self.sleep(2 ** (attempt + 1))
                continue
            break
        try:
            payload = r.json()
        except (json.JSONDecodeError, ValueError):
            payload = None
        message = _message(payload, "")
        if r.status_code == 404 or (r.status_code >= 400 and NO_DATA.search(message)):
            return None
        if MISSING_RATE.search(message):
            raise MissingRate(f"{path}: {message} (HTTP {r.status_code})", r.status_code)
        if r.status_code >= 400 and RANGE_TOO_LONG.search(message):
            raise RangeTooLong(f"{path}: {message} (HTTP {r.status_code})", r.status_code)
        if r.status_code in (401, 403):
            raise AuthError(f"{path}: {_message(payload, 'access denied')} (HTTP {r.status_code}). "
                            "Check FNS_USER, FNS_PASSWORD, FNS_CENTRAL_ID and FNS_ALOJAMIENTO_ID.",
                            r.status_code)
        if r.status_code >= 400:
            raise FNSError(f"{path}: {_message(payload, r.text[:300])} (HTTP {r.status_code})", r.status_code)
        if payload is None:
            if not r.text.strip():
                return None
            raise FNSError(f"{path}: the response is not JSON: {r.text[:300]!r}", r.status_code)
        if isinstance(payload, dict) and set(payload) <= {"error", "@attributes", "mensaje"} and payload:
            raise FNSError(f"{path}: {_message(payload, 'error')}", r.status_code)
        return payload
