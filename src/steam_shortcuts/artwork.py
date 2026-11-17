"""Safe local installation of selected artwork into Steam's grid directory."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import ArtworkAlreadyExists, ArtworkWriteFailed
from .models import ArtworkInstallResult, SteamGridDbArtwork
from .service import shortcut_artwork_id

Download = Callable[[str], bytes]


def install_artwork(
    *,
    grid_dir: Path,
    shortcut_id: int,
    artwork: SteamGridDbArtwork,
    downloader: Download,
    overwrite: bool = False,
) -> ArtworkInstallResult:
    """Download and atomically install selected art for one existing shortcut.

    Existing artwork is never overwritten unless ``overwrite`` is explicitly
    enabled. Any replaced files are copied to unique sibling backups first.
    """
    normalized_grid_dir = grid_dir.expanduser().resolve(strict=False)
    _validate_grid_dir(normalized_grid_dir)
    artwork_id = shortcut_artwork_id(shortcut_id)
    targets = _targets(normalized_grid_dir, artwork_id, artwork)
    existing_paths = tuple(path for path, _ in targets if path.exists() or path.is_symlink())
    if existing_paths and not overwrite:
        raise ArtworkAlreadyExists(existing_paths)
    if any(path.is_symlink() for path in existing_paths):
        raise ArtworkWriteFailed(normalized_grid_dir, "refusing to replace symbolic-link artwork")

    contents = tuple((path, _download(url, downloader)) for path, url in targets)
    normalized_grid_dir.mkdir(parents=True, exist_ok=True)
    backup_paths = _replace_files(contents, existing_paths)
    portrait_path, hero_path, logo_path = (path for path, _ in targets)
    return ArtworkInstallResult(
        shortcut_id=shortcut_id,
        artwork_id=artwork_id,
        grid_dir=normalized_grid_dir,
        portrait_path=portrait_path,
        hero_path=hero_path,
        logo_path=logo_path,
        backup_paths=backup_paths,
    )


def _targets(
    grid_dir: Path,
    artwork_id: int,
    artwork: SteamGridDbArtwork,
) -> tuple[tuple[Path, str], tuple[Path, str], tuple[Path, str]]:
    return (
        (grid_dir / f"{artwork_id}p.jpg", artwork.portrait_url),
        (grid_dir / f"{artwork_id}_hero.jpg", artwork.hero_url),
        (grid_dir / f"{artwork_id}_logo.png", artwork.logo_url),
    )


def _download(url: str, downloader: Download) -> bytes:
    content = downloader(url)
    if not isinstance(content, bytes) or not content:
        raise ValueError(f"Artwork download was empty or non-binary: {url}")
    return content


def _replace_files(
    contents: tuple[tuple[Path, bytes], ...],
    existing_paths: tuple[Path, ...],
) -> tuple[Path, ...]:
    temporary_paths: dict[Path, Path] = {}
    backup_paths: dict[Path, Path] = {}
    replaced_paths: list[Path] = []
    try:
        for target, content in contents:
            temporary_path = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            _write_temporary_file(temporary_path, content)
            temporary_paths[target] = temporary_path
        for target in existing_paths:
            backup_path = _next_backup_path(target)
            shutil.copy2(target, backup_path)
            backup_paths[target] = backup_path
        for target, _ in contents:
            os.replace(temporary_paths[target], target)
            replaced_paths.append(target)
        _fsync_directory(contents[0][0].parent)
    except BaseException:
        _restore_replaced_files(replaced_paths, backup_paths)
        raise
    finally:
        for temporary_path in temporary_paths.values():
            temporary_path.unlink(missing_ok=True)
    return tuple(backup_paths[target] for target in existing_paths)


def _validate_grid_dir(grid_dir: Path) -> None:
    if grid_dir.is_symlink():
        raise ArtworkWriteFailed(grid_dir, "grid directory must not be a symbolic link")
    if grid_dir.exists() and not grid_dir.is_dir():
        raise ArtworkWriteFailed(grid_dir, "grid path exists but is not a directory")


def _write_temporary_file(path: Path, content: bytes) -> None:
    with path.open("xb") as temporary_file:
        temporary_file.write(content)
        temporary_file.flush()
        os.fsync(temporary_file.fileno())


def _next_backup_path(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.bak.{timestamp}")
    sequence = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{path.name}.bak.{timestamp}-{sequence}")
        sequence += 1
    return candidate


def _restore_replaced_files(replaced_paths: list[Path], backup_paths: dict[Path, Path]) -> None:
    for target in reversed(replaced_paths):
        backup_path = backup_paths.get(target)
        if backup_path is None:
            target.unlink(missing_ok=True)
        else:
            shutil.copy2(backup_path, target)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
