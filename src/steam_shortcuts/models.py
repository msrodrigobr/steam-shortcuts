"""Public data models for Steam shortcut operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ShortcutStatus = Literal["added", "already_exists"]


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


def _reject_nul(field_name: str, value: str) -> None:
    if "\x00" in value:
        raise ValueError(f"{field_name} must not contain NUL")
