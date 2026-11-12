from pathlib import Path

import pytest

from steam_shortcuts.discovery import discover_steam_root
from steam_shortcuts.errors import SteamNotFound


def _steam_root(path: Path) -> Path:
    (path / "userdata").mkdir(parents=True)
    return path


def test_explicit_steam_root_wins_over_platform_candidates(tmp_path: Path) -> None:
    explicit = _steam_root(tmp_path / "portable-steam")
    _steam_root(tmp_path / ".local" / "share" / "Steam")

    assert discover_steam_root(
        explicit_root=explicit,
        system_name="Linux",
        home=tmp_path,
    ) == explicit.resolve()


def test_windows_registry_path_is_checked_before_standard_locations(tmp_path: Path) -> None:
    registry_steam = _steam_root(tmp_path / "registry-steam")

    assert discover_steam_root(
        system_name="Windows",
        home=tmp_path,
        registry_path=registry_steam,
    ) == registry_steam.resolve()


def test_linux_default_location_is_discovered(tmp_path: Path) -> None:
    steam_root = _steam_root(tmp_path / ".local" / "share" / "Steam")

    assert discover_steam_root(system_name="Linux", home=tmp_path) == steam_root.resolve()


def test_macos_default_location_is_discovered(tmp_path: Path) -> None:
    steam_root = _steam_root(tmp_path / "Library" / "Application Support" / "Steam")

    assert discover_steam_root(system_name="Darwin", home=tmp_path) == steam_root.resolve()


def test_missing_steam_raises_error_with_paths_tried(tmp_path: Path) -> None:
    with pytest.raises(SteamNotFound, match="Tried:"):
        discover_steam_root(system_name="Linux", home=tmp_path)
