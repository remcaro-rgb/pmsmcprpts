"""Manage the user directory from the command line (the website's admin page does the rest).

    python -m pms_agent.admin create-admin --email you@example.com --name "Your Name"
    python -m pms_agent.admin list

The password is asked for twice, or read from standard input with --password-stdin. Uses
PMS_APP_DATABASE_URL (the pms_app role). In Docker Compose:

    docker compose exec agent python -m pms_agent.admin create-admin --email you@example.com --name You
"""

import argparse
import asyncio
import getpass
import os
import sys

from .users import MIN_PASSWORD, UserDirectory, UserError


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            sys.exit("The passwords don't match.")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"Use at least {MIN_PASSWORD} characters.")
    return password


async def run(args: argparse.Namespace) -> None:
    directory = UserDirectory(args.dsn)
    if args.command == "create-admin":
        user = await directory.upsert_admin(args.email, args.name, read_password(args.password_stdin))
        print(f"Administrator {user.email} is ready (id {user.id}). Sign in to the website with it.")
    else:
        for u in await directory.list_users():
            role = "admin" if u.is_admin else "user"
            state = "" if u.active else " (inactive)"
            print(f"{u.id:>4}  {u.email:<36} {role:<5}{state}  hotels: {u.hotel_ids or '-'}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dsn", default=os.environ.get("PMS_APP_DATABASE_URL"),
                   help="defaults to $PMS_APP_DATABASE_URL")
    sub = p.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="create an administrator, or reset one's password")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    sub.add_parser("list", help="list accounts")
    args = p.parse_args()
    if not args.dsn:
        p.error("set --dsn or PMS_APP_DATABASE_URL")
    try:
        asyncio.run(run(args))
    except UserError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
