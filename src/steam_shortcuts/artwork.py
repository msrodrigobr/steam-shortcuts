"""Safe local installation of selected artwork into Steam's grid directory."""

from __future__ import annotations

import contextlib
import ctypes
import errno
import os
import shutil
import stat
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from .errors import ArtworkAlreadyExists, ArtworkWriteFailed, SteamStoreRequestFailed
from .models import ArtworkInstallResult
from .service import shortcut_grid_artwork_id

Download = Callable[[str], bytes]
BeforeCommit = Callable[[], None]
_FileIdentity = tuple[int, int, int, int, int]
_SUPPORTED_ARTWORK_EXTENSIONS = (".jpg", ".jpeg", ".png")


@dataclass(frozen=True, slots=True)
class _CommitResult:
    installed_paths: tuple[Path, ...]
    backup_paths: tuple[Path, ...]
    conflicting_paths: tuple[Path, ...]
    failed_paths: tuple[Path, ...]
    warning: str | None


class ArtworkAssets(Protocol):
    """URLs for the optional library artwork assets."""

    @property
    def portrait_url(self) -> str | None: ...

    @property
    def hero_url(self) -> str | None: ...

    @property
    def logo_url(self) -> str | None: ...


def install_artwork(
    *,
    grid_dir: Path,
    shortcut_id: int,
    artwork: ArtworkAssets,
    downloader: Download,
    overwrite: bool = False,
    allow_missing_assets: bool = False,
    before_commit: BeforeCommit | None = None,
) -> ArtworkInstallResult:
    """Download and install art one library slot at a time.

    Existing slots are preserved independently unless ``overwrite`` is enabled.
    Each replacement is backed up first. Directory-relative operations keep the
    selected grid directory pinned on POSIX, and every final publication is
    atomic and no-clobber.
    """
    expanded_grid_dir = grid_dir.expanduser()
    _validate_grid_dir(expanded_grid_dir)
    normalized_grid_dir = expanded_grid_dir.resolve(strict=False)
    artwork_id = shortcut_grid_artwork_id(shortcut_id)
    targets = artwork_targets(normalized_grid_dir, artwork_id, artwork)
    if not targets:
        raise ArtworkWriteFailed(normalized_grid_dir, "no artwork assets were available")

    try:
        normalized_grid_dir.mkdir(parents=True, exist_ok=True)
        directory_fd = _open_grid_directory(normalized_grid_dir)
    except OSError as error:
        raise ArtworkWriteFailed(
            normalized_grid_dir,
            f"could not securely open grid directory: {error}",
        ) from error

    try:
        existing_by_stem = {
            path.with_suffix(""): _existing_slot_paths(path, directory_fd)
            for _, path, _ in targets
        }
        initial_conflicts = tuple(
            dict.fromkeys(path for paths in existing_by_stem.values() for path in paths)
        )
        if any(_is_symlink(path, directory_fd) for path in initial_conflicts):
            raise ArtworkWriteFailed(
                normalized_grid_dir,
                "refusing to replace symbolic-link artwork",
            )

        targets_to_install = (
            targets
            if overwrite
            else tuple(
                target
                for target in targets
                if not existing_by_stem[target[1].with_suffix("")]
            )
        )
        if not targets_to_install:
            raise ArtworkAlreadyExists(initial_conflicts)

        ready_assets: list[tuple[str, Path, bytes]] = []
        download_failures: list[Path] = []
        download_warnings: list[str] = []
        for kind, requested_path, url in targets_to_install:
            try:
                content = _download(url, downloader)
                target_path = _path_for_content(requested_path, url, content)
            except SteamStoreRequestFailed as error:
                if not allow_missing_assets:
                    raise
                download_failures.append(requested_path)
                download_warnings.append(f"Could not download {requested_path}: {error}")
                continue
            ready_assets.append((kind, target_path, content))

        if not ready_assets:
            if allow_missing_assets:
                return ArtworkInstallResult(
                    shortcut_id=shortcut_id,
                    artwork_id=artwork_id,
                    grid_dir=normalized_grid_dir,
                    portrait_path=None,
                    hero_path=None,
                    logo_path=None,
                    backup_paths=(),
                    conflicting_paths=initial_conflicts,
                    failed_paths=tuple(download_failures),
                    warning="; ".join(download_warnings) if download_warnings else None,
                )
            raise ArtworkWriteFailed(
                normalized_grid_dir,
                "all requested artwork assets were unavailable",
            )

        _validate_grid_dir(expanded_grid_dir)
        if before_commit is not None:
            before_commit()
        commit = _commit_files(
            tuple(ready_assets),
            overwrite=overwrite,
            directory_fd=directory_fd,
        )
        if not _grid_directory_matches(normalized_grid_dir, directory_fd):
            changed_paths = tuple(path for _, path, _ in ready_assets)
            commit = _CommitResult(
                installed_paths=(),
                backup_paths=(),
                conflicting_paths=(),
                failed_paths=tuple(dict.fromkeys((*commit.failed_paths, *changed_paths))),
                warning=(
                    f"{commit.warning}; grid directory changed during installation"
                    if commit.warning
                    else (
                        "Grid directory changed during installation; "
                        "installed paths may have moved"
                    )
                ),
            )

        installed_stems = {path.with_suffix("") for path in commit.installed_paths}
        preserved_initial = tuple(
            path
            for path in initial_conflicts
            if path.with_suffix("") not in installed_stems or path not in commit.installed_paths
        )
        conflicting_paths = tuple(
            dict.fromkeys((*preserved_initial, *commit.conflicting_paths))
        )
        paths_by_kind = {
            kind: path
            for kind, path, _ in ready_assets
            if path in commit.installed_paths
        }
        all_warnings = tuple(
            warning
            for warning in (*download_warnings, commit.warning)
            if warning
        )
        return ArtworkInstallResult(
            shortcut_id=shortcut_id,
            artwork_id=artwork_id,
            grid_dir=normalized_grid_dir,
            portrait_path=paths_by_kind.get("portrait"),
            hero_path=paths_by_kind.get("hero"),
            logo_path=paths_by_kind.get("logo"),
            backup_paths=commit.backup_paths,
            conflicting_paths=conflicting_paths,
            failed_paths=tuple(dict.fromkeys((*download_failures, *commit.failed_paths))),
            warning="; ".join(all_warnings) if all_warnings else None,
        )
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def find_existing_artwork_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Find existing files for the requested Steam slots across image formats."""
    return tuple(
        dict.fromkeys(
            existing
            for path in paths
            for existing in _existing_slot_paths(path)
        )
    )


def _existing_slot_paths(path: Path, directory_fd: int | None = None) -> tuple[Path, ...]:
    stem = path.with_suffix("")
    existing: list[Path] = []
    for extension in _SUPPORTED_ARTWORK_EXTENSIONS:
        candidate = stem.with_suffix(extension)
        try:
            _entry_stat(candidate, directory_fd)
        except FileNotFoundError:
            continue
        existing.append(candidate)
    return tuple(existing)


def artwork_targets(
    grid_dir: Path,
    artwork_id: int,
    artwork: ArtworkAssets,
) -> tuple[tuple[str, Path, str], ...]:
    """Return output file paths inferred from each image URL's format."""
    candidates = (
        ("portrait", f"{artwork_id}p", artwork.portrait_url, ".jpg"),
        ("hero", f"{artwork_id}_hero", artwork.hero_url, ".jpg"),
        ("logo", f"{artwork_id}_logo", artwork.logo_url, ".png"),
    )
    return tuple(
        (kind, grid_dir / f"{stem}{_url_extension(url, fallback)}", url)
        for kind, stem, url, fallback in candidates
        if isinstance(url, str) and url
    )


def _url_extension(url: str, fallback: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.casefold()
    return suffix if suffix in _SUPPORTED_ARTWORK_EXTENSIONS else fallback


def _path_for_content(path: Path, url: str, content: bytes) -> Path:
    extension = _url_extension(url, path.suffix)
    if content.startswith(b"\x89PNG\r\n\x1a\n") and extension != ".png":
        raise SteamStoreRequestFailed("artwork content does not match the URL format")
    if content.startswith(b"\xff\xd8\xff") and extension not in {".jpg", ".jpeg"}:
        raise SteamStoreRequestFailed("artwork content does not match the URL format")
    return path.with_suffix(extension)


def _download(url: str, downloader: Download) -> bytes:
    content = downloader(url)
    if not isinstance(content, bytes) or not content:
        raise ValueError(f"Artwork download was empty or non-binary: {url}")
    return content


def _commit_files(
    assets: tuple[tuple[str, Path, bytes], ...],
    *,
    overwrite: bool,
    directory_fd: int | None,
) -> _CommitResult:
    installed: list[Path] = []
    backups: list[Path] = []
    conflicts: list[Path] = []
    failed: list[Path] = []
    warnings: list[str] = []

    for _, target, content in assets:
        temporary_path = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        temporary_identity: _FileIdentity | None = None
        backup_path: Path | None = None
        backup_moved = False
        try:
            existing = _existing_slot_paths(target, directory_fd)
            target_is_symlink = (
                target.is_symlink()
                if directory_fd is None
                else _is_symlink(target, directory_fd)
            )
            if target_is_symlink:
                conflicts.append(target)
                continue
            if existing and not overwrite:
                conflicts.extend(existing)
                continue
            alternates = tuple(path for path in existing if path != target)
            conflicts.extend(alternates)

            expected_identity = (
                _file_identity(target, directory_fd)
                if overwrite and target in existing
                else None
            )
            if expected_identity is not None:
                backup_path = target.with_name(_next_backup_name(target.name))

            temporary_identity = _write_temporary_file(
                temporary_path,
                content,
                directory_fd,
            )

            if expected_identity is not None and backup_path is not None:
                try:
                    _rename_entry_no_clobber(target, backup_path, directory_fd)
                    backup_moved = True
                except FileNotFoundError:
                    expected_identity = None
                    backup_path = None
                if backup_moved and backup_path is not None and expected_identity is not None:
                    backup_identity = _file_identity(backup_path, directory_fd)
                    if not _same_payload_identity(backup_identity, expected_identity):
                        preserved_backup = backup_path
                        try:
                            _rename_entry_no_clobber(preserved_backup, target, directory_fd)
                            backup_moved = False
                            backup_path = None
                        except (FileExistsError, OSError):
                            backups.append(preserved_backup)
                            backup_moved = False
                            backup_path = None
                        conflicts.extend(_existing_slot_paths(target, directory_fd) or (target,))
                        continue
                    backups.append(backup_path)

            try:
                installed_identity = _publish_no_clobber(
                    temporary_path,
                    target,
                    directory_fd,
                )
            except FileExistsError:
                conflicts.extend(_existing_slot_paths(target, directory_fd) or (target,))
                continue

            if not _path_matches_identity(target, installed_identity, directory_fd):
                conflicts.extend(_existing_slot_paths(target, directory_fd) or (target,))
                continue
            conflicts.extend(
                path
                for path in _existing_slot_paths(target, directory_fd)
                if path != target
            )
            installed.append(target)
            try:
                _fsync_directory(directory_fd)
            except OSError as error:
                warnings.append(f"Installed {target}, but could not sync its directory: {error}")
        except OSError as error:
            failed.append(target)
            warnings.append(f"Could not install {target}: {error}")
            if (
                backup_moved
                and backup_path is not None
                and _entry_exists(backup_path, directory_fd)
            ):
                try:
                    if _entry_exists(target, directory_fd):
                        if backup_path not in backups:
                            backups.append(backup_path)
                    else:
                        backup_info = _entry_stat(backup_path, directory_fd)
                        if stat.S_ISREG(backup_info.st_mode):
                            _restore_backup_independently(
                                backup_path,
                                target,
                                directory_fd,
                            )
                            if backup_path not in backups:
                                backups.append(backup_path)
                        else:
                            _rename_entry_no_clobber(backup_path, target, directory_fd)
                            if backup_path in backups:
                                backups.remove(backup_path)
                except (FileExistsError, OSError) as restore_error:
                    warnings.append(
                        f"Could not restore previous artwork from {backup_path}: {restore_error}"
                    )
                    if backup_path not in backups:
                        backups.append(backup_path)
                backup_moved = False
            with contextlib.suppress(OSError):
                conflicts.extend(
                    path
                    for path in _existing_slot_paths(target, directory_fd)
                    if _is_symlink(path, directory_fd)
                )
        finally:
            if temporary_identity is not None:
                _unlink_if_owned(temporary_path, temporary_identity, directory_fd)

    return _CommitResult(
        installed_paths=tuple(installed),
        backup_paths=tuple(dict.fromkeys(backups)),
        conflicting_paths=tuple(dict.fromkeys(conflicts)),
        failed_paths=tuple(dict.fromkeys(failed)),
        warning="; ".join(warnings) if warnings else None,
    )


def _publish_no_clobber(
    temporary: Path,
    target: Path,
    directory_fd: int | None,
) -> _FileIdentity:
    identity = _file_identity(temporary, directory_fd)
    if directory_fd is None:
        _ensure_parent_is_safe(target)
    try:
        if directory_fd is None:
            os.link(temporary, target, follow_symlinks=False)
        else:
            os.link(
                temporary.name,
                target.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
    except FileExistsError:
        raise
    except (OSError, NotImplementedError):
        return _rename_no_clobber(temporary, target, directory_fd)
    published_identity = _file_identity(target, directory_fd)
    if not _same_payload_identity(published_identity, identity):
        raise FileExistsError(f"Artwork target changed during installation: {target}")
    return published_identity


def _rename_entry_no_clobber(
    source: Path,
    target: Path,
    directory_fd: int | None,
) -> None:
    if directory_fd is None:
        _ensure_parent_is_safe(source)
        _ensure_parent_is_safe(target)
    if os.name == "nt":
        os.rename(source, target)
    elif sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOTSUP, "atomic no-replace rename is unavailable")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        base_fd = directory_fd if directory_fd is not None else -100
        result = renameat2(
            base_fd,
            os.fsencode(source.name if directory_fd is not None else source),
            base_fd,
            os.fsencode(target.name if directory_fd is not None else target),
            1,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number), str(target))
    elif sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renameatx = getattr(libc, "renameatx_np", None)
        if renameatx is None:
            raise OSError(errno.ENOTSUP, "atomic no-replace rename is unavailable")
        renameatx.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx.restype = ctypes.c_int
        base_fd = directory_fd if directory_fd is not None else -2
        result = renameatx(
            base_fd,
            os.fsencode(source.name if directory_fd is not None else source),
            base_fd,
            os.fsencode(target.name if directory_fd is not None else target),
            4,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number), str(target))
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace rename is unavailable")


def _rename_no_clobber(
    source: Path,
    target: Path,
    directory_fd: int | None,
) -> _FileIdentity:
    _rename_entry_no_clobber(source, target, directory_fd)
    return _file_identity(target, directory_fd)


def _copy_entry_to_temporary(
    source: Path,
    temporary: Path,
    directory_fd: int | None,
) -> _FileIdentity:
    source_fd = _open_entry(source, os.O_RDONLY, directory_fd)
    temporary_fd: int | None = None
    try:
        source_info = os.fstat(source_fd)
        if not stat.S_ISREG(source_info.st_mode):
            raise OSError(f"refusing to restore non-regular artwork: {source}")
        source_identity = _identity_from_stat(source_info)
        temporary_fd = _open_entry(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            directory_fd,
        )
        with os.fdopen(source_fd, "rb", closefd=False) as input_file, os.fdopen(
            temporary_fd, "wb"
        ) as output_file:
            temporary_fd = None
            shutil.copyfileobj(input_file, output_file)
            output_file.flush()
            os.fsync(output_file.fileno())
            temporary_identity = _identity_from_stat(os.fstat(output_file.fileno()))
        if _identity_from_stat(os.fstat(source_fd)) != source_identity:
            raise OSError(f"backup changed while being restored: {source}")
        try:
            current_source_identity = _file_identity(source, directory_fd)
        except OSError as error:
            raise OSError(f"backup path changed while being restored: {source}") from error
        if not _same_payload_identity(current_source_identity, source_identity):
            raise OSError(f"backup path changed while being restored: {source}")
        return temporary_identity
    except BaseException:
        if temporary_fd is not None:
            os.close(temporary_fd)
        _unlink_entry(temporary, directory_fd, missing_ok=True)
        raise
    finally:
        os.close(source_fd)


def _restore_backup_independently(
    backup: Path,
    target: Path,
    directory_fd: int | None,
) -> None:
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.restore")
    temporary_identity = _copy_entry_to_temporary(backup, temporary, directory_fd)
    try:
        _publish_no_clobber(temporary, target, directory_fd)
    finally:
        _unlink_if_owned(temporary, temporary_identity, directory_fd)


def _write_temporary_file(
    path: Path,
    content: bytes,
    directory_fd: int | None = None,
) -> _FileIdentity:
    descriptor = _open_entry(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        directory_fd,
        mode=0o666,
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            identity = _identity_from_stat(os.fstat(temporary_file.fileno()))
        return identity
    except BaseException:
        _unlink_entry(path, directory_fd, missing_ok=True)
        raise


def _open_grid_directory(path: Path) -> int | None:
    try:
        if path.resolve(strict=True) != path:
            raise OSError(errno.ELOOP, "grid path resolves through a symbolic link", str(path))
    except FileNotFoundError as error:
        raise OSError(
            errno.ENOENT,
            "grid directory disappeared before opening",
            str(path),
        ) from error
    if os.name == "nt":
        return None
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    if not _grid_directory_matches(path, descriptor):
        os.close(descriptor)
        raise OSError(errno.ELOOP, "grid directory changed while opening", str(path))
    return descriptor


def _grid_directory_matches(path: Path, directory_fd: int | None) -> bool:
    try:
        if path.resolve(strict=True) != path:
            return False
    except OSError:
        return False
    if directory_fd is None:
        try:
            _validate_grid_dir(path)
            return True
        except ArtworkWriteFailed:
            return False
    try:
        path_info = path.lstat()
        descriptor_info = os.fstat(directory_fd)
    except OSError:
        return False
    return (
        stat.S_ISDIR(path_info.st_mode)
        and path_info.st_dev == descriptor_info.st_dev
        and path_info.st_ino == descriptor_info.st_ino
    )


def _entry_stat(path: Path, directory_fd: int | None) -> os.stat_result:
    if directory_fd is None:
        return path.lstat()
    return os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)


def _entry_exists(path: Path, directory_fd: int | None) -> bool:
    try:
        _entry_stat(path, directory_fd)
    except FileNotFoundError:
        return False
    return True


def _is_symlink(path: Path, directory_fd: int | None) -> bool:
    try:
        return stat.S_ISLNK(_entry_stat(path, directory_fd).st_mode)
    except FileNotFoundError:
        return False


def _open_entry(
    path: Path,
    flags: int,
    directory_fd: int | None,
    *,
    mode: int = 0o666,
    nofollow: bool = True,
) -> int:
    if nofollow and _is_symlink(path, directory_fd):
        raise OSError(errno.ELOOP, "refusing to follow a symbolic link", str(path))
    if directory_fd is None:
        _ensure_parent_is_safe(path)
    flags |= getattr(os, "O_NOFOLLOW", 0) if nofollow else 0
    if os.name == "nt":
        flags |= getattr(os, "O_BINARY", 0)
    if directory_fd is None:
        return os.open(path, flags, mode)
    return os.open(path.name, flags, mode, dir_fd=directory_fd)


def _file_identity(path: Path, directory_fd: int | None = None) -> _FileIdentity:
    info = _entry_stat(path, directory_fd)
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"not a regular file: {path}")
    return _identity_from_stat(info)


def _identity_from_stat(info: os.stat_result) -> _FileIdentity:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _same_payload_identity(left: _FileIdentity, right: _FileIdentity) -> bool:
    # Rename/link-count operations can update ctime without changing file contents.
    return left[:4] == right[:4]


def _path_matches_identity(
    path: Path,
    identity: _FileIdentity,
    directory_fd: int | None,
) -> bool:
    try:
        return _file_identity(path, directory_fd) == identity
    except OSError:
        return False


def _rename_entry(source: Path, target: Path, directory_fd: int | None) -> None:
    if directory_fd is None:
        _ensure_parent_is_safe(source)
        _ensure_parent_is_safe(target)
        os.rename(source, target)
    else:
        os.rename(
            source.name,
            target.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )


def _unlink_entry(
    path: Path,
    directory_fd: int | None,
    *,
    missing_ok: bool = False,
) -> None:
    try:
        if directory_fd is None:
            _ensure_parent_is_safe(path)
            path.unlink()
        else:
            os.unlink(path.name, dir_fd=directory_fd)
    except FileNotFoundError:
        if not missing_ok:
            raise


def _unlink_if_owned(
    path: Path,
    identity: _FileIdentity,
    directory_fd: int | None,
) -> None:
    try:
        current_identity = _file_identity(path, directory_fd)
    except OSError:
        return
    if _same_payload_identity(current_identity, identity):
        _unlink_entry(path, directory_fd)


def _ensure_parent_is_safe(path: Path) -> None:
    parent = path.parent
    try:
        _validate_grid_dir(parent)
        resolved_parent = parent.resolve(strict=True)
    except (ArtworkWriteFailed, OSError) as error:
        raise OSError(
            errno.ELOOP,
            "artwork parent is not a stable directory",
            str(parent),
        ) from error
    if resolved_parent != parent:
        raise OSError(errno.ELOOP, "artwork parent resolves through a symbolic link", str(parent))


def _validate_grid_dir(grid_dir: Path) -> None:
    try:
        info = grid_dir.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise ArtworkWriteFailed(grid_dir, "grid directory must not be a symbolic link")
    if not stat.S_ISDIR(info.st_mode):
        raise ArtworkWriteFailed(grid_dir, "grid path exists but is not a directory")


def _fsync_directory(directory: int | Path | None) -> None:
    if os.name == "nt" or directory is None:
        return
    if isinstance(directory, int):
        os.fsync(directory)
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _next_backup_name(filename: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{filename}.bak.{timestamp}-{uuid4().hex}"
