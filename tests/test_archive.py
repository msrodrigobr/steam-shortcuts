from __future__ import annotations

import io
import tarfile
from pathlib import Path, PurePosixPath

import pytest

from steam_shortcuts.archive import extract_archive, inspect_archive
from steam_shortcuts.errors import ArchiveExecutableSelectionRequired, InvalidArchive


def _write_tar(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path


def _write_symlink_tar(path: Path) -> Path:
    with tarfile.open(path, "w") as archive:
        link = tarfile.TarInfo("Game/link.exe")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside.exe"
        archive.addfile(link)
    return path


def test_inspect_archive_automatically_uses_the_only_noninstaller_executable(
    tmp_path: Path,
) -> None:
    archive = _write_tar(
        tmp_path / "My Game.tar",
        {"My Game/setup.exe": b"installer", "My Game/Game.EXE": b"game"},
    )

    inspection = inspect_archive(archive, extract_to=tmp_path / "Games" / "My Game")

    assert inspection.executable_relative == PurePosixPath("My Game/Game.EXE")
    assert inspection.archive_root == PurePosixPath("My Game")
    assert inspection.selection == "single_candidate"
    assert inspection.executable == tmp_path / "Games" / "My Game" / "Game.EXE"
    assert inspection.executable_candidates == (
        PurePosixPath("My Game/Game.EXE"),
        PurePosixPath("My Game/setup.exe"),
    )


def test_inspect_archive_honors_an_explicit_relative_executable(tmp_path: Path) -> None:
    archive = _write_tar(
        tmp_path / "My Game.tar",
        {"My Game/Game.exe": b"game", "My Game/bin/Launcher.exe": b"launcher"},
    )

    inspection = inspect_archive(
        archive,
        extract_to=tmp_path / "Games" / "My Game",
        executable_relative=PurePosixPath("My Game/bin/Launcher.exe"),
    )

    assert inspection.executable_relative == PurePosixPath("My Game/bin/Launcher.exe")
    assert inspection.selection == "explicit"


def test_inspect_archive_preserves_paths_when_a_regular_file_is_at_archive_root(
    tmp_path: Path,
) -> None:
    archive = _write_tar(
        tmp_path / "My Game.tar",
        {"README.txt": b"read me", "My Game/Game.exe": b"game"},
    )

    inspection = inspect_archive(archive, extract_to=tmp_path / "Games" / "My Game")

    assert inspection.archive_root is None
    assert inspection.executable == tmp_path / "Games" / "My Game" / "My Game" / "Game.exe"


def test_inspect_archive_requires_explicit_choice_for_two_game_executables(tmp_path: Path) -> None:
    archive = _write_tar(
        tmp_path / "game.tar",
        {"Game/Game.exe": b"game", "Game/Launcher.exe": b"launcher"},
    )

    with pytest.raises(ArchiveExecutableSelectionRequired, match="--exe-relative") as raised:
        inspect_archive(archive, extract_to=tmp_path / "out")

    assert raised.value.candidates == (
        PurePosixPath("Game/Game.exe"),
        PurePosixPath("Game/Launcher.exe"),
    )


def test_inspect_archive_rejects_parent_directory_member(tmp_path: Path) -> None:
    archive = _write_tar(tmp_path / "unsafe.tar", {"../outside.exe": b"nope"})

    with pytest.raises(InvalidArchive, match="unsafe member path"):
        inspect_archive(archive, extract_to=tmp_path / "out")


def test_inspect_archive_rejects_symbolic_link_members(tmp_path: Path) -> None:
    archive = _write_symlink_tar(tmp_path / "unsafe-link.tar")

    with pytest.raises(InvalidArchive, match="unsupported member type"):
        inspect_archive(archive, extract_to=tmp_path / "out")


def test_inspect_archive_requires_explicit_setup_executable_choice(tmp_path: Path) -> None:
    archive = _write_tar(tmp_path / "setup-only.tar", {"Game/setup.exe": b"installer"})

    with pytest.raises(ArchiveExecutableSelectionRequired) as raised:
        inspect_archive(archive, extract_to=tmp_path / "out")

    assert raised.value.candidates == (PurePosixPath("Game/setup.exe"),)


def test_extract_archive_promotes_a_complete_staging_directory(tmp_path: Path) -> None:
    archive = _write_tar(
        tmp_path / "game.tar",
        {"Game/Game.exe": b"game", "Game/data.pak": b"data"},
    )
    inspection = inspect_archive(archive, extract_to=tmp_path / "Games" / "Game")
    inspection.extract_to.parent.mkdir()

    executable = extract_archive(inspection)

    assert executable == tmp_path / "Games" / "Game" / "Game.exe"
    assert executable.read_bytes() == b"game"
    assert (executable.parent / "data.pak").read_bytes() == b"data"


def test_extract_archive_refuses_to_overwrite_a_destination(tmp_path: Path) -> None:
    archive = _write_tar(tmp_path / "game.tar", {"Game/Game.exe": b"game"})
    destination = tmp_path / "Games" / "Game"
    destination.mkdir(parents=True)
    (destination / "keep.txt").write_text("keep")
    inspection = inspect_archive(archive, extract_to=destination)

    with pytest.raises(InvalidArchive, match="destination already exists"):
        extract_archive(inspection)

    assert (destination / "keep.txt").read_text() == "keep"


def test_extract_archive_cleans_its_staging_directory_after_a_read_failure(tmp_path: Path) -> None:
    archive = _write_tar(tmp_path / "game.tar", {"Game/Game.exe": b"game"})
    destination = tmp_path / "Games" / "Game"
    destination.parent.mkdir()
    inspection = inspect_archive(archive, extract_to=destination)
    archive.unlink()

    with pytest.raises(InvalidArchive, match="archive could not be extracted"):
        extract_archive(inspection)

    assert not destination.exists()
    assert not list(destination.parent.glob(".Game.steam-shortcuts-*"))
