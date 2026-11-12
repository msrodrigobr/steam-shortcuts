from pathlib import Path

import pytest

from steam_shortcuts.errors import InvalidExecutable, ShortcutConflict
from steam_shortcuts.models import ShortcutRequest
from steam_shortcuts.service import plan_shortcut_addition, shortcut_app_id


def _request(executable: Path, **overrides: object) -> ShortcutRequest:
    values: dict[str, object] = {"name": "My Game", "executable": executable}
    values.update(overrides)
    return ShortcutRequest(**values)  # type: ignore[arg-type]


def test_shortcut_app_id_matches_steam_crc32_scheme() -> None:
    assert shortcut_app_id('"C:\\Games\\Game.exe"', "Game") == 3_516_482_161


def test_plan_builds_steam_compatible_shortcut_fields(tmp_path: Path) -> None:
    executable = tmp_path / "My Game" / "game.exe"
    executable.parent.mkdir()
    executable.touch()
    root: dict[str, object] = {"shortcuts": {}}

    plan = plan_shortcut_addition(root, _request(executable))

    assert plan.status == "added"
    assert plan.index == "0"
    assert plan.entry == {
        "appid": plan.shortcut_id - 2**32,
        "AppName": "My Game",
        "Exe": f'"{executable}"',
        "StartDir": f'"{executable.parent}"',
        "icon": "",
        "ShortcutPath": "",
        "LaunchOptions": "",
        "IsHidden": 0,
        "AllowDesktopConfig": 1,
        "AllowOverlay": 1,
        "openvr": 0,
        "Devkit": 0,
        "DevkitGameID": "",
        "DevkitOverrideAppID": 0,
        "LastPlayTime": 0,
        "tags": {},
    }
    assert plan.run_game_url == f"steam://rungameid/{(plan.shortcut_id << 32) | 0x02000000}"


def test_plan_preserves_optional_fields_and_tags(tmp_path: Path) -> None:
    executable = tmp_path / "game.exe"
    executable.touch()
    start_dir = tmp_path / "working"
    start_dir.mkdir()
    icon = tmp_path / "icon.ico"
    icon.touch()

    plan = plan_shortcut_addition(
        {"shortcuts": {}},
        _request(
            executable,
            start_dir=start_dir,
            launch_options="--windowed",
            icon=icon,
            tags=("Action", "Local"),
        ),
    )

    assert plan.entry is not None
    assert plan.entry["StartDir"] == f'"{start_dir}"'
    assert plan.entry["LaunchOptions"] == "--windowed"
    assert plan.entry["icon"] == str(icon)
    assert plan.entry["tags"] == {"0": "Action", "1": "Local"}


@pytest.mark.parametrize("is_directory", [False, True])
def test_plan_rejects_missing_or_directory_executable(tmp_path: Path, is_directory: bool) -> None:
    executable = tmp_path / "not-an-exe"
    if is_directory:
        executable.mkdir()

    with pytest.raises(InvalidExecutable):
        plan_shortcut_addition({"shortcuts": {}}, _request(executable))


def test_matching_name_and_executable_is_idempotent(tmp_path: Path) -> None:
    executable = tmp_path / "game.exe"
    executable.touch()
    existing = {
        "AppName": "My Game",
        "Exe": f'"{executable}"',
        "appid": -1,
    }

    plan = plan_shortcut_addition({"shortcuts": {"0": existing}}, _request(executable))

    assert plan.status == "already_exists"
    assert plan.index == "0"
    assert plan.entry is None


def test_matching_executable_with_different_name_is_a_conflict(tmp_path: Path) -> None:
    executable = tmp_path / "game.exe"
    executable.touch()
    existing = {"AppName": "Old Name", "Exe": f'"{executable}"', "appid": -1}

    with pytest.raises(ShortcutConflict, match="Old Name"):
        plan_shortcut_addition({"shortcuts": {"0": existing}}, _request(executable))


def test_new_shortcut_uses_next_highest_numeric_index(tmp_path: Path) -> None:
    executable = tmp_path / "game.exe"
    executable.touch()

    plan = plan_shortcut_addition(
        {"shortcuts": {"0": {}, "10": {}, "not-numeric": {}}},
        _request(executable),
    )

    assert plan.index == "11"
