"""Validated binary-VDF storage for Steam's ``shortcuts.vdf`` file."""

from __future__ import annotations

import os
import shutil
import struct
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn, TypeAlias, cast
from uuid import uuid4

import vdf  # type: ignore[import-untyped]

from .errors import InvalidShortcutFile

VdfValue: TypeAlias = str | int | dict[str, "VdfValue"]
VdfMap: TypeAlias = dict[str, VdfValue]
_MIN_INT32 = -(2**31)
_MAX_INT32 = 2**31 - 1


def load_shortcuts(path: Path) -> VdfMap:
    """Load a valid shortcuts VDF file without creating a missing file."""
    if not path.exists():
        return {"shortcuts": {}}

    try:
        loaded = vdf.binary_loads(path.read_bytes())
    except (
        OSError,
        ValueError,
        TypeError,
        EOFError,
        IndexError,
        SyntaxError,
        struct.error,
    ) as error:
        raise InvalidShortcutFile(path, str(error)) from error

    return _normalize_root(loaded, path)


def serialize_shortcuts(root: VdfMap) -> bytes:
    """Validate and serialize a shortcut root into Valve binary-VDF bytes."""
    normalized = _normalize_for_serialization(root)
    try:
        return cast(bytes, vdf.binary_dumps(normalized))
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"Unable to serialize Steam shortcuts: {error}") from error


def write_shortcuts_atomically(
    path: Path,
    root: VdfMap,
    *,
    now: datetime | None = None,
) -> Path | None:
    """Back up and atomically replace one shortcuts VDF file.

    A missing target is created without a backup. Existing targets receive a
    sibling timestamped backup before ``os.replace`` switches in the new data.
    """
    serialized = serialize_shortcuts(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = _create_backup(path, now) if path.exists() else None
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary_path.open("xb") as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return backup_path


def _create_backup(path: Path, now: datetime | None) -> Path:
    timestamp = _backup_timestamp(now)
    candidate = path.with_name(f"{path.name}.bak.{timestamp}")
    sequence = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak.{timestamp}-{sequence}")
        sequence += 1
    shutil.copy2(path, candidate)
    return candidate


def _backup_timestamp(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _normalize_root(value: object, path: Path) -> VdfMap:
    if not isinstance(value, Mapping):
        raise InvalidShortcutFile(path, "root must be a mapping")

    try:
        root = _normalize_mapping(value, value_error=InvalidShortcutFile(path, "invalid value"))
    except ValueError as error:
        raise InvalidShortcutFile(path, str(error)) from error

    shortcuts = root.get("shortcuts")
    if shortcuts is None:
        root["shortcuts"] = {}
    elif not isinstance(shortcuts, dict):
        raise InvalidShortcutFile(path, "'shortcuts' must be a mapping")
    return root


def _normalize_for_serialization(root: VdfMap) -> VdfMap:
    normalized = _normalize_mapping(cast(Mapping[object, object], root))
    shortcuts = normalized.get("shortcuts")
    if shortcuts is None:
        normalized["shortcuts"] = {}
    elif not isinstance(shortcuts, dict):
        raise ValueError("'shortcuts' must be a mapping")
    return normalized


def _normalize_mapping(
    value: Mapping[object, object],
    *,
    value_error: Exception | None = None,
) -> VdfMap:
    normalized: VdfMap = {}
    for key, item in value.items():
        if not isinstance(key, str):
            _raise_validation_error("VDF keys must be strings", value_error)
        _reject_nul("VDF keys", key, value_error)
        normalized[key] = _normalize_value(item, value_error)
    return normalized


def _normalize_value(value: object, value_error: Exception | None) -> VdfValue:
    if isinstance(value, str):
        _reject_nul("VDF strings", value, value_error)
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if not _MIN_INT32 <= value <= _MAX_INT32:
            _raise_validation_error("VDF integers must fit in signed 32-bit range", value_error)
        return value
    if isinstance(value, Mapping):
        return _normalize_mapping(cast(Mapping[object, object], value), value_error=value_error)
    _raise_validation_error(f"Unsupported VDF value type: {type(value).__name__}", value_error)
    raise AssertionError("unreachable")


def _reject_nul(field_name: str, value: str, value_error: Exception | None) -> None:
    if "\x00" in value:
        _raise_validation_error(f"{field_name} must not contain NUL", value_error)


def _raise_validation_error(message: str, value_error: Exception | None) -> NoReturn:
    if value_error is not None:
        raise ValueError(message) from value_error
    raise ValueError(message)
