from datetime import UTC, datetime
from pathlib import Path

import pytest

from steam_shortcuts.models import ShortcutRequest
from steam_shortcuts.service import add_shortcut_to_profile
from steam_shortcuts.vdf_store import (
    load_shortcuts,
    serialize_shortcuts,
    write_shortcuts_atomically,
)


def _write_root(path: Path, root: dict[str, object]) -> bytes:
    data = serialize_shortcuts(root)  # type: ignore[arg-type]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def test_atomic_write_creates_timestamped_backup_and_replaces_content(tmp_path: Path) -> None:
    shortcuts_path = tmp_path / "config" / "shortcuts.vdf"
    original = _write_root(shortcuts_path, {"shortcuts": {}})
    replacement = {"shortcuts": {"0": {"appid": -1, "AppName": "Game"}}}

    backup = write_shortcuts_atomically(
        shortcuts_path,
        replacement,  # type: ignore[arg-type]
        now=datetime(2026, 11, 12, 2, 0, tzinfo=UTC),
    )

    assert backup == shortcuts_path.with_name("shortcuts.vdf.bak.20261112T020000Z")
    assert backup is not None
    assert backup.read_bytes() == original
    assert load_shortcuts(shortcuts_path) == replacement


def test_failed_atomic_replace_leaves_original_file_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shortcuts_path = tmp_path / "config" / "shortcuts.vdf"
    original = _write_root(shortcuts_path, {"shortcuts": {}})

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("disk is on fire")

    monkeypatch.setattr("steam_shortcuts.vdf_store.os.replace", fail_replace)

    with pytest.raises(OSError, match="disk is on fire"):
        write_shortcuts_atomically(
            shortcuts_path,
            {"shortcuts": {"0": {"appid": -1}}},  # type: ignore[arg-type]
            now=datetime(2026, 11, 12, 2, 0, tzinfo=UTC),
        )

    assert shortcuts_path.read_bytes() == original


def test_add_to_profile_writes_and_rereads_verified_shortcut(tmp_path: Path) -> None:
    executable = tmp_path / "game.exe"
    executable.touch()
    shortcuts_path = tmp_path / "config" / "shortcuts.vdf"
    _write_root(shortcuts_path, {"shortcuts": {}})

    result = add_shortcut_to_profile(
        shortcuts_path,
        profile_id="123",
        request=ShortcutRequest(name="My Game", executable=executable),
        now=datetime(2026, 11, 12, 2, 0, tzinfo=UTC),
    )

    assert result.status == "added"
    assert result.backup_path is not None
    saved = load_shortcuts(shortcuts_path)
    assert saved["shortcuts"]["0"]["AppName"] == "My Game"
    assert saved["shortcuts"]["0"]["Exe"] == f'"{executable}"'


def test_idempotent_add_does_not_create_another_backup(tmp_path: Path) -> None:
    executable = tmp_path / "game.exe"
    executable.touch()
    shortcuts_path = tmp_path / "config" / "shortcuts.vdf"
    _write_root(shortcuts_path, {"shortcuts": {}})
    request = ShortcutRequest(name="My Game", executable=executable)

    first = add_shortcut_to_profile(shortcuts_path, "123", request)
    content_after_first_add = shortcuts_path.read_bytes()
    second = add_shortcut_to_profile(shortcuts_path, "123", request)

    assert first.status == "added"
    assert second.status == "already_exists"
    assert second.backup_path is None
    assert shortcuts_path.read_bytes() == content_after_first_add
