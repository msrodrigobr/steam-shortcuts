"""Command-line interface for steam-shortcuts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from . import api
from .credentials import configure_steamgriddb_api_key
from .errors import SteamShortcutsError
from .executable_metadata import read_executable_metadata
from .models import (
    ArchiveInspection,
    ExecutableMetadata,
    ShortcutResult,
    SteamGridDbGame,
    SteamStoreGame,
)
from .protondb import get_protondb_report
from .steam_store import search_steam_store_games
from .steamgriddb import search_steamgriddb_games


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

    configure_parser = subcommands.add_parser(
        "configure-steamgriddb",
        help="Prompt once and save a local SteamGridDB API key.",
    )
    configure_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    list_parser = subcommands.add_parser("list", help="List shortcuts in one Steam profile.")
    _add_root_argument(list_parser)
    _add_profile_argument(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    metadata_parser = subcommands.add_parser(
        "metadata",
        help="Read title candidates from a local Windows executable.",
    )
    metadata_parser.add_argument(
        "--exe",
        required=True,
        type=Path,
        help="Windows executable to inspect.",
    )
    metadata_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    lookup_parser = subcommands.add_parser(
        "lookup",
        help="Search SteamGridDB using local executable metadata.",
    )
    lookup_parser.add_argument(
        "--exe",
        required=True,
        type=Path,
        help="Windows executable whose metadata supplies the default search title.",
    )
    lookup_parser.add_argument(
        "--query",
        help="Override the title derived from executable metadata.",
    )
    lookup_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    store_search_parser = subcommands.add_parser(
        "store-search",
        help="Search the Steam Store for an explicit ProtonDB AppID.",
    )
    store_search_parser.add_argument(
        "--exe",
        required=True,
        type=Path,
        help="Windows executable whose metadata supplies the default search title.",
    )
    store_search_parser.add_argument(
        "--query",
        help="Override the title derived from executable metadata.",
    )
    store_search_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    proton_parser = subcommands.add_parser(
        "proton-report",
        help="Read ProtonDB compatibility evidence without changing Steam settings.",
    )
    proton_parser.add_argument(
        "--steam-appid",
        required=True,
        type=int,
        help="Explicit Steam Store AppID selected from store-search output.",
    )
    proton_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    artwork_parser = subcommands.add_parser(
        "artwork",
        help="Install selected SteamGridDB artwork for an existing shortcut.",
    )
    _add_root_argument(artwork_parser)
    _add_profile_argument(artwork_parser)
    artwork_parser.add_argument(
        "--steamgriddb-id",
        required=True,
        type=int,
        help="Explicit SteamGridDB game ID selected from lookup output.",
    )
    artwork_parser.add_argument(
        "--shortcut-id",
        required=True,
        type=int,
        help="Existing non-Steam shortcut ID from add or list output.",
    )
    artwork_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Back up and replace existing artwork for this shortcut.",
    )
    artwork_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve artwork and paths without downloading or writing files.",
    )
    artwork_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    add_parser = subcommands.add_parser("add", help="Add one non-Steam shortcut.")
    _add_root_argument(add_parser)
    _add_profile_argument(add_parser)
    add_parser.add_argument("--name", required=True, help="Library display name.")
    target = add_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--exe", type=Path, help="Executable file to launch.")
    target.add_argument(
        "--archive",
        type=Path,
        help="Tar archive containing an already-installed game directory.",
    )
    add_parser.add_argument(
        "--extract-to",
        type=Path,
        help="New local install directory for --archive; defaults below the current directory.",
    )
    add_parser.add_argument(
        "--exe-relative",
        help="Archive-relative POSIX path to the game .exe when selection is ambiguous.",
    )
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
        elif arguments.command == "configure-steamgriddb":
            _run_configure_steamgriddb(arguments)
        elif arguments.command == "list":
            _run_list(arguments)
        elif arguments.command == "metadata":
            _run_metadata(arguments)
        elif arguments.command == "lookup":
            _run_lookup(arguments)
        elif arguments.command == "store-search":
            _run_store_search(arguments)
        elif arguments.command == "proton-report":
            _run_proton_report(arguments)
        elif arguments.command == "artwork":
            _run_artwork(arguments)
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


def _run_configure_steamgriddb(arguments: argparse.Namespace) -> None:
    credential_path = configure_steamgriddb_api_key()
    payload = {"status": "saved", "credential_path": str(credential_path)}
    _emit(payload, arguments.json, f"SteamGridDB credential saved: {credential_path}")


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


def _run_metadata(arguments: argparse.Namespace) -> None:
    metadata = read_executable_metadata(arguments.exe)
    payload = _metadata_payload(metadata)
    _emit(payload, arguments.json, f"Metadata: {metadata.executable}")


def _run_lookup(arguments: argparse.Namespace) -> None:
    metadata = read_executable_metadata(arguments.exe)
    query = arguments.query or _default_lookup_query(metadata)
    games = search_steamgriddb_games(query)
    payload = {
        "query": query,
        "metadata": _metadata_payload(metadata),
        "games": _steamgriddb_games_payload(games),
    }
    _emit(payload, arguments.json, f"Lookup: {query} ({len(games)} candidates)")


def _run_store_search(arguments: argparse.Namespace) -> None:
    metadata = read_executable_metadata(arguments.exe)
    query = arguments.query or _default_lookup_query(metadata)
    games = search_steam_store_games(query)
    payload = {
        "query": query,
        "metadata": _metadata_payload(metadata),
        "games": _steam_store_games_payload(games),
    }
    _emit(payload, arguments.json, f"Steam Store: {query} ({len(games)} candidates)")


def _run_proton_report(arguments: argparse.Namespace) -> None:
    report = get_protondb_report(arguments.steam_appid)
    payload = {
        "app_id": report.app_id,
        "tier": report.tier,
        "best_reported_tier": report.best_reported_tier,
        "trending_tier": report.trending_tier,
        "confidence": report.confidence,
        "score": report.score,
        "total_reports": report.total_reports,
        "protondb_url": f"https://www.protondb.com/app/{report.app_id}",
        "proton_tool_recommendation": None,
        "recommendation_reason": (
            "ProtonDB's public summary does not identify a Proton version; "
            "no compatibility tool was selected or applied."
        ),
    }
    _emit(payload, arguments.json, f"ProtonDB: AppID {report.app_id} ({report.tier})")


def _run_artwork(arguments: argparse.Namespace) -> None:
    keyword_arguments = {
        "steamgriddb_game_id": arguments.steamgriddb_id,
        "shortcut_id": arguments.shortcut_id,
        "steam_root": arguments.steam_root,
        "steam_id": arguments.steam_id,
    }
    if arguments.dry_run:
        preview = api.preview_steamgriddb_artwork(**keyword_arguments)
        payload: dict[str, Any] = {
            "dry_run": True,
            "profile_id": preview.profile.profile_id,
            "steamgriddb_game_id": preview.artwork.game_id,
            "shortcut_id": arguments.shortcut_id,
            "grid_dir": str(preview.grid_dir),
            "paths": {
                "portrait": str(preview.portrait_path),
                "hero": str(preview.hero_path),
                "logo": str(preview.logo_path),
            },
            "conflicting_paths": [str(path) for path in preview.conflicting_paths],
            "artwork": {
                "game_id": preview.artwork.game_id,
                "portrait_url": preview.artwork.portrait_url,
                "hero_url": preview.artwork.hero_url,
                "logo_url": preview.artwork.logo_url,
            },
        }
        human_message = f"Artwork dry run: shortcut {arguments.shortcut_id}"
    else:
        result = api.install_steamgriddb_artwork(
            **keyword_arguments,
            overwrite=arguments.overwrite,
        )
        payload = {
            "dry_run": False,
            "shortcut_id": result.shortcut_id,
            "artwork_id": result.artwork_id,
            "grid_dir": str(result.grid_dir),
            "paths": {
                "portrait": str(result.portrait_path),
                "hero": str(result.hero_path),
                "logo": str(result.logo_path),
            },
            "backup_paths": [str(path) for path in result.backup_paths],
        }
        human_message = f"Artwork installed: shortcut {result.shortcut_id}"
    _emit(payload, arguments.json, human_message)


def _run_add(arguments: argparse.Namespace) -> None:
    _validate_add_mode(arguments)
    if arguments.archive is not None:
        _run_add_archive(arguments)
        return

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


def _run_add_archive(arguments: argparse.Namespace) -> None:
    if arguments.archive is None:  # pragma: no cover - guarded by _run_add
        raise AssertionError("archive mode requires an archive")
    keyword_arguments = {
        "name": arguments.name,
        "archive": arguments.archive,
        "extract_to": arguments.extract_to,
        "executable_relative": (
            None if arguments.exe_relative is None else PurePosixPath(arguments.exe_relative)
        ),
        "launch_options": arguments.args,
        "icon": arguments.icon,
        "tags": arguments.tag,
        "steam_root": arguments.steam_root,
        "steam_id": arguments.steam_id,
    }
    if arguments.dry_run:
        preview = api.preview_archive_shortcut(**keyword_arguments)
        payload = {
            "status": preview.plan.status,
            "dry_run": True,
            "profile_id": preview.profile.profile_id,
            "shortcuts_path": str(preview.profile.shortcuts_path),
            "shortcut_id": preview.plan.shortcut_id,
            "run_game_url": preview.plan.run_game_url,
            "backup_path": None,
        }
        payload.update(_archive_payload(preview.inspection))
    else:
        result = api.add_shortcut_from_archive(**keyword_arguments)
        payload = _result_payload(result.shortcut)
        payload.update(_archive_payload(result.inspection))
    _emit(payload, arguments.json, f"{payload['status']}: {arguments.name}")


def _validate_add_mode(arguments: argparse.Namespace) -> None:
    if arguments.exe is not None and (
        arguments.extract_to is not None or arguments.exe_relative is not None
    ):
        raise ValueError("--extract-to and --exe-relative require --archive")
    if arguments.archive is not None and arguments.start_dir is not None:
        raise ValueError(
            "--start-dir cannot be used with --archive; archive mode uses the selected "
            "executable's directory"
        )


def _result_payload(result: ShortcutResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "profile_id": result.profile_id,
        "shortcuts_path": str(result.shortcuts_path),
        "shortcut_id": result.shortcut_id,
        "run_game_url": result.run_game_url,
        "backup_path": None if result.backup_path is None else str(result.backup_path),
    }


def _archive_payload(inspection: ArchiveInspection) -> dict[str, Any]:
    return {
        "archive": str(inspection.archive),
        "extract_to": str(inspection.extract_to),
        "executable": str(inspection.executable),
        "executable_relative": str(inspection.executable_relative),
        "archive_root": None if inspection.archive_root is None else str(inspection.archive_root),
        "selection": inspection.selection,
    }


def _metadata_payload(metadata: ExecutableMetadata) -> dict[str, Any]:
    return {
        "executable": str(metadata.executable),
        "product_name": metadata.product_name,
        "file_description": metadata.file_description,
        "original_filename": metadata.original_filename,
        "company_name": metadata.company_name,
        "internal_name": metadata.internal_name,
        "product_version": metadata.product_version,
        "title_candidates": [
            {"value": candidate.value, "source": candidate.source}
            for candidate in metadata.title_candidates
        ],
    }


def _default_lookup_query(metadata: ExecutableMetadata) -> str:
    if not metadata.title_candidates:
        raise ValueError("executable metadata contained no usable title; provide --query")
    return metadata.title_candidates[0].value


def _steamgriddb_games_payload(games: tuple[SteamGridDbGame, ...]) -> list[dict[str, Any]]:
    return [
        {
            "id": game.id,
            "name": game.name,
            "types": list(game.types),
            "verified": game.verified,
        }
        for game in games
    ]


def _steam_store_games_payload(games: tuple[SteamStoreGame, ...]) -> list[dict[str, Any]]:
    return [
        {"app_id": game.app_id, "name": game.name, "kind": game.kind}
        for game in games
    ]


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
