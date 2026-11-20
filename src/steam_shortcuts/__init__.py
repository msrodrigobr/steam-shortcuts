"""Portable, safe management of local Steam non-Steam shortcuts."""

from .api import (
    add_shortcut,
    add_shortcut_from_archive,
    enrich_game_data,
    install_steamgriddb_artwork,
    preview_steamgriddb_artwork,
)
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
    GameEnrichmentResult,
    ShortcutRequest,
    ShortcutResult,
    SteamLibraryArtwork,
    SteamProfile,
)

__version__ = "0.4.0"

__all__ = [
    "add_shortcut",
    "add_shortcut_from_archive",
    "enrich_game_data",
    "install_steamgriddb_artwork",
    "preview_steamgriddb_artwork",
    "read_executable_metadata",
    "ArchiveExecutableSelectionRequired",
    "ArchiveInspection",
    "ExecutableMetadata",
    "ExecutableTitleCandidate",
    "GameEnrichmentResult",
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
    "SteamLibraryArtwork",
    "SteamRunning",
    "__version__",
]
