"""Portable, safe management of local Steam non-Steam shortcuts."""

from .errors import (
    InvalidShortcutFile,
    ProfileNotFound,
    ProfileSelectionRequired,
    ShortcutConflict,
    SteamNotFound,
    SteamRunning,
)
from .models import ShortcutRequest, ShortcutResult, SteamProfile

__version__ = "0.1.0"

__all__ = [
    "InvalidShortcutFile",
    "ProfileNotFound",
    "ProfileSelectionRequired",
    "ShortcutConflict",
    "ShortcutRequest",
    "ShortcutResult",
    "SteamNotFound",
    "SteamProfile",
    "SteamRunning",
    "__version__",
]
