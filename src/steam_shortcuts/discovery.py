"""Steam installation discovery and profile-path helpers."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any, cast

from .errors import ProfileNotFound, ProfileSelectionRequired, SteamNotFound
from .models import SteamProfile


def discover_steam_root(
    explicit_root: Path | None = None,
    *,
    system_name: str | None = None,
    home: Path | None = None,
    registry_path: Path | None = None,
) -> Path:
    """Return a Steam root containing ``userdata``, or raise ``SteamNotFound``.

    Keyword injection points keep platform discovery testable without reading the
    host registry or a real user's home directory.
    """
    candidates: list[Path] = []
    if explicit_root is not None:
        candidates.append(explicit_root)

    system = system_name or platform.system()
    user_home = home or Path.home()
    candidates.extend(_platform_candidates(system, user_home, registry_path))

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "userdata").is_dir():
            return resolved

    raise SteamNotFound(tuple(seen))


def list_profile_ids(steam_root: Path) -> tuple[str, ...]:
    """Return numeric Steam profile IDs in stable ascending order."""
    userdata = steam_root / "userdata"
    if not userdata.is_dir():
        return ()
    return tuple(
        sorted(
            entry.name
            for entry in userdata.iterdir()
            if entry.is_dir() and entry.name.isdecimal() and entry.name != "0"
        )
    )


def select_profile(steam_root: Path, profile_id: str | None = None) -> SteamProfile:
    """Select exactly one numeric Steam profile below a discovered root."""
    available_ids = list_profile_ids(steam_root)
    if profile_id is not None:
        if profile_id not in available_ids:
            raise ProfileNotFound(profile_id)
        return _profile_from_id(steam_root, profile_id)
    if len(available_ids) == 1:
        return _profile_from_id(steam_root, available_ids[0])
    if len(available_ids) > 1:
        raise ProfileSelectionRequired(available_ids)
    raise ProfileNotFound("(no numeric profiles found)")


def _profile_from_id(steam_root: Path, profile_id: str) -> SteamProfile:
    return SteamProfile(
        profile_id=profile_id,
        shortcuts_path=steam_root / "userdata" / profile_id / "config" / "shortcuts.vdf",
    )


def _platform_candidates(
    system_name: str,
    home: Path,
    registry_path: Path | None,
) -> list[Path]:
    if system_name == "Windows":
        candidates = [registry_path] if registry_path is not None else []
        if registry_path is None:
            discovered_registry_path = _read_windows_registry_path()
            if discovered_registry_path is not None:
                candidates.append(discovered_registry_path)
        candidates.extend(_windows_default_paths())
        return candidates
    if system_name == "Darwin":
        return [home / "Library" / "Application Support" / "Steam"]
    return [
        home / ".local" / "share" / "Steam",
        home / ".steam" / "steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
    ]


def _windows_default_paths() -> list[Path]:
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\\Program Files (x86)")
    program_files = os.environ.get("PROGRAMFILES", r"C:\\Program Files")
    return [Path(program_files_x86) / "Steam", Path(program_files) / "Steam"]


def _read_windows_registry_path() -> Path | None:
    try:
        import winreg
    except ImportError:
        return None

    try:
        registry = cast(Any, winreg)
        with registry.OpenKey(registry.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            for value_name in ("SteamPath", "InstallPath"):
                try:
                    value, _ = registry.QueryValueEx(key, value_name)
                except FileNotFoundError:
                    continue
                if isinstance(value, str) and value:
                    return Path(value)
    except FileNotFoundError:
        return None
    return None
