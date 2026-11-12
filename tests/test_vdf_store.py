from pathlib import Path

import pytest

from steam_shortcuts.errors import InvalidShortcutFile
from steam_shortcuts.vdf_store import load_shortcuts, serialize_shortcuts

# A minimal, static binary-VDF fixture for one shortcut. The appid is stored as
# a signed int32 because ValvePython's binary VDF codec uses signed int32 fields.
EXISTING_SHORTCUT_VDF = bytes.fromhex(
    "0073686f727463757473000030000261707069640000286bee014170704e616d6500"
    "47616d650000746167730008080808"
)


def test_missing_shortcuts_file_loads_as_empty_without_creating_it(tmp_path: Path) -> None:
    shortcuts_path = tmp_path / "config" / "shortcuts.vdf"

    assert load_shortcuts(shortcuts_path) == {"shortcuts": {}}
    assert not shortcuts_path.exists()


def test_valid_binary_vdf_round_trips_existing_shortcut_fields(tmp_path: Path) -> None:
    shortcuts_path = tmp_path / "shortcuts.vdf"
    shortcuts_path.write_bytes(EXISTING_SHORTCUT_VDF)

    loaded = load_shortcuts(shortcuts_path)
    encoded = serialize_shortcuts(loaded)

    assert loaded["shortcuts"]["0"]["AppName"] == "Game"
    assert loaded["shortcuts"]["0"]["appid"] == -294_967_296
    shortcuts_path.write_bytes(encoded)
    assert load_shortcuts(shortcuts_path) == loaded


def test_malformed_binary_vdf_is_rejected_without_changing_file(tmp_path: Path) -> None:
    shortcuts_path = tmp_path / "shortcuts.vdf"
    malformed = b"\x00shortcuts\x00\x00"
    shortcuts_path.write_bytes(malformed)

    with pytest.raises(InvalidShortcutFile):
        load_shortcuts(shortcuts_path)

    assert shortcuts_path.read_bytes() == malformed


def test_serialization_rejects_nul_in_strings() -> None:
    with pytest.raises(ValueError, match="must not contain NUL"):
        serialize_shortcuts({"shortcuts": {"0": {"AppName": "bad\x00name"}}})


def test_serialization_rejects_values_outside_signed_int32_range() -> None:
    with pytest.raises(ValueError, match="signed 32-bit"):
        serialize_shortcuts({"shortcuts": {"0": {"appid": 2**31}}})
