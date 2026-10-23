"""HTTP client for the FNSrooms PMS API (https://ms.fnsmanager.com/api-doc/pms/).

Every method is a POST with a JSON body (usually {"filter": {...}}) and HTTP Basic credentials."""

import json
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


def _message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("mensaje", "error", "message"):
            if payload.get(key):
                return str(payload[key])
    return fallback


class FNSClient:
    def __init__(self, config: Config, transport: httpx2.BaseTransport | None = None,
                 retries: int = 3, sleep=time.sleep):
        self.config = config
        self.retries = retries
        self.sleep = sleep
        self.http = httpx2.Client(base_url=config.base_url, auth=(config.user, config.password),
                                  timeout=httpx2.Timeout(180, connect=20), transport=transport,
                                  headers={"Accept": "application/json"})

    def close(self) -> None:
        self.http.close()

    def call(self, name: str, body: dict[str, Any]) -> Any:
        """The decoded JSON response, or None when the API answers 404 (no data for the request)."""
        path = ENDPOINTS[name]
        for attempt in range(self.retries + 1):
            try:
                r = self.http.post(path, json=body)
            except httpx2.TransportError as e:
                if attempt == self.retries:
                    raise FNSError(f"{path}: could not reach the API ({e.__class__.__name__}: {e})") from e
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
        if r.status_code == 404:
            return None
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
