"""Steam client process safety checks."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import psutil

from .errors import SteamRunning


def ensure_steam_not_running(process_names: Iterable[str] | None = None) -> None:
    """Raise if the main Steam client process appears to be running.

    ``steamwebhelper`` is intentionally ignored: it can outlive the main client
    and does not, by itself, prove that Steam has the shortcuts file open.
    """
    names = process_names if process_names is not None else _running_process_names()
    for name in names:
        normalized = Path(name).name.casefold()
        if normalized in {"steam", "steam.exe"}:
            raise SteamRunning()


def _running_process_names() -> tuple[str, ...]:
    names: list[str] = []
    for process in psutil.process_iter(["name", "exe"]):
        try:
            info = process.info
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        for value in (info.get("name"), info.get("exe")):
            if isinstance(value, str) and value:
                names.append(value)
    return tuple(names)
