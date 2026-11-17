from __future__ import annotations

from pathlib import Path

import pytest

from steam_shortcuts.artwork import install_artwork
from steam_shortcuts.errors import ArtworkAlreadyExists
from steam_shortcuts.models import SteamGridDbArtwork
from steam_shortcuts.service import shortcut_artwork_id


@pytest.fixture
def selected_artwork() -> SteamGridDbArtwork:
    return SteamGridDbArtwork(
        game_id=42,
        portrait_url="https://cdn.example/portrait.jpg",
        hero_url="https://cdn.example/hero.jpg",
        logo_url="https://cdn.example/logo.png",
    )


def test_install_artwork_downloads_and_writes_all_steam_grid_images_atomically(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    shortcut_id = 3_516_482_161
    artwork_id = shortcut_artwork_id(shortcut_id)
    payloads = {
        selected_artwork.portrait_url: b"portrait-bytes",
        selected_artwork.hero_url: b"hero-bytes",
        selected_artwork.logo_url: b"logo-bytes",
    }

    result = install_artwork(
        grid_dir=tmp_path / "grid",
        shortcut_id=shortcut_id,
        artwork=selected_artwork,
        downloader=payloads.__getitem__,
    )

    assert result.artwork_id == artwork_id
    assert result.backup_paths == ()
    assert result.portrait_path == tmp_path / "grid" / f"{artwork_id}p.jpg"
    assert result.hero_path == tmp_path / "grid" / f"{artwork_id}_hero.jpg"
    assert result.logo_path == tmp_path / "grid" / f"{artwork_id}_logo.png"
    assert result.portrait_path.read_bytes() == b"portrait-bytes"
    assert result.hero_path.read_bytes() == b"hero-bytes"
    assert result.logo_path.read_bytes() == b"logo-bytes"


def test_install_artwork_refuses_to_replace_existing_images_without_overwrite(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_artwork_id(42)
    existing_portrait = grid_dir / f"{artwork_id}p.jpg"
    existing_portrait.write_bytes(b"existing-art")

    with pytest.raises(ArtworkAlreadyExists, match="existing artwork"):
        install_artwork(
            grid_dir=grid_dir,
            shortcut_id=42,
            artwork=selected_artwork,
            downloader=lambda _: b"new-art",
        )

    assert existing_portrait.read_bytes() == b"existing-art"


def test_install_artwork_overwrite_keeps_a_backup_of_replaced_images(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_artwork_id(42)
    existing_portrait = grid_dir / f"{artwork_id}p.jpg"
    existing_portrait.write_bytes(b"existing-art")

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
        overwrite=True,
    )

    assert result.portrait_path.read_bytes() == selected_artwork.portrait_url.encode()
    assert len(result.backup_paths) == 1
    assert result.backup_paths[0].read_bytes() == b"existing-art"
