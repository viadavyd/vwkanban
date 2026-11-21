"""`vwk user create|passwd|list` — manage accounts from the app container."""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from vwkanban.auth.models import User
from vwkanban.auth.users import create_user, find_user, set_password
from vwkanban.config import get_settings
from vwkanban.db import make_engine, make_sessionmaker


class CliError(Exception):
    pass


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise CliError("passwords do not match")
    return first


async def _run(args: argparse.Namespace) -> None:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as db:
            if args.action == "list":
                for name, created in await db.execute(
                    select(User.username, User.created_at).order_by(User.username)
                ):
                    print(f"{name}\t{created:%Y-%m-%d %H:%M}")
                return
            password = _read_password(args.password_stdin)
            if args.action == "create":
                try:
                    user = await create_user(db, args.username, password)
                except ValueError as e:
                    raise CliError(str(e)) from None
                if user is None:
                    raise CliError(f"user {args.username!r} already exists")
                await db.commit()
                print(f"created user {user.username}")
            else:  # passwd
                user = await find_user(db, args.username)
                if user is None:
                    raise CliError(f"no user {args.username!r}")
                try:
                    await set_password(db, user, password)
                except ValueError as e:
                    raise CliError(str(e)) from None
                await db.commit()
                print(f"password changed for {user.username}; their sessions were logged out")
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vwk", description="VWKanban admin commands")
    sub = parser.add_subparsers(dest="group", required=True)
    user = sub.add_parser("user", help="manage users")
    actions = user.add_subparsers(dest="action", required=True)
    for name, help_ in (("create", "create a user"), ("passwd", "change a user's password")):
        p = actions.add_parser(name, help=help_)
        p.add_argument("username")
        p.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    actions.add_parser("list", help="list users")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except CliError as e:
        print(f"vwk: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
