"""Command-line interface for steam-shortcuts."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command parser."""
    parser = argparse.ArgumentParser(
        prog="steam-shortcuts",
        description="Safely manage local Steam non-Steam shortcuts.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")
    subcommands.add_parser("add", help="Add a non-Steam shortcut (not implemented yet).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit code."""
    parser = build_parser()
    try:
        parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
