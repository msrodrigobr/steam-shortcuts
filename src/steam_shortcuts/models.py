"""Public data models for Steam shortcut operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

ShortcutStatus = Literal["added", "already_exists"]
ArchiveSelection = Literal["explicit", "single_candidate"]
MetadataTitleSource = Literal[
    "product_name",
    "file_description",
    "internal_name",
    "executable_stem",
]


@dataclass(frozen=True, slots=True)
class SteamProfile:
    """The Steam user profile selected for an operation."""

    profile_id: str
    shortcuts_path: Path


@dataclass(frozen=True, slots=True)
class ShortcutRequest:
    """A validated request to add one local executable to Steam."""

    name: str
    executable: Path
    start_dir: Path | None = None
    launch_options: str = ""
    icon: Path | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be blank")
        _reject_nul("name", self.name)
        _reject_nul("launch_options", self.launch_options)
        for tag in self.tags:
            if not tag.strip():
                raise ValueError("tags must not be blank")
            _reject_nul("tag", tag)


@dataclass(frozen=True, slots=True)
class ShortcutResult:
    """The verified result of adding or finding a Steam shortcut."""

    status: ShortcutStatus
    profile_id: str
    shortcuts_path: Path
    shortcut_id: int
    run_game_url: str
    backup_path: Path | None


@dataclass(frozen=True, slots=True)
class ArchiveInspection:
    """A validated tar archive and the executable selected within it."""

    archive: Path
    extract_to: Path
    executable_relative: PurePosixPath
    selection: ArchiveSelection
    executable_candidates: tuple[PurePosixPath, ...]
    archive_root: PurePosixPath | None = None

    def __post_init__(self) -> None:
        if self.executable_relative.is_absolute():
            raise ValueError("executable_relative must be relative")
        if ".." in self.executable_relative.parts:
            raise ValueError("executable_relative must not escape the archive root")
        if self.archive_root is not None:
            if self.archive_root.is_absolute() or len(self.archive_root.parts) != 1:
                raise ValueError("archive_root must be one safe path component")
            if self.archive_root.parts[0] in {"", ".", ".."}:
                raise ValueError("archive_root must be one safe path component")
            if self.executable_relative.parts[0] != self.archive_root.parts[0]:
                raise ValueError("executable_relative must be beneath archive_root")

    @property
    def install_relative(self) -> PurePosixPath:
        """Return the executable path relative to the final install directory."""
        if self.archive_root is None:
            return self.executable_relative
        return self.executable_relative.relative_to(self.archive_root)

    @property
    def executable(self) -> Path:
        return self.extract_to.joinpath(*self.install_relative.parts)


@dataclass(frozen=True, slots=True)
class ExecutableTitleCandidate:
    """A possible original game title inferred from local executable metadata."""

    value: str
    source: MetadataTitleSource


@dataclass(frozen=True, slots=True)
class ExecutableMetadata:
    """Windows PE version-resource metadata from one local executable."""

    executable: Path
    product_name: str | None
    file_description: str | None
    original_filename: str | None
    company_name: str | None
    internal_name: str | None
    product_version: str | None
    title_candidates: tuple[ExecutableTitleCandidate, ...]


@dataclass(frozen=True, slots=True)
class SteamGridDbGame:
    """One candidate game returned by the SteamGridDB search API."""

    id: int
    name: str
    types: tuple[str, ...]
    verified: bool


@dataclass(frozen=True, slots=True)
class SteamGridDbArtwork:
    """One selected portrait, hero, and logo set for a SteamGridDB game."""

    game_id: int
    portrait_url: str
    hero_url: str
    logo_url: str


@dataclass(frozen=True, slots=True)
class ArtworkInstallResult:
    """Verified local artwork files installed for one non-Steam shortcut."""

    shortcut_id: int
    artwork_id: int
    grid_dir: Path
    portrait_path: Path
    hero_path: Path
    logo_path: Path
    backup_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class SteamStoreGame:
    """One explicit Steam Store application candidate returned by title search."""

    app_id: int
    name: str
    kind: str


@dataclass(frozen=True, slots=True)
class ProtonDbReport:
    """Read-only compatibility evidence from ProtonDB's public summary endpoint."""

    app_id: int
    tier: str
    best_reported_tier: str
    trending_tier: str
    confidence: str
    score: float
    total_reports: int


def _reject_nul(field_name: str, value: str) -> None:
    if "\x00" in value:
        raise ValueError(f"{field_name} must not contain NUL")
