"""Run the agent service: python -m pms_agent [--host 0.0.0.0] [--port 7001]"""

import argparse
import logging

import uvicorn

from .app import create_app


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7001)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
