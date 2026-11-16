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
from .models import ArchiveInspection, ShortcutRequest, ShortcutResult, SteamProfile

__version__ = "0.2.1"

__all__ = [
    "add_shortcut",
    "add_shortcut_from_archive",
    "ArchiveExecutableSelectionRequired",
    "ArchiveInspection",
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
