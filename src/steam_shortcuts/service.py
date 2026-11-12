"""Shortcut construction and duplicate-detection rules."""

from __future__ import annotations

import os
import zlib
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .errors import InvalidExecutable, ShortcutConflict, ShortcutVerificationFailed
from .models import ShortcutRequest, ShortcutResult, ShortcutStatus
from .vdf_store import VdfMap, VdfValue, load_shortcuts, write_shortcuts_atomically

_UINT32_MODULUS = 2**32
_UINT32_SIGN_BIT = 2**31
_RUN_GAME_LOW_BITS = 0x02000000


@dataclass(frozen=True, slots=True)
class ShortcutAdditionPlan:
    """A verified, not-yet-persisted shortcut operation."""

    status: ShortcutStatus
    index: str
    shortcut_id: int
    run_game_url: str
    entry: dict[str, VdfValue] | None


def shortcut_app_id(quoted_executable: str, app_name: str) -> int:
    """Return Steam's unsigned 32-bit non-Steam shortcut identifier."""
    checksum = zlib.crc32(f"{quoted_executable}{app_name}".encode()) & 0xFFFFFFFF
    return checksum | _UINT32_SIGN_BIT


def plan_shortcut_addition(root: VdfMap, request: ShortcutRequest) -> ShortcutAdditionPlan:
    """Build an idempotent shortcut addition without mutating ``root``."""
    _validate_executable(request.executable)
    executable_key = _path_key(request.executable)
    shortcuts = _shortcut_map(root)

    for index, existing in shortcuts.items():
        if not isinstance(existing, dict):
            continue
        existing_executable = _stored_executable(existing)
        if existing_executable is None or _path_key(existing_executable) != executable_key:
            continue
        existing_name = _stored_name(existing)
        existing_id = _stored_app_id(existing)
        if existing_name == request.name:
            if existing_id is None:
                raise ShortcutConflict("Existing matching Steam shortcut has no valid AppID")
            return ShortcutAdditionPlan(
                status="already_exists",
                index=index,
                shortcut_id=existing_id,
                run_game_url=run_game_url(existing_id),
                entry=None,
            )
        raise ShortcutConflict(
            f"Executable already belongs to Steam shortcut {existing_name!r} at index {index}"
        )

    quoted_executable = _quote(request.executable)
    shortcut_id = shortcut_app_id(quoted_executable, request.name)
    for index, existing in shortcuts.items():
        if not isinstance(existing, dict):
            continue
        existing_id = _stored_app_id(existing)
        if existing_id is not None and existing_id == shortcut_id:
            raise ShortcutConflict(
                "Shortcut AppID collision with existing shortcut at index "
                f"{index}; no change was made"
            )

    return ShortcutAdditionPlan(
        status="added",
        index=_next_index(shortcuts),
        shortcut_id=shortcut_id,
        run_game_url=run_game_url(shortcut_id),
        entry=_build_entry(request, shortcut_id),
    )


def run_game_url(shortcut_id: int) -> str:
    """Return the Steam protocol URL corresponding to an unsigned shortcut ID."""
    return f"steam://rungameid/{(shortcut_id << 32) | _RUN_GAME_LOW_BITS}"


def add_shortcut_to_profile(
    shortcuts_path: Path,
    profile_id: str,
    request: ShortcutRequest,
    *,
    now: datetime | None = None,
) -> ShortcutResult:
    """Add one shortcut to a stopped Steam profile and verify the persisted result."""
    root = load_shortcuts(shortcuts_path)
    plan = plan_shortcut_addition(root, request)
    if plan.status == "already_exists":
        return ShortcutResult(
            status=plan.status,
            profile_id=profile_id,
            shortcuts_path=shortcuts_path,
            shortcut_id=plan.shortcut_id,
            run_game_url=plan.run_game_url,
            backup_path=None,
        )

    updated_root = deepcopy(root)
    updated_shortcuts = _shortcut_map(updated_root)
    if plan.entry is None:
        raise AssertionError("added shortcut plan must contain an entry")
    updated_shortcuts[plan.index] = plan.entry
    backup_path = write_shortcuts_atomically(shortcuts_path, updated_root, now=now)

    verified_root = load_shortcuts(shortcuts_path)
    verified_entry = _shortcut_map(verified_root).get(plan.index)
    if verified_entry != plan.entry:
        raise ShortcutVerificationFailed(shortcuts_path, plan.index)

    return ShortcutResult(
        status=plan.status,
        profile_id=profile_id,
        shortcuts_path=shortcuts_path,
        shortcut_id=plan.shortcut_id,
        run_game_url=plan.run_game_url,
        backup_path=backup_path,
    )


def to_signed_int32(value: int) -> int:
    """Represent an unsigned Steam AppID in binary-VDF's signed int32 field."""
    if not 0 <= value < _UINT32_MODULUS:
        raise ValueError("Steam AppID must fit in unsigned 32-bit range")
    return value - _UINT32_MODULUS if value >= _UINT32_SIGN_BIT else value


def to_unsigned_int32(value: int) -> int:
    """Return the unsigned interpretation of a binary-VDF signed int32 value."""
    if not -_UINT32_SIGN_BIT <= value < _UINT32_SIGN_BIT:
        raise ValueError("Steam AppID must fit in signed 32-bit range")
    return value + _UINT32_MODULUS if value < 0 else value


def _build_entry(request: ShortcutRequest, shortcut_id: int) -> dict[str, VdfValue]:
    start_dir = request.start_dir if request.start_dir is not None else request.executable.parent
    tags: dict[str, VdfValue] = {}
    for index, tag in enumerate(request.tags):
        tags[str(index)] = tag
    return {
        "appid": to_signed_int32(shortcut_id),
        "AppName": request.name,
        "Exe": _quote(request.executable),
        "StartDir": _quote(start_dir),
        "icon": "" if request.icon is None else str(request.icon),
        "ShortcutPath": "",
        "LaunchOptions": request.launch_options,
        "IsHidden": 0,
        "AllowDesktopConfig": 1,
        "AllowOverlay": 1,
        "openvr": 0,
        "Devkit": 0,
        "DevkitGameID": "",
        "DevkitOverrideAppID": 0,
        "LastPlayTime": 0,
        "tags": tags,
    }


def _shortcut_map(root: VdfMap) -> dict[str, VdfValue]:
    shortcuts = root.get("shortcuts")
    if not isinstance(shortcuts, dict):
        raise ValueError("'shortcuts' must be a mapping")
    return shortcuts


def _validate_executable(executable: Path) -> None:
    if not executable.exists():
        raise InvalidExecutable(executable, "path does not exist")
    if not executable.is_file():
        raise InvalidExecutable(executable, "path is not a file")
    if '"' in str(executable):
        raise InvalidExecutable(executable, "path contains a double quote")


def _stored_executable(entry: dict[str, VdfValue]) -> Path | None:
    executable = entry.get("Exe", entry.get("exe"))
    if not isinstance(executable, str):
        return None
    return Path(executable.strip().removeprefix('"').removesuffix('"'))


def _stored_name(entry: dict[str, VdfValue]) -> str:
    name = entry.get("AppName", entry.get("appname", ""))
    return name if isinstance(name, str) else ""


def _stored_app_id(entry: dict[str, VdfValue]) -> int | None:
    app_id = entry.get("appid")
    if not isinstance(app_id, int) or isinstance(app_id, bool):
        return None
    try:
        return to_unsigned_int32(app_id)
    except ValueError:
        return None


def _path_key(path: Path) -> str:
    resolved = path.resolve(strict=True)
    return os.path.normcase(str(resolved)) if os.name == "nt" else str(resolved)


def _quote(path: Path) -> str:
    return f'"{path}"'


def _next_index(shortcuts: dict[str, VdfValue]) -> str:
    numeric_indices = [int(index) for index in shortcuts if index.isdecimal()]
    return str(max(numeric_indices, default=-1) + 1)
