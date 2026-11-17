from __future__ import annotations

from pathlib import Path

import pytest

from steam_shortcuts.errors import InvalidExecutable
from steam_shortcuts.executable_metadata import read_executable_metadata


class _StringTable:
    def __init__(self, entries: dict[bytes, bytes]) -> None:
        self.entries = entries


class _FileInfo:
    Key = b"StringFileInfo"

    def __init__(self, entries: dict[bytes, bytes]) -> None:
        self.StringTable = [_StringTable(entries)]


class _Pe:
    def __init__(self, entries: dict[bytes, bytes]) -> None:
        self.FileInfo = [[_FileInfo(entries)]]
        self.parsed_directories = False
        self.closed = False

    def parse_data_directories(self, *, directories: object) -> None:
        assert directories
        self.parsed_directories = True

    def close(self) -> None:
        self.closed = True


def test_read_executable_metadata_prefers_product_name_and_deduplicates_titles(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "Decktamer.exe"
    executable.touch()
    fake_pe = _Pe(
        {
            b"ProductName": b"Decktamer",
            b"FileDescription": b"Decktamer",
            b"OriginalFilename": b"Decktamer.exe",
            b"CompanyName": b"Horizon Edge",
            b"InternalName": b"Decktamer",
            b"ProductVersion": b"1.0.0",
        }
    )

    metadata = read_executable_metadata(executable, pe_loader=lambda _: fake_pe)

    assert fake_pe.parsed_directories is True
    assert fake_pe.closed is True
    assert metadata.product_name == "Decktamer"
    assert metadata.file_description == "Decktamer"
    assert metadata.original_filename == "Decktamer.exe"
    assert metadata.company_name == "Horizon Edge"
    assert metadata.product_version == "1.0.0"
    assert [(candidate.value, candidate.source) for candidate in metadata.title_candidates] == [
        ("Decktamer", "product_name"),
    ]


def test_read_executable_metadata_falls_back_to_executable_stem(tmp_path: Path) -> None:
    executable = tmp_path / "My Game.exe"
    executable.touch()

    metadata = read_executable_metadata(executable, pe_loader=lambda _: _Pe({}))

    assert metadata.product_name is None
    assert [(candidate.value, candidate.source) for candidate in metadata.title_candidates] == [
        ("My Game", "executable_stem"),
    ]


def test_read_executable_metadata_rejects_a_missing_executable(tmp_path: Path) -> None:
    with pytest.raises(InvalidExecutable, match="path does not exist"):
        read_executable_metadata(tmp_path / "missing.exe")
