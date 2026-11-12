"""Command-line interface for steam-shortcuts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import api
from .errors import SteamShortcutsError
from .models import ShortcutResult


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command parser."""
    parser = argparse.ArgumentParser(
        prog="steam-shortcuts",
        description="Safely manage local Steam non-Steam shortcuts.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")

    detect_parser = subcommands.add_parser("detect", help="Find Steam and local profiles.")
    _add_root_argument(detect_parser)
    detect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    list_parser = subcommands.add_parser("list", help="List shortcuts in one Steam profile.")
    _add_root_argument(list_parser)
    _add_profile_argument(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    add_parser = subcommands.add_parser("add", help="Add one non-Steam shortcut.")
    _add_root_argument(add_parser)
    _add_profile_argument(add_parser)
    add_parser.add_argument("--name", required=True, help="Library display name.")
    add_parser.add_argument("--exe", required=True, type=Path, help="Executable file to launch.")
    add_parser.add_argument(
        "--start-dir",
        type=Path,
        help="Working directory; defaults to executable's parent.",
    )
    add_parser.add_argument("--args", default="", help="Launch options passed to the executable.")
    add_parser.add_argument("--icon", type=Path, help="Optional icon file path.")
    add_parser.add_argument(
        "--tag", action="append", default=[], help="Steam category tag; repeatable."
    )
    add_parser.add_argument(
        "--dry-run", action="store_true", help="Validate and show the planned change only."
    )
    add_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit code."""
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1

    if arguments.command is None:
        parser.print_help()
        return 0

    try:
        if arguments.command == "detect":
            _run_detect(arguments)
        elif arguments.command == "list":
            _run_list(arguments)
        elif arguments.command == "add":
            _run_add(arguments)
        else:  # pragma: no cover - argparse owns the command choices
            parser.error(f"Unsupported command: {arguments.command}")
    except (SteamShortcutsError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


def _run_detect(arguments: argparse.Namespace) -> None:
    installation = api.detect_steam(arguments.steam_root)
    payload = {
        "steam_root": str(installation.steam_root),
        "profiles": list(installation.profile_ids),
    }
    _emit(payload, arguments.json, f"Steam: {installation.steam_root}")


def _run_list(arguments: argparse.Namespace) -> None:
    profile, shortcuts = api.list_shortcuts(
        steam_root=arguments.steam_root,
        steam_id=arguments.steam_id,
    )
    listed_shortcuts = [
        {
            "index": shortcut.index,
            "name": shortcut.name,
            "executable": shortcut.executable,
            "app_id": shortcut.app_id,
        }
        for shortcut in shortcuts
    ]
    payload = {"profile_id": profile.profile_id, "shortcuts": listed_shortcuts}
    _emit(payload, arguments.json, f"Profile {profile.profile_id}: {len(shortcuts)} shortcuts")


def _run_add(arguments: argparse.Namespace) -> None:
    keyword_arguments = {
        "name": arguments.name,
        "executable": arguments.exe,
        "start_dir": arguments.start_dir,
        "launch_options": arguments.args,
        "icon": arguments.icon,
        "tags": arguments.tag,
        "steam_root": arguments.steam_root,
        "steam_id": arguments.steam_id,
    }
    if arguments.dry_run:
        preview = api.preview_shortcut(**keyword_arguments)
        payload = {
            "status": preview.plan.status,
            "dry_run": True,
            "profile_id": preview.profile.profile_id,
            "shortcuts_path": str(preview.profile.shortcuts_path),
            "shortcut_id": preview.plan.shortcut_id,
            "run_game_url": preview.plan.run_game_url,
            "backup_path": None,
        }
    else:
        result = api.add_shortcut(**keyword_arguments)
        payload = _result_payload(result)
    _emit(payload, arguments.json, f"{payload['status']}: {arguments.name}")


def _result_payload(result: ShortcutResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "profile_id": result.profile_id,
        "shortcuts_path": str(result.shortcuts_path),
        "shortcut_id": result.shortcut_id,
        "run_game_url": result.run_game_url,
        "backup_path": None if result.backup_path is None else str(result.backup_path),
    }


def _emit(payload: dict[str, Any], as_json: bool, human_message: str) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(human_message)


def _add_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--steam-root",
        type=Path,
        help="Explicit Steam root containing userdata/; overrides automatic discovery.",
    )


def _add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--steam-id", help="Numeric Steam userdata profile ID.")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
