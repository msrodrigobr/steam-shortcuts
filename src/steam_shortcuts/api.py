"""Public library API for local Steam shortcut management."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .discovery import discover_steam_root, list_profile_ids, select_profile
from .models import ShortcutRequest, ShortcutResult, SteamProfile
from .process import ensure_steam_not_running
from .service import (
    ShortcutAdditionPlan,
    add_shortcut_to_profile,
    plan_shortcut_addition,
    to_unsigned_int32,
)
from .vdf_store import VdfMap, VdfValue, load_shortcuts


@dataclass(frozen=True, slots=True)
class SteamInstallation:
    """A discovered Steam root and the numeric user profiles beneath it."""

    steam_root: Path
    profile_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShortcutPreview:
    """An addition plan resolved to one Steam profile without a file write."""

    steam_root: Path
    profile: SteamProfile
    plan: ShortcutAdditionPlan


@dataclass(frozen=True, slots=True)
class ShortcutListing:
    """A shortcut shown by the list API."""

    index: str
    name: str
    executable: str
    app_id: int | None


def detect_steam(steam_root: Path | None = None) -> SteamInstallation:
    """Discover Steam and return its selectable local profiles."""
    root = discover_steam_root(steam_root)
    return SteamInstallation(steam_root=root, profile_ids=list_profile_ids(root))


def list_shortcuts(
    *,
    steam_root: Path | None = None,
    steam_id: str | None = None,
) -> tuple[SteamProfile, tuple[ShortcutListing, ...]]:
    """List non-Steam shortcuts from exactly one selected profile."""
    installation = detect_steam(steam_root)
    profile = select_profile(installation.steam_root, steam_id)
    root = load_shortcuts(profile.shortcuts_path)
    shortcuts = _shortcut_map(root)
    listings = tuple(
        _listing(index, entry)
        for index, entry in sorted(shortcuts.items(), key=_shortcut_sort_key)
        if isinstance(entry, dict)
    )
    return profile, listings


def preview_shortcut(
    *,
    name: str,
    executable: Path,
    start_dir: Path | None = None,
    launch_options: str = "",
    icon: Path | None = None,
    tags: Iterable[str] = (),
    steam_root: Path | None = None,
    steam_id: str | None = None,
) -> ShortcutPreview:
    """Resolve and validate an add operation without changing Steam files."""
    installation = detect_steam(steam_root)
    ensure_steam_not_running()
    profile = select_profile(installation.steam_root, steam_id)
    request = ShortcutRequest(
        name=name,
        executable=executable,
        start_dir=start_dir,
        launch_options=launch_options,
        icon=icon,
        tags=tuple(tags),
    )
    plan = plan_shortcut_addition(load_shortcuts(profile.shortcuts_path), request)
    return ShortcutPreview(steam_root=installation.steam_root, profile=profile, plan=plan)


def add_shortcut(
    *,
    name: str,
    executable: Path,
    start_dir: Path | None = None,
    launch_options: str = "",
    icon: Path | None = None,
    tags: Iterable[str] = (),
    steam_root: Path | None = None,
    steam_id: str | None = None,
) -> ShortcutResult:
    """Safely add a non-Steam shortcut and return its verified result."""
    tag_values = tuple(tags)
    preview = preview_shortcut(
        name=name,
        executable=executable,
        start_dir=start_dir,
        launch_options=launch_options,
        icon=icon,
        tags=tag_values,
        steam_root=steam_root,
        steam_id=steam_id,
    )
    request = ShortcutRequest(
        name=name,
        executable=executable,
        start_dir=start_dir,
        launch_options=launch_options,
        icon=icon,
        tags=tag_values,
    )
    return add_shortcut_to_profile(
        preview.profile.shortcuts_path,
        preview.profile.profile_id,
        request,
    )


def _shortcut_map(root: VdfMap) -> dict[str, VdfValue]:
    shortcuts = root["shortcuts"]
    if not isinstance(shortcuts, dict):
        raise ValueError("'shortcuts' must be a mapping")
    return shortcuts


def _listing(index: str, entry: dict[str, VdfValue]) -> ShortcutListing:
    name = entry.get("AppName", entry.get("appname", ""))
    executable = entry.get("Exe", entry.get("exe", ""))
    raw_app_id = entry.get("appid")
    app_id = (
        to_unsigned_int32(raw_app_id)
        if isinstance(raw_app_id, int) and not isinstance(raw_app_id, bool)
        else None
    )
    return ShortcutListing(
        index=index,
        name=name if isinstance(name, str) else "",
        executable=_unquote(executable) if isinstance(executable, str) else "",
        app_id=app_id,
    )


def _shortcut_sort_key(item: tuple[str, VdfValue]) -> tuple[int, int | str]:
    index, _ = item
    return (0, int(index)) if index.isdecimal() else (1, index)


def _unquote(value: str) -> str:
    return value.strip().removeprefix('"').removesuffix('"')
