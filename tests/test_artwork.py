from __future__ import annotations

from pathlib import Path

import pytest

import steam_shortcuts.artwork as artwork_module
from steam_shortcuts.artwork import install_artwork
from steam_shortcuts.errors import ArtworkWriteFailed, SteamStoreRequestFailed
from steam_shortcuts.models import SteamGridDbArtwork, SteamLibraryArtwork
from steam_shortcuts.service import shortcut_grid_artwork_id


@pytest.fixture
def selected_artwork() -> SteamGridDbArtwork:
    return SteamGridDbArtwork(
        game_id=42,
        portrait_url="https://cdn.example/portrait.jpg",
        hero_url="https://cdn.example/hero.jpg",
        logo_url="https://cdn.example/logo.png",
    )


def test_install_artwork_downloads_and_writes_all_steam_grid_images(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    shortcut_id = 3_516_482_161
    artwork_id = shortcut_id
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


def test_install_artwork_refuses_a_symlinked_grid_directory(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    real_grid = tmp_path / "real-grid"
    real_grid.mkdir()
    grid_link = tmp_path / "grid"
    try:
        grid_link.symlink_to(real_grid, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink creation is unavailable: {error}")

    with pytest.raises(ArtworkWriteFailed, match="grid directory must not be a symbolic link"):
        install_artwork(
            grid_dir=grid_link,
            shortcut_id=42,
            artwork=selected_artwork,
            downloader=lambda _: b"artwork",
        )

    assert not tuple(real_grid.iterdir())


def test_install_artwork_does_not_follow_grid_directory_replaced_before_temp_write(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork, monkeypatch
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    moved_grid_dir = tmp_path / "original-grid"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    original_write = artwork_module._write_temporary_file
    swapped = False

    def swap_then_write(
        path: Path,
        content: bytes,
        directory_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if not swapped:
            grid_dir.rename(moved_grid_dir)
            try:
                grid_dir.symlink_to(outside_dir, target_is_directory=True)
            except OSError as error:
                pytest.skip(f"directory symlink creation is unavailable: {error}")
            swapped = True
        original_write(path, content, directory_fd)

    monkeypatch.setattr(artwork_module, "_write_temporary_file", swap_then_write)

    install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
    )

    assert not tuple(outside_dir.iterdir())


def test_install_artwork_keeps_existing_slot_and_installs_missing_images(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_grid_artwork_id(42)
    existing_portrait = grid_dir / f"{artwork_id}p.png"
    existing_portrait.write_bytes(b"existing-art")

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
    )

    assert result.portrait_path is None
    assert existing_portrait.read_bytes() == b"existing-art"
    assert not (grid_dir / f"{artwork_id}p.jpg").exists()
    assert result.hero_path is not None
    assert result.hero_path.read_bytes() == selected_artwork.hero_url.encode()
    assert result.logo_path is not None
    assert result.logo_path.read_bytes() == selected_artwork.logo_url.encode()
    assert result.conflicting_paths == (existing_portrait,)


@pytest.mark.parametrize(
    ("stem", "existing_extension", "new_extension", "kind"),
    (("_hero", ".png", ".jpg", "hero"), ("_logo", ".jpg", ".png", "logo")),
)
def test_install_artwork_detects_alternate_extensions_for_each_slot(
    tmp_path: Path,
    selected_artwork: SteamGridDbArtwork,
    stem: str,
    existing_extension: str,
    new_extension: str,
    kind: str,
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_grid_artwork_id(42)
    existing = grid_dir / f"{artwork_id}{stem}{existing_extension}"
    existing.write_bytes(b"existing-art")

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
    )

    assert result.conflicting_paths == (existing,)
    assert existing.read_bytes() == b"existing-art"
    assert not (grid_dir / f"{artwork_id}{stem}{new_extension}").exists()
    assert getattr(result, f"{kind}_path") is None


def test_install_artwork_does_not_clobber_file_created_during_download(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    hero_path = grid_dir / f"{shortcut_grid_artwork_id(42)}_hero.jpg"

    def download(url: str) -> bytes:
        if url == selected_artwork.hero_url:
            hero_path.write_bytes(b"created-concurrently")
        return url.encode()

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=download,
    )

    assert hero_path.read_bytes() == b"created-concurrently"
    assert result.hero_path is None
    assert result.portrait_path is not None and result.portrait_path.is_file()
    assert result.logo_path is not None and result.logo_path.is_file()
    assert result.conflicting_paths == (hero_path,)


def test_install_artwork_detects_alternate_extension_created_during_download(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_grid_artwork_id(42)
    concurrent_portrait = grid_dir / f"{artwork_id}p.png"

    def download(url: str) -> bytes:
        if url == selected_artwork.portrait_url:
            concurrent_portrait.write_bytes(b"concurrent-png")
        return url.encode()

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=download,
    )

    assert concurrent_portrait.read_bytes() == b"concurrent-png"
    assert not (grid_dir / f"{artwork_id}p.jpg").exists()
    assert result.conflicting_paths == (concurrent_portrait,)


def test_overwrite_preserves_file_changed_after_initial_identity_check(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork, monkeypatch
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    portrait = grid_dir / f"{shortcut_grid_artwork_id(42)}p.jpg"
    portrait.write_bytes(b"original portrait")
    original_move = artwork_module._rename_entry_no_clobber
    injected = False

    def concurrent_change(source, destination, directory_fd):
        nonlocal injected
        if source == portrait and ".bak." in destination.name and not injected:
            portrait.write_bytes(b"concurrent writer contents")
            injected = True
        return original_move(source, destination, directory_fd)

    monkeypatch.setattr(artwork_module, "_rename_entry_no_clobber", concurrent_change)

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
        overwrite=True,
    )

    assert portrait.read_bytes() == b"concurrent writer contents"
    assert result.portrait_path is None
    assert result.conflicting_paths == (portrait,)


def test_install_artwork_overwrite_backs_up_file_created_during_download(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_grid_artwork_id(42)
    target = grid_dir / f"{artwork_id}p.jpg"

    def download(url: str) -> bytes:
        if url == selected_artwork.portrait_url:
            target.write_bytes(b"concurrent-original")
        return url.encode()

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=download,
        overwrite=True,
    )

    assert result.portrait_path is not None
    assert result.portrait_path.read_bytes() == selected_artwork.portrait_url.encode()
    assert any(path.read_bytes() == b"concurrent-original" for path in result.backup_paths)


def test_install_artwork_rejects_content_that_disagrees_with_the_previewed_extension(
    tmp_path: Path,
) -> None:
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://cdn.example/portrait.jpg",
        hero_url="https://cdn.example/hero.jpg",
        logo_url="https://cdn.example/logo.png",
    )

    with pytest.raises(SteamStoreRequestFailed, match="does not match the URL format"):
        install_artwork(
            grid_dir=tmp_path / "grid",
            shortcut_id=42,
            artwork=artwork,
            downloader=lambda _: b"\x89PNG\r\n\x1a\nimage",
        )


def test_install_artwork_falls_back_when_filesystem_does_not_support_hardlinks(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork, monkeypatch
) -> None:
    def no_hardlinks(*_args, **_kwargs) -> None:
        raise OSError(95, "hard links are unsupported")

    monkeypatch.setattr(artwork_module.os, "link", no_hardlinks)

    result = install_artwork(
        grid_dir=tmp_path / "grid",
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
    )

    assert result.portrait_path is not None and result.portrait_path.is_file()
    assert result.hero_path is not None and result.hero_path.is_file()
    assert result.logo_path is not None and result.logo_path.is_file()


def test_hardlink_fallback_uses_atomic_no_clobber_publication(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork, monkeypatch
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    observed_final_paths: list[tuple[Path, ...]] = []
    original_move = artwork_module._rename_entry_no_clobber

    def no_hardlinks(*_args, **_kwargs) -> None:
        raise OSError(95, "hard links are unsupported")

    def observe_publication(source: Path, target: Path, directory_fd: int | None) -> None:
        if target.name.startswith("42"):
            observed_final_paths.append(tuple(grid_dir.glob(target.name)))
            assert source.is_file() and source.stat().st_size > 0
        original_move(source, target, directory_fd)

    monkeypatch.setattr(artwork_module.os, "link", no_hardlinks)
    monkeypatch.setattr(artwork_module, "_rename_entry_no_clobber", observe_publication)

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
    )

    assert len(observed_final_paths) == 3
    assert all(not paths for paths in observed_final_paths)
    assert result.portrait_path is not None and result.portrait_path.is_file()


def test_install_artwork_does_not_follow_symlink_created_during_download(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_grid_artwork_id(42)
    portrait = grid_dir / f"{artwork_id}p.jpg"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"must remain untouched")

    def download(url: str) -> bytes:
        if url == selected_artwork.portrait_url:
            try:
                portrait.symlink_to(outside)
            except OSError as error:
                pytest.skip(f"file symlink creation is unavailable: {error}")
        return url.encode()

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=download,
        overwrite=True,
    )

    assert outside.read_bytes() == b"must remain untouched"
    assert portrait.is_symlink()
    assert result.conflicting_paths == (portrait,)
    assert result.hero_path is not None and result.hero_path.is_file()
    assert result.logo_path is not None and result.logo_path.is_file()


def test_install_artwork_backup_does_not_read_through_a_racing_symlink(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork, monkeypatch
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    portrait = grid_dir / f"{shortcut_grid_artwork_id(42)}p.jpg"
    portrait.write_bytes(b"expected original")
    outside = tmp_path / "private.txt"
    outside.write_bytes(b"private file contents")
    original_move = artwork_module._rename_entry_no_clobber
    swapped = False

    def replace_before_backup(
        source: Path,
        target: Path,
        directory_fd: int | None,
    ) -> None:
        nonlocal swapped
        if source == portrait and ".bak." in target.name and not swapped:
            portrait.unlink()
            try:
                portrait.symlink_to(outside)
            except OSError as error:
                pytest.skip(f"file symlink creation is unavailable: {error}")
            swapped = True
        original_move(source, target, directory_fd)

    monkeypatch.setattr(artwork_module, "_rename_entry_no_clobber", replace_before_backup)

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
        overwrite=True,
    )

    assert outside.read_bytes() == b"private file contents"
    assert portrait.is_symlink()
    assert all(b"private file contents" not in path.read_bytes() for path in result.backup_paths)


def test_install_artwork_preserves_other_writers_files_after_link_races(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork, monkeypatch
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_grid_artwork_id(42)
    portrait = grid_dir / f"{artwork_id}p.jpg"
    hero = grid_dir / f"{artwork_id}_hero.jpg"
    original_link = artwork_module.os.link
    link_count = 0

    def race_link(source, target, *args, **kwargs):
        nonlocal link_count
        link_count += 1
        target_path = Path(target)
        if not target_path.is_absolute():
            target_path = grid_dir / target_path
        if link_count == 1:
            original_link(source, target, *args, **kwargs)
            target_path.unlink()
            target_path.write_bytes(b"another writer's portrait")
            return
        if link_count == 2:
            target_path.write_bytes(b"another writer's hero")
        return original_link(source, target, *args, **kwargs)

    monkeypatch.setattr(artwork_module.os, "link", race_link)

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
    )

    assert portrait.read_bytes() == b"another writer's portrait"
    assert hero.read_bytes() == b"another writer's hero"
    assert result.conflicting_paths == (portrait, hero)
    assert result.logo_path is not None and result.logo_path.is_file()


def test_install_artwork_overwrite_preserves_alternate_extension_variant(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_grid_artwork_id(42)
    existing_portrait = grid_dir / f"{artwork_id}p.png"
    existing_portrait.write_bytes(b"existing-art")

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
        overwrite=True,
    )

    assert existing_portrait.read_bytes() == b"existing-art"
    assert result.portrait_path is not None
    assert result.portrait_path.read_bytes() == selected_artwork.portrait_url.encode()
    assert result.conflicting_paths == (existing_portrait,)
    assert result.backup_paths == ()


def test_overwrite_rejects_fifo_artwork_without_blocking(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    make_fifo = getattr(artwork_module.os, "mkfifo", None)
    if make_fifo is None:
        pytest.skip("named pipes are not supported on this platform")
    assert callable(make_fifo)
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    fifo = grid_dir / f"{shortcut_grid_artwork_id(42)}p.jpg"
    make_fifo(fifo)

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
        overwrite=True,
    )

    assert fifo.is_fifo()
    assert fifo in result.failed_paths
    assert result.portrait_path is None
    assert result.hero_path is not None and result.hero_path.is_file()
    assert result.logo_path is not None and result.logo_path.is_file()


def test_late_alternate_extension_conflict_does_not_delete_new_install(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork, monkeypatch
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_grid_artwork_id(42)
    target = grid_dir / f"{artwork_id}p.jpg"
    alternate = grid_dir / f"{artwork_id}p.png"
    target.write_bytes(b"original")
    original_existing = artwork_module._existing_slot_paths
    portrait_checks = 0

    def create_late_alternate(
        path: Path,
        directory_fd: int | None = None,
    ) -> tuple[Path, ...]:
        nonlocal portrait_checks
        existing = original_existing(path, directory_fd)
        if path.name == target.name:
            portrait_checks += 1
            if portrait_checks == 3:
                alternate.write_bytes(b"concurrent alternate artwork")
                existing = original_existing(path, directory_fd)
        return existing

    monkeypatch.setattr(artwork_module, "_existing_slot_paths", create_late_alternate)

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
        overwrite=True,
    )

    assert target.read_bytes() == selected_artwork.portrait_url.encode()
    assert alternate.read_bytes() == b"concurrent alternate artwork"
    assert result.portrait_path == target
    assert result.conflicting_paths == (alternate,)


def test_install_artwork_overwrite_keeps_a_backup_of_replaced_images(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    artwork_id = shortcut_grid_artwork_id(42)
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


@pytest.mark.parametrize("path_mode", ("anchored", "path-fallback", "windows-like"))
def test_failed_publication_restores_file_without_consuming_backup(
    tmp_path: Path,
    selected_artwork: SteamGridDbArtwork,
    monkeypatch,
    path_mode: str,
) -> None:
    if path_mode == "path-fallback":
        monkeypatch.setattr(artwork_module, "_open_grid_directory", lambda _: None)
    elif path_mode == "windows-like":
        monkeypatch.setattr(artwork_module, "_open_grid_directory", lambda _: None)
        original_move = artwork_module._rename_entry_no_clobber

        def windows_style_move(source: Path, target: Path, directory_fd: int | None) -> None:
            if directory_fd is None:
                if target.exists():
                    raise FileExistsError(target)
                artwork_module.os.rename(source, target)
            else:
                original_move(source, target, directory_fd)

        monkeypatch.setattr(artwork_module, "_rename_entry_no_clobber", windows_style_move)
        monkeypatch.setattr(
            artwork_module.os,
            "link",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(95, "no hard links")),
        )
    grid_dir = tmp_path / "grid"
    grid_dir.mkdir()
    portrait = grid_dir / f"{shortcut_grid_artwork_id(42)}p.jpg"
    portrait.write_bytes(b"original portrait")
    original_publish = artwork_module._publish_no_clobber
    injected = False

    def fail_once(temporary: Path, target: Path, directory_fd: int | None):
        nonlocal injected
        if target == portrait and not injected:
            injected = True
            raise OSError("injected publish error")
        return original_publish(temporary, target, directory_fd)

    monkeypatch.setattr(artwork_module, "_publish_no_clobber", fail_once)

    result = install_artwork(
        grid_dir=grid_dir,
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
        overwrite=True,
    )

    assert portrait.exists(), f"restore warning: {result.warning}; backups={result.backup_paths}"
    assert portrait.read_bytes() == b"original portrait"
    assert result.failed_paths == (portrait,)
    assert len(result.backup_paths) == 1
    backup = result.backup_paths[0]
    assert backup.read_bytes() == b"original portrait"
    portrait.write_bytes(b"later edit to restored artwork")
    assert backup.read_bytes() == b"original portrait"


def test_install_artwork_can_keep_available_images_when_optional_steam_logo_is_missing(
    tmp_path: Path,
) -> None:
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )

    def download(url: str) -> bytes:
        if url.endswith("logo.png"):
            raise SteamStoreRequestFailed("HTTP 404")
        return url.encode()

    result = install_artwork(
        grid_dir=tmp_path / "grid",
        shortcut_id=42,
        artwork=artwork,
        downloader=download,
        allow_missing_assets=True,
    )

    assert result.portrait_path is not None and result.portrait_path.is_file()
    assert result.hero_path is not None and result.hero_path.is_file()
    assert result.logo_path is None
    assert result.failed_paths == (tmp_path / "grid" / "42_logo.png",)


def test_install_artwork_reports_all_failed_optional_downloads_without_fabricated_paths(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork
) -> None:
    def failed_download(_url: str) -> bytes:
        raise SteamStoreRequestFailed("HTTP 503")

    result = install_artwork(
        grid_dir=tmp_path / "grid",
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=failed_download,
        allow_missing_assets=True,
    )

    assert result.portrait_path is None
    assert result.hero_path is None
    assert result.logo_path is None
    assert result.failed_paths == (
        tmp_path / "grid" / "42p.jpg",
        tmp_path / "grid" / "42_hero.jpg",
        tmp_path / "grid" / "42_logo.png",
    )
    assert "HTTP 503" in (result.warning or "")


def test_directory_sync_failure_does_not_report_same_path_as_installed_and_failed(
    tmp_path: Path, selected_artwork: SteamGridDbArtwork, monkeypatch
) -> None:
    monkeypatch.setattr(
        artwork_module,
        "_fsync_directory",
        lambda _: (_ for _ in ()).throw(OSError("injected directory sync error")),
    )

    result = install_artwork(
        grid_dir=tmp_path / "grid",
        shortcut_id=42,
        artwork=selected_artwork,
        downloader=lambda url: url.encode(),
    )

    assert result.portrait_path is not None and result.portrait_path.is_file()
    assert result.hero_path is not None and result.hero_path.is_file()
    assert result.logo_path is not None and result.logo_path.is_file()
    assert result.failed_paths == ()
