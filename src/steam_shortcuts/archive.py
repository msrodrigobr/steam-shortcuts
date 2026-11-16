"""Safe inspection and extraction of archived game directories."""

from __future__ import annotations

import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import ArchiveExecutableSelectionRequired, InvalidArchive
from .models import ArchiveInspection

_INSTALLER_NAMES = {"setup.exe", "install.exe", "installer.exe", "uninstall.exe"}


@dataclass(frozen=True, slots=True)
class _ValidatedArchive:
    """Archive metadata that is safe to use for selection and extraction."""

    members: tuple[tarfile.TarInfo, ...]
    executable_candidates: tuple[PurePosixPath, ...]


def inspect_archive(
    archive_path: Path,
    *,
    extract_to: Path,
    executable_relative: PurePosixPath | None = None,
) -> ArchiveInspection:
    """Inspect a supported tar archive without extracting any member."""
    archive = archive_path.expanduser().resolve(strict=False)
    if not archive.is_file():
        raise InvalidArchive(archive, "path does not exist or is not a file")

    validated = _read_validated_archive(archive)
    candidates = validated.executable_candidates

    if executable_relative is not None:
        selected = _validate_explicit_executable(archive, executable_relative, candidates)
        return ArchiveInspection(
            archive=archive,
            extract_to=extract_to,
            executable_relative=selected,
            selection="explicit",
            executable_candidates=candidates,
        )

    eligible = tuple(
        candidate for candidate in candidates if not _looks_like_installer(candidate.name)
    )
    if len(eligible) != 1:
        raise ArchiveExecutableSelectionRequired(archive, candidates)
    return ArchiveInspection(
        archive=archive,
        extract_to=extract_to,
        executable_relative=eligible[0],
        selection="single_candidate",
        executable_candidates=candidates,
    )


def _read_validated_archive(archive: Path) -> _ValidatedArchive:
    try:
        with tarfile.open(archive, mode="r:*") as tar:
            return _validated_members(archive, tuple(tar.getmembers()))
    except (tarfile.TarError, OSError) as error:
        raise InvalidArchive(archive, "not a supported tar archive") from error


def _validated_members(archive: Path, members: tuple[tarfile.TarInfo, ...]) -> _ValidatedArchive:
    paths: list[PurePosixPath] = []
    seen: set[PurePosixPath] = set()
    for member in members:
        path = _safe_member_path(archive, member.name)
        if not (member.isdir() or member.isreg()):
            raise InvalidArchive(archive, f"unsupported member type: {member.name!r}")
        if path in seen:
            raise InvalidArchive(archive, f"duplicate member path: {member.name!r}")
        seen.add(path)
        paths.append(path)

    candidates = tuple(
        sorted(
            (
                path
                for member, path in zip(members, paths, strict=True)
                if member.isreg() and path.suffix.casefold() == ".exe"
            ),
            key=lambda path: str(path).casefold(),
        )
    )
    return _ValidatedArchive(members=members, executable_candidates=candidates)


def _safe_member_path(archive: Path, member_name: str) -> PurePosixPath:
    path = PurePosixPath(member_name)
    if (
        not member_name
        or path == PurePosixPath(".")
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in member_name
    ):
        raise InvalidArchive(archive, f"unsafe member path: {member_name!r}")
    return path


def _looks_like_installer(filename: str) -> bool:
    lowered = filename.casefold()
    return lowered in _INSTALLER_NAMES or (lowered.startswith("unins") and lowered.endswith(".exe"))


def _validate_explicit_executable(
    archive: Path,
    requested: PurePosixPath,
    candidates: tuple[PurePosixPath, ...],
) -> PurePosixPath:
    if requested.is_absolute() or ".." in requested.parts or "\\" in str(requested):
        raise InvalidArchive(archive, "--exe-relative must be a safe archive-relative POSIX path")
    if requested not in candidates:
        raise InvalidArchive(archive, f"--exe-relative is not a regular .exe member: {requested}")
    return requested
