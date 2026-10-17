"""Run the PMS MCP server.

    PMS_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms python -m pms_mcp
    python -m pms_mcp --transport streamable-http --host 0.0.0.0 --port 7070

Remote sign-in (for Claude custom connectors) turns on when PMS_PUBLIC_URL is set; see the
README for PMS_OIDC_ISSUER, PMS_OIDC_CLIENT_ID, PMS_OIDC_CLIENT_SECRET and the allowlist.
"""

import argparse
import os

from .auth import AuthConfig
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
    except ValueError as e:
        p.error(str(e))
    if auth and args.transport != "streamable-http":
        p.error("Sign-in (PMS_PUBLIC_URL) needs --transport streamable-http.")

    server = build_server(args.dsn, args.statement_timeout_ms, auth=auth)
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
