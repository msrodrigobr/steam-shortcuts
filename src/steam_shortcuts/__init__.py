"""Portable, safe management of local Steam non-Steam shortcuts."""

from .api import add_shortcut, add_shortcut_from_archive
from .errors import (
    ArchiveExecutableSelectionRequired,
    InvalidArchive,
    InvalidExecutable,
    InvalidShortcutFile,
    ProfileNotFound,
    ProfileSelectionRequired,
    ShortcutConflict,
    ShortcutVerificationFailed,
    SteamNotFound,
    SteamRunning,
)
from .executable_metadata import read_executable_metadata
from .models import (
    ArchiveInspection,
    ExecutableMetadata,
    ExecutableTitleCandidate,
    ShortcutRequest,
    ShortcutResult,
    SteamProfile,
)

__version__ = "0.2.1"

__all__ = [
    "add_shortcut",
    "add_shortcut_from_archive",
    "read_executable_metadata",
    "ArchiveExecutableSelectionRequired",
    "ArchiveInspection",
    "ExecutableMetadata",
    "ExecutableTitleCandidate",
    "InvalidArchive",
    "InvalidShortcutFile",
    "InvalidExecutable",
    "ProfileNotFound",
    "ProfileSelectionRequired",
    "ShortcutConflict",
    "ShortcutVerificationFailed",
    "ShortcutRequest",
    "ShortcutResult",
    "SteamNotFound",
    "SteamProfile",
    "SteamRunning",
    "__version__",
]
