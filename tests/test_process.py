from pathlib import Path

import pytest

from steam_shortcuts.discovery import select_profile
from steam_shortcuts.errors import ProfileNotFound, ProfileSelectionRequired, SteamRunning
from steam_shortcuts.process import ensure_steam_not_running


def _profile(root: Path, profile_id: str) -> Path:
    profile = root / "userdata" / profile_id / "config"
    profile.mkdir(parents=True)
    return profile / "shortcuts.vdf"


def test_select_profile_ignores_zero_and_nonnumeric_directories(tmp_path: Path) -> None:
    _profile(tmp_path, "0")
    _profile(tmp_path, "not-a-profile")
    expected = _profile(tmp_path, "123")

    profile = select_profile(tmp_path)

    assert profile.profile_id == "123"
    assert profile.shortcuts_path == expected


def test_select_profile_requires_an_explicit_id_when_multiple_profiles_exist(
    tmp_path: Path,
) -> None:
    _profile(tmp_path, "123")
    _profile(tmp_path, "456")

    with pytest.raises(ProfileSelectionRequired, match="123, 456"):
        select_profile(tmp_path)


def test_select_profile_returns_requested_existing_profile(tmp_path: Path) -> None:
    expected = _profile(tmp_path, "456")
    _profile(tmp_path, "123")

    profile = select_profile(tmp_path, profile_id="456")

    assert profile.profile_id == "456"
    assert profile.shortcuts_path == expected


def test_select_profile_rejects_unknown_requested_profile(tmp_path: Path) -> None:
    _profile(tmp_path, "123")

    with pytest.raises(ProfileNotFound, match="456"):
        select_profile(tmp_path, profile_id="456")


@pytest.mark.parametrize("process_names", [("steam.exe",), ("steam",)])
def test_running_steam_process_blocks_mutation(process_names: tuple[str, ...]) -> None:
    with pytest.raises(SteamRunning):
        ensure_steam_not_running(process_names)


def test_steam_webhelper_alone_does_not_block_mutation() -> None:
    ensure_steam_not_running(("steamwebhelper.exe",))
