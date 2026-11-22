import argparse
import getpass
import json
import logging
import os
import re
import time
from contextlib import closing
from pathlib import Path
from secrets import token_urlsafe

from .auth import password_hash
from .db import connect, initialize
from .demo import write_demo
from .etl import load_with_retry

LOGGER = logging.getLogger("olap")


def add_account(conn, username, role, password, *, ignore_existing=False):
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,39}", username):
        raise ValueError("Username must contain 3–40 lowercase letters, digits, dots, hyphens or underscores")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12–128 characters")
    with conn, conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO app_user (username, role, password_hash) VALUES (%s, %s, %s)
            ON CONFLICT (username) DO NOTHING RETURNING username
        """, (username, role, password_hash(password)))
        created = cursor.fetchone() is not None
    if not created and not ignore_existing:
        raise ValueError("That username already exists")
    return created


def init(args):
    with closing(connect("ADMIN_DATABASE_URL")) as conn:
        initialize(conn)
        if args.demo:
            directory = write_demo(args.inbox / "demo-2026-11-01")
            print(json.dumps(load_with_retry(directory)), flush=True)
            accounts = ("manager", "admin")
        else:
            accounts = ("admin",)
        for role in accounts:
            configured = os.environ.get(f"OLAP_BOOTSTRAP_{role.upper()}_PASSWORD")
            password = configured or token_urlsafe(18)
            if add_account(conn, role, role, password, ignore_existing=True) and not configured:
                print(f"{role} password: {password}", flush=True)


def account(args):
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        raise ValueError("Passwords differ")
    with closing(connect("ADMIN_DATABASE_URL")) as conn:
        add_account(conn, args.username, args.role, password)
    print(f"Created {args.username}")


def load(args):
    print(json.dumps(load_with_retry(args.directory), indent=2))


def worker(args):
    args.inbox.mkdir(parents=True, exist_ok=True)
    while True:
        for batch in sorted(args.inbox.iterdir()):
            if batch.name.startswith(".") or not batch.is_dir() or not (batch / "READY").is_file():
                continue
            try:
                result = load_with_retry(batch)
                if not result.get("already_loaded"):
                    LOGGER.info("%s", json.dumps(result))
            except Exception:
                LOGGER.exception("Batch %s failed. Later batches will wait for this batch to recover.", batch.name)
                if args.once:
                    return 1
                break
        if args.once:
            return 0
        time.sleep(args.interval)


def main():
    parser = argparse.ArgumentParser(prog="python -m olap")
    commands = parser.add_subparsers(required=True)
    initializer = commands.add_parser("init", help="Create the warehouse and bootstrap logins")
    initializer.add_argument("--demo", action="store_true")
    initializer.add_argument("--inbox", type=Path, default=Path("data/inbox"))
    initializer.set_defaults(handler=init)
    loader = commands.add_parser("load", help="Load one completed extract directory")
    loader.add_argument("directory", type=Path)
    loader.set_defaults(handler=load)
    add_user = commands.add_parser("user", help="Create a warehouse application account")
    add_user.add_argument("username")
    add_user.add_argument("--role", choices=("admin", "manager"), default="manager")
    add_user.set_defaults(handler=account)
    scheduler = commands.add_parser("worker", help="Check the inbox for completed daily extracts")
    scheduler.add_argument("--inbox", type=Path, default=Path(os.environ.get("OLAP_INBOX", "data/inbox")))
    scheduler.add_argument("--interval", type=int, default=900, help="Polling interval in seconds")
    scheduler.add_argument("--once", action="store_true")
    scheduler.set_defaults(handler=worker)
    args = parser.parse_args()
    if hasattr(args, "interval") and not 1 <= args.interval <= 3600:
        parser.error("--interval must be between 1 and 3600 seconds")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return args.handler(args)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
