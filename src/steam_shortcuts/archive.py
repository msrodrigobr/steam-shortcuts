"""Safe inspection and extraction of archived game directories."""

from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from .errors import ArchiveExecutableSelectionRequired, InvalidArchive
from .models import ArchiveInspection

_INSTALLER_NAMES = {"setup.exe", "install.exe", "installer.exe", "uninstall.exe"}


@dataclass(frozen=True, slots=True)
class _ValidatedArchive:
    """Archive metadata that is safe to use for selection and extraction."""

    members: tuple[tarfile.TarInfo, ...]
    executable_candidates: tuple[PurePosixPath, ...]
    archive_root: PurePosixPath | None


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
            archive_root=validated.archive_root,
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
        archive_root=validated.archive_root,
    )


def extract_archive(inspection: ArchiveInspection) -> Path:
    """Safely extract an inspected archive and return its final executable path."""
    destination = inspection.extract_to.expanduser().resolve(strict=False)
    if not destination.parent.is_dir():
        raise InvalidArchive(
            inspection.archive,
            f"destination parent is not a directory: {destination.parent}",
        )
    if _path_exists(destination):
        raise InvalidArchive(inspection.archive, f"destination already exists: {destination}")

    stage = destination.parent / f".{destination.name}.steam-shortcuts-{uuid4().hex}"
    promoted = False
    try:
        stage.mkdir()
        with tarfile.open(inspection.archive, mode="r:*") as tar:
            members = tuple(tar.getmembers())
            validated = _validated_members(inspection.archive, members)
            if inspection.executable_relative not in validated.executable_candidates:
                raise InvalidArchive(
                    inspection.archive,
                    "archive changed after inspection; selected executable is no longer present",
                )
            if inspection.archive_root != validated.archive_root:
                raise InvalidArchive(
                    inspection.archive,
                    "archive root changed after inspection",
                )
            for member, relative_path in zip(
                validated.members,
                _member_paths(inspection.archive, validated.members),
                strict=True,
            ):
                target = stage.joinpath(*_install_relative(inspection, relative_path).parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise InvalidArchive(
                        inspection.archive,
                        f"could not read archive member: {member.name!r}",
                    )
                with source, target.open("xb") as destination_file:
                    shutil.copyfileobj(source, destination_file)

        staged_executable = stage.joinpath(*inspection.install_relative.parts)
        if not staged_executable.is_file():
            raise InvalidArchive(
                inspection.archive,
                "selected executable was not extracted as a regular file",
            )
        if _path_exists(destination):
            raise InvalidArchive(inspection.archive, f"destination already exists: {destination}")
        stage.rename(destination)
        promoted = True
        return destination.joinpath(*inspection.install_relative.parts)
    except (tarfile.TarError, OSError) as error:
        raise InvalidArchive(inspection.archive, "archive could not be extracted") from error
    finally:
        if not promoted:
            shutil.rmtree(stage, ignore_errors=True)


def _read_validated_archive(archive: Path) -> _ValidatedArchive:
    try:
        with tarfile.open(archive, mode="r:*") as tar:
            return _validated_members(archive, tuple(tar.getmembers()))
    except (tarfile.TarError, OSError) as error:
        raise InvalidArchive(archive, "not a supported tar archive") from error


def _validated_members(archive: Path, members: tuple[tarfile.TarInfo, ...]) -> _ValidatedArchive:
    paths = _member_paths(archive, members)
    seen: set[PurePosixPath] = set()
    for member, path in zip(members, paths, strict=True):
        if not (member.isdir() or member.isreg()):
            raise InvalidArchive(archive, f"unsupported member type: {member.name!r}")
        if path in seen:
            raise InvalidArchive(archive, f"duplicate member path: {member.name!r}")
        seen.add(path)

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
    return _ValidatedArchive(
        members=members,
        executable_candidates=candidates,
        archive_root=_archive_root(members, paths),
    )


def _member_paths(archive: Path, members: tuple[tarfile.TarInfo, ...]) -> tuple[PurePosixPath, ...]:
    return tuple(_safe_member_path(archive, member.name) for member in members)


def _archive_root(
    members: tuple[tarfile.TarInfo, ...],
    paths: tuple[PurePosixPath, ...],
) -> PurePosixPath | None:
    roots = {path.parts[0] for path in paths}
    if len(roots) != 1:
        return None
    for member, path in zip(members, paths, strict=True):
        if len(path.parts) == 1 and not member.isdir():
            return None
    return PurePosixPath(roots.pop())


def _install_relative(inspection: ArchiveInspection, path: PurePosixPath) -> PurePosixPath:
    if inspection.archive_root is None:
        return path
    return path.relative_to(inspection.archive_root)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _safe_member_path(archive: Path, member_name: str) -> PurePosixPath:
    path = PurePosixPath(member_name)
    if (
        not member_name
        or path == PurePosixPath(".")
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in member_name
        or any(PureWindowsPath(part).drive for part in path.parts)
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
