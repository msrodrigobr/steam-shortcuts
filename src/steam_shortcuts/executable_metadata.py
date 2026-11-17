"""Read portable Windows executable metadata for game-title discovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pefile  # type: ignore[import-untyped]

from .errors import InvalidExecutable
from .models import ExecutableMetadata, ExecutableTitleCandidate, MetadataTitleSource

_METADATA_FIELDS = {
    "ProductName": "product_name",
    "FileDescription": "file_description",
    "OriginalFilename": "original_filename",
    "CompanyName": "company_name",
    "InternalName": "internal_name",
    "ProductVersion": "product_version",
}
_TITLE_FIELDS: tuple[tuple[str, MetadataTitleSource], ...] = (
    ("product_name", "product_name"),
    ("file_description", "file_description"),
    ("internal_name", "internal_name"),
)


def read_executable_metadata(
    executable: Path,
    *,
    pe_loader: Callable[[str], object] | None = None,
) -> ExecutableMetadata:
    """Read PE version metadata and stable game-title candidates from ``executable``."""
    path = executable.expanduser().resolve(strict=False)
    _validate_executable(path)
    loader = pe_loader if pe_loader is not None else _load_pe
    try:
        pe = loader(str(path))
    except (OSError, pefile.PEFormatError) as error:
        raise InvalidExecutable(path, "is not a valid PE executable") from error

    try:
        _parse_resource_directory(pe)
        values = _version_values(pe)
    finally:
        _close_pe(pe)

    return ExecutableMetadata(
        executable=path,
        product_name=values["product_name"],
        file_description=values["file_description"],
        original_filename=values["original_filename"],
        company_name=values["company_name"],
        internal_name=values["internal_name"],
        product_version=values["product_version"],
        title_candidates=_title_candidates(path, values),
    )


def _load_pe(path: str) -> object:
    return pefile.PE(path, fast_load=True)


def _parse_resource_directory(pe: object) -> None:
    parser = getattr(pe, "parse_data_directories", None)
    if callable(parser):
        parser(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])


def _version_values(pe: object) -> dict[str, str | None]:
    values: dict[str, str | None] = {field: None for field in _METADATA_FIELDS.values()}
    for file_info_group in getattr(pe, "FileInfo", ()):
        entries = file_info_group if isinstance(file_info_group, list) else (file_info_group,)
        for file_info in entries:
            if _decode(getattr(file_info, "Key", None)) != "StringFileInfo":
                continue
            for table in getattr(file_info, "StringTable", ()):
                table_entries = getattr(table, "entries", {})
                if not isinstance(table_entries, Mapping):
                    continue
                for key, value in table_entries.items():
                    key_name = _decode(key)
                    if key_name is None:
                        continue
                    field = _METADATA_FIELDS.get(key_name)
                    decoded = _decode(value)
                    if field is not None and decoded is not None and values[field] is None:
                        values[field] = decoded
    return values


def _title_candidates(
    executable: Path,
    values: Mapping[str, str | None],
) -> tuple[ExecutableTitleCandidate, ...]:
    candidates: list[ExecutableTitleCandidate] = []
    seen: set[str] = set()
    for field, source in _TITLE_FIELDS:
        value = values[field]
        if value is not None:
            _append_title_candidate(candidates, seen, value, source)
    _append_title_candidate(candidates, seen, executable.stem, "executable_stem")
    return tuple(candidates)


def _append_title_candidate(
    candidates: list[ExecutableTitleCandidate],
    seen: set[str],
    value: str,
    source: MetadataTitleSource,
) -> None:
    normalized = value.casefold()
    if normalized not in seen:
        seen.add(normalized)
        candidates.append(ExecutableTitleCandidate(value=value, source=source))


def _decode(value: Any) -> str | None:
    if isinstance(value, bytes):
        for encoding in ("utf-8", "utf-16-le", "latin-1"):
            try:
                decoded = value.decode(encoding)
            except UnicodeDecodeError:
                continue
            cleaned = decoded.rstrip("\x00").strip()
            if cleaned:
                return cleaned
        return None
    if isinstance(value, str):
        cleaned = value.rstrip("\x00").strip()
        return cleaned or None
    return None


def _close_pe(pe: object) -> None:
    closer = getattr(pe, "close", None)
    if callable(closer):
        closer()


def _validate_executable(executable: Path) -> None:
    if not executable.exists():
        raise InvalidExecutable(executable, "path does not exist")
    if not executable.is_file():
        raise InvalidExecutable(executable, "path is not a file")
