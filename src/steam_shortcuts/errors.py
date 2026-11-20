"""Domain-specific exceptions for steam-shortcuts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePosixPath


class SteamShortcutsError(Exception):
    """Base class for errors raised by steam-shortcuts."""


class SteamNotFound(SteamShortcutsError):
    """Raised when no usable local Steam root can be found."""

    def __init__(self, tried: Iterable[Path] | str) -> None:
        if isinstance(tried, str):
            self.tried: tuple[Path, ...] = ()
            super().__init__(tried)
            return
        self.tried = tuple(tried)
        formatted_paths = ", ".join(str(path) for path in self.tried) or "(none)"
        super().__init__(f"Steam installation was not found. Tried: {formatted_paths}")


class ProfileSelectionRequired(SteamShortcutsError):
    """Raised when a Steam root contains multiple user profiles."""

    def __init__(self, profile_ids: Iterable[str]) -> None:
        self.profile_ids = tuple(profile_ids)
        choices = ", ".join(self.profile_ids)
        super().__init__(f"Multiple Steam profiles found; specify one with --steam-id: {choices}")


class ProfileNotFound(SteamShortcutsError):
    """Raised when a requested Steam profile does not exist beneath userdata."""

    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        super().__init__(f"Steam profile was not found: {profile_id}")


class SteamRunning(SteamShortcutsError):
    """Raised when Steam might overwrite a shortcut-file mutation."""

    def __init__(self) -> None:
        super().__init__("Steam is running; fully exit Steam before changing shortcuts")


class ShortcutConflict(SteamShortcutsError):
    """Raised when an executable already belongs to a different shortcut."""


class ShortcutNotFound(SteamShortcutsError):
    """Raised when an artwork action names no shortcut in the chosen profile."""

    def __init__(self, shortcut_id: int, profile_id: str) -> None:
        self.shortcut_id = shortcut_id
        self.profile_id = profile_id
        super().__init__(f"Shortcut ID {shortcut_id} was not found in Steam profile {profile_id}")


class ShortcutNameNotFound(SteamShortcutsError):
    """Raised when an exact shortcut name cannot be found in one Steam profile."""

    def __init__(self, name: str, profile_id: str) -> None:
        self.name = name
        self.profile_id = profile_id
        super().__init__(
            f"No exact shortcut named '{name}' was found in Steam profile {profile_id}"
        )


class ShortcutNameAmbiguous(SteamShortcutsError):
    """Raised when a shortcut name identifies multiple local entries."""

    def __init__(self, name: str, shortcut_ids: Iterable[int]) -> None:
        self.name = name
        self.shortcut_ids = tuple(shortcut_ids)
        formatted = ", ".join(str(value) for value in self.shortcut_ids)
        super().__init__(f"Shortcut name '{name}' is ambiguous; matching shortcut IDs: {formatted}")


class InvalidExecutable(SteamShortcutsError):
    """Raised when a requested shortcut target cannot be launched as a file."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Invalid executable {path}: {reason}")


class InvalidArchive(SteamShortcutsError):
    """Raised when an archive is unsafe, unreadable, or unsupported."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Invalid archive {path}: {reason}")


class ArchiveExecutableSelectionRequired(SteamShortcutsError):
    """Raised when archive metadata cannot identify one launch executable."""

    def __init__(self, archive: Path, candidates: Iterable[PurePosixPath]) -> None:
        self.archive = archive
        self.candidates = tuple(candidates)
        listed = ", ".join(str(candidate) for candidate in self.candidates) or "(none found)"
        super().__init__(
            f"Could not select a game executable from archive {archive}. "
            f"Candidates: {listed}. Re-run with --exe-relative <archive-relative-path>."
        )


class SteamGridDbApiKeyMissing(SteamShortcutsError):
    """Raised when an online SteamGridDB operation has no API credential."""

    def __init__(self, reason: str | None = None) -> None:
        message = (
            "SteamGridDB API key is required; set STEAMGRIDDB_API_KEY or run from an "
            "interactive terminal to save it locally"
        )
        super().__init__(message if reason is None else f"{message}: {reason}")


class CredentialStorageError(SteamShortcutsError):
    """Raised when a local API credential cannot be read or safely persisted."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Credential storage error at {path}: {reason}")


class SteamGridDbRequestFailed(SteamShortcutsError):
    """Raised when SteamGridDB cannot fulfill an authenticated request."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"SteamGridDB request failed: {reason}")


class SteamStoreRequestFailed(SteamShortcutsError):
    """Raised when Steam Store search cannot return a usable response."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Steam Store request failed: {reason}")


class ProtonDbRequestFailed(SteamShortcutsError):
    """Raised when ProtonDB's public compatibility summary is unavailable."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"ProtonDB request failed: {reason}")


class ArtworkAlreadyExists(SteamShortcutsError):
    """Raised when artwork would replace an existing Steam grid file."""

    def __init__(self, paths: Iterable[Path]) -> None:
        self.paths = tuple(paths)
        formatted = ", ".join(str(path) for path in self.paths)
        super().__init__(
            f"Refusing to replace existing artwork: {formatted}. Re-run with --overwrite."
        )


class ArtworkWriteFailed(SteamShortcutsError):
    """Raised when artwork cannot be safely written to Steam's grid directory."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Could not install artwork in {path}: {reason}")


class ShortcutVerificationFailed(SteamShortcutsError):
    """Raised when a just-written shortcut cannot be read back unchanged."""

    def __init__(self, path: Path, index: str) -> None:
        self.path = path
        self.index = index
        super().__init__(f"Could not verify shortcut {index} after writing {path}")


class InvalidShortcutFile(SteamShortcutsError):
    """Raised when shortcuts.vdf is corrupt or structurally unexpected."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Invalid Steam shortcuts file at {path}: {reason}")
