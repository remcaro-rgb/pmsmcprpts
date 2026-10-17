"""Run the PMS MCP server.

    PMS_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms python -m pms_mcp
    python -m pms_mcp --transport streamable-http --host 0.0.0.0 --port 7000
"""

import argparse
import os

from .server import build_server


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7000)
    p.add_argument("--dsn", default=os.environ.get("PMS_DATABASE_URL"), help="defaults to $PMS_DATABASE_URL")
    p.add_argument("--statement-timeout-ms", type=int,
                   default=int(os.environ.get("PMS_STATEMENT_TIMEOUT_MS", "15000")))
    args = p.parse_args()
    if not args.dsn:
        p.error("set --dsn or PMS_DATABASE_URL")

    server = build_server(args.dsn, args.statement_timeout_ms)
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
