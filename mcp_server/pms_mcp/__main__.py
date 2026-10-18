"""Run the PMS MCP server.

    PMS_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms python -m pms_mcp
    python -m pms_mcp --transport streamable-http --host 0.0.0.0 --port 7070

Remote sign-in (for Claude custom connectors) turns on when PMS_PUBLIC_URL is set; see the
README for PMS_OIDC_ISSUER, PMS_OIDC_CLIENT_ID, PMS_OIDC_CLIENT_SECRET and the allowlist.
Without it, setting PMS_MCP_SERVICE_TOKEN makes the HTTP server private to the website's agent.
PMS_HOTEL_ACCESS limits which hotels each user sees (see pms_mcp/access.py).
"""

import argparse
import os

from .access import HotelAccess
from .auth import AuthConfig, ServiceTokenMiddleware
from .ratelimit import RateLimitMiddleware
from .server import build_server


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7070)
    p.add_argument("--dsn", default=os.environ.get("PMS_DATABASE_URL"), help="defaults to $PMS_DATABASE_URL")
    p.add_argument("--statement-timeout-ms", type=int,
                   default=int(os.environ.get("PMS_STATEMENT_TIMEOUT_MS", "15000")))
    args = p.parse_args()
    if not args.dsn:
        p.error("set --dsn or PMS_DATABASE_URL")

    try:
        auth = AuthConfig.from_env(os.environ)
        access = HotelAccess.from_env(os.environ)
    except ValueError as e:
        p.error(str(e))
    if auth and args.transport != "streamable-http":
        p.error("Sign-in (PMS_PUBLIC_URL) needs --transport streamable-http.")
    service_token = auth.service_token if auth else os.environ.get("PMS_MCP_SERVICE_TOKEN") or None
    if service_token and len(service_token) < 32:
        p.error("PMS_MCP_SERVICE_TOKEN must be at least 32 characters (openssl rand -hex 32).")

    server = build_server(args.dsn, args.statement_timeout_ms, auth=auth, access=access)
    if args.transport == "stdio":
        server.run("stdio")
        return
    import uvicorn

    app = server.streamable_http_app(host=args.host)
    if service_token and not auth:
        app = ServiceTokenMiddleware(app, service_token)
    if os.environ.get("PMS_RATE_LIMIT", "on").lower() != "off":
        # Trust X-Forwarded-For only behind a proxy (e.g. the bundled Caddy); otherwise clients could spoof it.
        app = RateLimitMiddleware(app, trust_proxy=os.environ.get("PMS_TRUST_PROXY", "").lower() == "true",
                                  service_token=service_token)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
