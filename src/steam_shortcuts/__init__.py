"""Portable, safe management of local Steam non-Steam shortcuts."""

from .errors import (
    InvalidExecutable,
    InvalidShortcutFile,
    ProfileNotFound,
    ProfileSelectionRequired,
    ShortcutConflict,
    ShortcutVerificationFailed,
    SteamNotFound,
    SteamRunning,
)
from .models import ShortcutRequest, ShortcutResult, SteamProfile

__version__ = "0.1.0"

__all__ = [
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
