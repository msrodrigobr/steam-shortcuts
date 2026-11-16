from pathlib import Path, PurePosixPath

import pytest

from steam_shortcuts.errors import (
    ArchiveExecutableSelectionRequired,
    InvalidArchive,
    InvalidShortcutFile,
    ProfileSelectionRequired,
    ShortcutConflict,
    SteamNotFound,
    SteamRunning,
)
from steam_shortcuts.models import ArchiveInspection, ShortcutRequest, ShortcutResult


def test_shortcut_request_rejects_blank_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="name must not be blank"):
        ShortcutRequest(name="   ", executable=tmp_path / "game.exe")


def test_shortcut_request_rejects_name_with_nul(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="name must not contain NUL"):
        ShortcutRequest(name="bad\x00name", executable=tmp_path / "game.exe")


def test_shortcut_request_rejects_launch_options_with_nul(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="launch_options must not contain NUL"):
        ShortcutRequest(
            name="Game",
            executable=tmp_path / "game.exe",
            launch_options="--bad\x00option",
        )


def test_shortcut_result_preserves_add_operation_metadata(tmp_path: Path) -> None:
    backup = tmp_path / "shortcuts.vdf.bak.20261112T020000Z"
    result = ShortcutResult(
        status="added",
        profile_id="123",
        shortcuts_path=tmp_path / "shortcuts.vdf",
        shortcut_id=3_456_789_012,
        run_game_url="steam://rungameid/123",
        backup_path=backup,
    )

    assert result.status == "added"
    assert result.profile_id == "123"
    assert result.backup_path == backup


@pytest.mark.parametrize(
    "error",
    [
        SteamNotFound("Steam was not found"),
        ProfileSelectionRequired(("123", "456")),
        SteamRunning(),
        ShortcutConflict("Game executable already exists"),
        InvalidShortcutFile(Path("shortcuts.vdf"), "invalid root"),
    ],
)
def test_domain_errors_are_specific(error: Exception) -> None:
    assert isinstance(error, Exception)


def test_archive_inspection_preserves_the_selected_archive_member(tmp_path: Path) -> None:
    inspection = ArchiveInspection(
        archive=tmp_path / "My Game.tar",
        extract_to=tmp_path / "Games" / "My Game",
        executable_relative=PurePosixPath("My Game/Game.exe"),
        selection="explicit",
        executable_candidates=(PurePosixPath("My Game/Game.exe"),),
    )

    assert inspection.executable == tmp_path / "Games" / "My Game" / "My Game" / "Game.exe"


def test_archive_inspection_rejects_an_absolute_entrypoint(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="executable_relative must be relative"):
        ArchiveInspection(
            archive=tmp_path / "My Game.tar",
            extract_to=tmp_path / "Games" / "My Game",
            executable_relative=PurePosixPath("/Game.exe"),
            selection="explicit",
            executable_candidates=(PurePosixPath("Game.exe"),),
        )


def test_archive_errors_include_actionable_context(tmp_path: Path) -> None:
    assert "not a supported tar archive" in str(
        InvalidArchive(tmp_path / "broken.7z", "not a supported tar archive")
    )
    error = ArchiveExecutableSelectionRequired(
        archive=tmp_path / "game.tar",
        candidates=(PurePosixPath("Game.exe"), PurePosixPath("bin/Launcher.exe")),
    )
    assert "--exe-relative" in str(error)
    assert "bin/Launcher.exe" in str(error)
