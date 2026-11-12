"""Domain-specific exceptions for steam-shortcuts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


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


class InvalidExecutable(SteamShortcutsError):
    """Raised when a requested shortcut target cannot be launched as a file."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Invalid executable {path}: {reason}")


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
