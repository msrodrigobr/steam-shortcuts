from __future__ import annotations

from pathlib import Path

from steam_shortcuts import api
from steam_shortcuts.models import SteamGridDbArtwork
from steam_shortcuts.service import to_signed_int32
from steam_shortcuts.vdf_store import serialize_shortcuts


class _Client:
    artwork = SteamGridDbArtwork(
        game_id=42,
        portrait_url="https://cdn.example/portrait.jpg",
        hero_url="https://cdn.example/hero.jpg",
        logo_url="https://cdn.example/logo.png",
    )

    def get_artwork(self, game_id: int) -> SteamGridDbArtwork:
        assert game_id == 42
        return self.artwork

    def download_asset(self, url: str) -> bytes:
        return f"bytes:{url}".encode()


def _steam_root_with_shortcut(tmp_path: Path, shortcut_id: int) -> Path:
    steam_root = tmp_path / "Steam"
    shortcuts_path = steam_root / "userdata" / "123" / "config" / "shortcuts.vdf"
    shortcuts_path.parent.mkdir(parents=True)
    shortcuts_path.write_bytes(
        serialize_shortcuts(
            {
                "shortcuts": {
                    "0": {
                        "appid": to_signed_int32(shortcut_id),
                        "AppName": "Decktamer",
                        "Exe": '"/games/Decktamer.exe"',
                    }
                }
            }
        )
    )
    return steam_root


def test_preview_steamgriddb_artwork_verifies_shortcut_and_reports_target_paths(
    tmp_path: Path,
) -> None:
    steam_root = _steam_root_with_shortcut(tmp_path, 42)

    preview = api.preview_steamgriddb_artwork(
        steamgriddb_game_id=42,
        shortcut_id=42,
        steam_root=steam_root,
        client=_Client(),
    )

    assert preview.profile.profile_id == "123"
    assert preview.artwork.game_id == 42
    assert preview.conflicting_paths == ()
    assert preview.portrait_path.name == "42p.jpg"
    assert preview.hero_path.name == "42_hero.jpg"
    assert preview.logo_path.name == "42_logo.png"


def test_install_steamgriddb_artwork_writes_selected_assets_for_verified_shortcut(
    tmp_path: Path,
) -> None:
    steam_root = _steam_root_with_shortcut(tmp_path, 42)

    result = api.install_steamgriddb_artwork(
        steamgriddb_game_id=42,
        shortcut_id=42,
        steam_root=steam_root,
        client=_Client(),
    )

    assert result.portrait_path.read_bytes() == b"bytes:https://cdn.example/portrait.jpg"
    assert result.hero_path.read_bytes() == b"bytes:https://cdn.example/hero.jpg"
    assert result.logo_path.read_bytes() == b"bytes:https://cdn.example/logo.png"
