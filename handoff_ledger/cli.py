import argparse
import os
import sqlite3
import sys
from contextlib import closing
from importlib.metadata import version
from pathlib import Path
from tempfile import NamedTemporaryFile

import uvicorn

from .app import create_app
from .settings import Settings


def main() -> None:
    """Runs the application or writes a consistent online backup."""
    parser = argparse.ArgumentParser(prog="handoff-ledger", description="Review and seal documented handoffs.")
    parser.add_argument("--version", action="version", version=version("handoff-ledger"))
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the local web workspace.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8080, type=_port, metavar="PORT")
    backup = commands.add_parser("backup", help="Write a consistent copy of the workspace database.")
    backup.add_argument("destination", type=Path)

    args = parser.parse_args()
    os.umask(0o077)
    try:
        settings = Settings.from_env()
        if args.command == "serve":
            uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1)
        else:
            _backup(settings.database_path, args.destination)
            print(f"Workspace backup saved to {args.destination}.")
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"handoff-ledger: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def _port(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 5 or not 1 <= int(value) <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return int(value)


def _backup(source_path: Path, destination: Path) -> None:
    source_file = source_path.resolve().as_uri() + "?mode=ro"
    destination = destination.expanduser()
    with NamedTemporaryFile(prefix=".handoff-", suffix=".sqlite3", dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)

    try:
        with (
            closing(sqlite3.connect(source_file, uri=True)) as source,
            closing(sqlite3.connect(temporary)) as target,
        ):
            source.backup(target)
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
