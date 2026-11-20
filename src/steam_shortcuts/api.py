"""Public library API for local Steam shortcut management."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .archive import extract_archive, inspect_archive
from .artwork import artwork_targets, find_existing_artwork_paths, install_artwork
from .discovery import discover_steam_root, list_profile_ids, select_profile
from .errors import (
    ArtworkAlreadyExists,
    ArtworkWriteFailed,
    InvalidArchive,
    ProtonDbRequestFailed,
    ShortcutNameAmbiguous,
    ShortcutNameNotFound,
    ShortcutNotFound,
    SteamStoreRequestFailed,
)
from .models import (
    ArchiveInspection,
    ArtworkInstallResult,
    GameEnrichmentResult,
    ProtonDbReport,
    ShortcutRequest,
    ShortcutResult,
    SteamGridDbArtwork,
    SteamProfile,
)
from .process import ensure_steam_not_running
from .protondb import get_protondb_report
from .service import (
    ShortcutAdditionPlan,
    add_shortcut_to_profile,
    plan_shortcut_addition,
    to_unsigned_int32,
)
from .steam_assets import download_steam_asset, get_steam_library_artwork
from .steam_store import search_steam_store_games
from .steamgriddb import (
    SteamGridDbArtworkClient,
    steamgriddb_client_from_environment,
)
from .vdf_store import VdfMap, VdfValue, load_shortcuts

_ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tar")


@dataclass(frozen=True, slots=True)
class SteamInstallation:
    """A discovered Steam root and the numeric user profiles beneath it."""

    steam_root: Path
    profile_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShortcutPreview:
    """An addition plan resolved to one Steam profile without a file write."""

    steam_root: Path
    profile: SteamProfile
    plan: ShortcutAdditionPlan


@dataclass(frozen=True, slots=True)
class ArchiveShortcutPreview:
    """A non-mutating archive extraction and shortcut-addition plan."""

    steam_root: Path
    profile: SteamProfile
    inspection: ArchiveInspection
    plan: ShortcutAdditionPlan


@dataclass(frozen=True, slots=True)
class ArchiveShortcutResult:
    """A completed archive extraction and verified shortcut mutation."""

    inspection: ArchiveInspection
    shortcut: ShortcutResult


@dataclass(frozen=True, slots=True)
class ShortcutListing:
    """A shortcut shown by the list API."""

    index: str
    name: str
    executable: str
    app_id: int | None


@dataclass(frozen=True, slots=True)
class ArtworkPreview:
    """Selected remote artwork and the exact local Steam paths it would occupy."""

    steam_root: Path
    profile: SteamProfile
    artwork: SteamGridDbArtwork
    grid_dir: Path
    portrait_path: Path
    hero_path: Path
    logo_path: Path
    conflicting_paths: tuple[Path, ...]


def detect_steam(steam_root: Path | None = None) -> SteamInstallation:
    """Discover Steam and return its selectable local profiles."""
    root = discover_steam_root(steam_root)
    return SteamInstallation(steam_root=root, profile_ids=list_profile_ids(root))


def list_shortcuts(
    *,
    steam_root: Path | None = None,
    steam_id: str | None = None,
) -> tuple[SteamProfile, tuple[ShortcutListing, ...]]:
    """List non-Steam shortcuts from exactly one selected profile."""
    installation = detect_steam(steam_root)
    profile = select_profile(installation.steam_root, steam_id)
    root = load_shortcuts(profile.shortcuts_path)
    shortcuts = _shortcut_map(root)
    listings = tuple(
        _listing(index, entry)
        for index, entry in sorted(shortcuts.items(), key=_shortcut_sort_key)
        if isinstance(entry, dict)
    )
    return profile, listings


def enrich_game_data(
    *,
    name: str,
    steam_root: Path | None = None,
    steam_id: str | None = None,
    dry_run: bool = False,
    overwrite_artwork: bool = False,
) -> GameEnrichmentResult:
    """Enrich one uniquely named existing shortcut with official Steam art and ProtonDB data.

    Steam's public app-info endpoint supplies official library images without an
    API key. ProtonDB summaries do not identify an exact Proton tool/version, so
    this operation never writes compatibility settings and explains that choice.
    """
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("shortcut name must not be blank")

    installation = detect_steam(steam_root)
    ensure_steam_not_running()
    profile, shortcuts = list_shortcuts(
        steam_root=installation.steam_root,
        steam_id=steam_id,
    )
    matches = tuple(
        shortcut
        for shortcut in shortcuts
        if shortcut.name.strip().casefold() == normalized_name.casefold()
    )
    if not matches:
        raise ShortcutNameNotFound(normalized_name, profile.profile_id)
    if len(matches) > 1:
        ids = tuple(match.app_id for match in matches if match.app_id is not None)
        raise ShortcutNameAmbiguous(normalized_name, ids)
    shortcut = next(iter(matches))
    if shortcut.app_id is None:
        raise SteamStoreRequestFailed(
            f"Shortcut '{normalized_name}' has no valid Steam shortcut ID"
        )

    store_candidates = search_steam_store_games(normalized_name)
    exact_games = tuple(
        game
        for game in store_candidates
        if (
            game.kind.casefold() == "app"
            and game.name.strip().casefold() == normalized_name.casefold()
        )
    )
    if len(exact_games) != 1:
        names = ", ".join(
            f"{game.name} ({game.kind}, AppID {game.app_id})" for game in store_candidates
        ) or "none"
        raise SteamStoreRequestFailed(
            f"Expected one exact Steam Store game for '{normalized_name}'; candidates: {names}"
        )
    steam_game = exact_games[0]

    proton_report: ProtonDbReport | None = None
    proton_status = "unavailable"
    proton_warning = (
        "No ProtonDB compatibility summary was available; no Proton setting was changed."
    )
    try:
        proton_report = get_protondb_report(steam_game.app_id)
    except ProtonDbRequestFailed as error:
        proton_report = None
        proton_status = "unavailable"
        proton_warning = (
            f"No ProtonDB compatibility summary was available ({error}); "
            "no Proton setting was changed."
        )
    if proton_report is not None:
        proton_status = "unchanged_no_version_recommendation"
        if proton_report.confidence.casefold() in {"inadequate", "low"}:
            proton_warning = (
                f"ProtonDB evidence is weak ({proton_report.confidence} confidence, "
                f"{proton_report.total_reports} reports); no exact Proton version "
                "recommendation is available. Existing Steam compatibility settings "
                "were left unchanged."
            )
        else:
            proton_warning = (
                "ProtonDB's summary does not identify an exact Proton tool/version; "
                "existing Steam compatibility settings were left unchanged."
            )

    artwork_paths: tuple[tuple[str, Path], ...] = ()
    conflicting_paths: tuple[Path, ...] = ()
    artwork_warning: str | None = None
    artwork_result: ArtworkInstallResult | None = None
    try:
        artwork = get_steam_library_artwork(steam_game.app_id)
    except SteamStoreRequestFailed as error:
        artwork_status = "unavailable"
        artwork_warning = str(error)
    else:
        grid_dir = profile.shortcuts_path.parent / "grid"
        all_paths = artwork_targets(grid_dir, shortcut.app_id, artwork)
        artwork_paths = tuple(
            (kind, path)
            for kind, path, url in all_paths
            if isinstance(url, str) and url
        )
        conflicting_paths = find_existing_artwork_paths(path for _, path in artwork_paths)
        requested_stems = {path.with_suffix("") for _, path in artwork_paths}
        existing_stems = {path.with_suffix("") for path in conflicting_paths}
        all_slots_existing = bool(requested_stems) and requested_stems <= existing_stems
        if not artwork_paths:
            artwork_status = "unavailable"
            artwork_warning = "Steam did not expose compatible portrait, hero, or logo assets."
        elif dry_run:
            artwork_status = (
                "planned_overwrite"
                if conflicting_paths and overwrite_artwork
                else "preserved_existing"
                if all_slots_existing
                else "planned_partial"
                if conflicting_paths
                else "planned"
            )
            if all_slots_existing and not overwrite_artwork:
                artwork_warning = (
                    "All artwork slots already have images and no files would be changed. "
                    "Pass --overwrite-artwork to replace same-format files."
                )
            elif conflicting_paths and not overwrite_artwork:
                artwork_warning = (
                    "Existing artwork slots will be preserved; missing slots will be filled. "
                    "Pass --overwrite-artwork to replace same-format files."
                )
            if conflicting_paths and not overwrite_artwork:
                artwork_paths = tuple(
                    (kind, path)
                    for kind, path in artwork_paths
                    if path.with_suffix("") not in existing_stems
                )
        else:
            try:
                artwork_result = install_artwork(
                    grid_dir=grid_dir,
                    shortcut_id=shortcut.app_id,
                    artwork=artwork,
                    downloader=download_steam_asset,
                    overwrite=overwrite_artwork,
                    allow_missing_assets=True,
                    before_commit=ensure_steam_not_running,
                )
            except ArtworkAlreadyExists as error:
                artwork_status = "preserved_existing"
                artwork_paths = ()
                conflicting_paths = error.paths
                artwork_warning = (
                    "All available artwork slots already have images, so they were preserved. "
                    "Pass --overwrite-artwork to replace them."
                )
            except SteamStoreRequestFailed as error:
                artwork_status = "unavailable"
                artwork_paths = ()
                artwork_warning = (
                    "Steam artwork download failed without changing grid files "
                    f"({error})."
                )
            except ArtworkWriteFailed as error:
                if error.reason != "all requested artwork assets were unavailable":
                    raise
                artwork_status = "unavailable"
                artwork_paths = ()
                artwork_warning = str(error)
            else:
                conflicting_paths = artwork_result.conflicting_paths
                installed_paths = (
                    ("portrait", artwork_result.portrait_path),
                    ("hero", artwork_result.hero_path),
                    ("logo", artwork_result.logo_path),
                )
                artwork_paths = tuple(
                    (kind, path) for kind, path in installed_paths if path is not None
                )
                conflict_stems = {path.with_suffix("") for path in conflicting_paths}
                if artwork_paths:
                    artwork_status = (
                        "partially_installed"
                        if conflicting_paths or artwork_result.failed_paths
                        else "installed"
                    )
                elif artwork_result.failed_paths:
                    artwork_status = (
                        "preserved_existing_download_failed"
                        if conflicting_paths
                        else "unavailable"
                    )
                elif requested_stems and requested_stems <= conflict_stems:
                    artwork_status = "preserved_existing"
                elif conflicting_paths:
                    artwork_status = "conflict"
                else:
                    artwork_status = "unavailable"
                if conflicting_paths:
                    if artwork_status == "preserved_existing_download_failed":
                        artwork_warning = (
                            "Artwork downloads failed; existing images were left untouched. "
                            "Retry later to fill the missing slots."
                        )
                    elif artwork_status == "preserved_existing":
                        if overwrite_artwork:
                            artwork_warning = (
                                "An overwrite conflict prevented updates; existing artwork "
                                "was preserved."
                            )
                        else:
                            artwork_warning = (
                                "All available artwork slots already had images, so they were "
                                "preserved. Pass --overwrite-artwork to replace them."
                            )
                    else:
                        artwork_warning = (
                            "Some artwork slots conflicted with existing files; available "
                            "non-conflicting slots were installed."
                        )
                if artwork_result.warning:
                    artwork_warning = (
                        f"{artwork_warning} {artwork_result.warning}"
                        if artwork_warning
                        else artwork_result.warning
                    )
                if artwork_result.failed_paths:
                    failed_warning = (
                        "Some artwork slots could not be downloaded or written; see failed_paths."
                    )
                    artwork_warning = (
                        f"{artwork_warning} {failed_warning}"
                        if artwork_warning
                        else failed_warning
                    )
                if len(artwork_paths) < 3 and not artwork_result.failed_paths:
                    missing_warning = (
                        "Some Steam library artwork assets were unavailable; "
                        "the available images were installed."
                    )
                    if artwork_warning is None:
                        artwork_warning = missing_warning

    return GameEnrichmentResult(
        shortcut_name=shortcut.name,
        shortcut_id=shortcut.app_id,
        profile_id=profile.profile_id,
        steam_app_id=steam_game.app_id,
        steam_game_name=steam_game.name,
        proton_report=proton_report,
        proton_status=proton_status,
        proton_warning=proton_warning,
        artwork_status=artwork_status,
        artwork_paths=artwork_paths,
        conflicting_paths=conflicting_paths,
        artwork_warning=artwork_warning,
        artwork_result=artwork_result,
        artwork_failed_paths=(
            artwork_result.failed_paths if artwork_result is not None else ()
        ),
    )


def preview_shortcut(
    *,
    name: str,
    executable: Path,
    start_dir: Path | None = None,
    launch_options: str = "",
    icon: Path | None = None,
    tags: Iterable[str] = (),
    steam_root: Path | None = None,
    steam_id: str | None = None,
) -> ShortcutPreview:
    """Resolve and validate an add operation without changing Steam files."""
    installation = detect_steam(steam_root)
    ensure_steam_not_running()
    profile = select_profile(installation.steam_root, steam_id)
    request = ShortcutRequest(
        name=name,
        executable=executable,
        start_dir=start_dir,
        launch_options=launch_options,
        icon=icon,
        tags=tuple(tags),
    )
    plan = plan_shortcut_addition(load_shortcuts(profile.shortcuts_path), request)
    return ShortcutPreview(steam_root=installation.steam_root, profile=profile, plan=plan)


def add_shortcut(
    *,
    name: str,
    executable: Path,
    start_dir: Path | None = None,
    launch_options: str = "",
    icon: Path | None = None,
    tags: Iterable[str] = (),
    steam_root: Path | None = None,
    steam_id: str | None = None,
) -> ShortcutResult:
    """Safely add a non-Steam shortcut and return its verified result."""
    tag_values = tuple(tags)
    preview = preview_shortcut(
        name=name,
        executable=executable,
        start_dir=start_dir,
        launch_options=launch_options,
        icon=icon,
        tags=tag_values,
        steam_root=steam_root,
        steam_id=steam_id,
    )
    request = ShortcutRequest(
        name=name,
        executable=executable,
        start_dir=start_dir,
        launch_options=launch_options,
        icon=icon,
        tags=tag_values,
    )
    return add_shortcut_to_profile(
        preview.profile.shortcuts_path,
        preview.profile.profile_id,
        request,
    )


def preview_archive_shortcut(
    *,
    name: str,
    archive: Path,
    extract_to: Path | None = None,
    executable_relative: PurePosixPath | None = None,
    launch_options: str = "",
    icon: Path | None = None,
    tags: Iterable[str] = (),
    steam_root: Path | None = None,
    steam_id: str | None = None,
) -> ArchiveShortcutPreview:
    """Plan a tar extraction and shortcut addition without changing local files."""
    installation = detect_steam(steam_root)
    ensure_steam_not_running()
    profile = select_profile(installation.steam_root, steam_id)
    destination = _resolve_archive_destination(archive, extract_to)
    inspection = inspect_archive(
        archive,
        extract_to=destination,
        executable_relative=executable_relative,
    )
    request = ShortcutRequest(
        name=name,
        executable=inspection.executable,
        launch_options=launch_options,
        icon=icon,
        tags=tuple(tags),
    )
    plan = plan_shortcut_addition(
        load_shortcuts(profile.shortcuts_path),
        request,
        require_existing_executable=False,
    )
    return ArchiveShortcutPreview(
        steam_root=installation.steam_root,
        profile=profile,
        inspection=inspection,
        plan=plan,
    )


def add_shortcut_from_archive(
    *,
    name: str,
    archive: Path,
    extract_to: Path | None = None,
    executable_relative: PurePosixPath | None = None,
    launch_options: str = "",
    icon: Path | None = None,
    tags: Iterable[str] = (),
    steam_root: Path | None = None,
    steam_id: str | None = None,
) -> ArchiveShortcutResult:
    """Extract a tarred game directory and register its selected executable."""
    tag_values = tuple(tags)
    preview = preview_archive_shortcut(
        name=name,
        archive=archive,
        extract_to=extract_to,
        executable_relative=executable_relative,
        launch_options=launch_options,
        icon=icon,
        tags=tag_values,
        steam_root=steam_root,
        steam_id=steam_id,
    )
    extract_archive(preview.inspection)
    ensure_steam_not_running()
    request = ShortcutRequest(
        name=name,
        executable=preview.inspection.executable,
        launch_options=launch_options,
        icon=icon,
        tags=tag_values,
    )
    shortcut = add_shortcut_to_profile(
        preview.profile.shortcuts_path,
        preview.profile.profile_id,
        request,
    )
    return ArchiveShortcutResult(inspection=preview.inspection, shortcut=shortcut)


def preview_steamgriddb_artwork(
    *,
    steamgriddb_game_id: int,
    shortcut_id: int,
    steam_root: Path | None = None,
    steam_id: str | None = None,
    client: SteamGridDbArtworkClient | None = None,
) -> ArtworkPreview:
    """Verify a local shortcut and resolve its selected SteamGridDB artwork."""
    preview, _ = _resolve_steamgriddb_artwork(
        steamgriddb_game_id=steamgriddb_game_id,
        shortcut_id=shortcut_id,
        steam_root=steam_root,
        steam_id=steam_id,
        client=client,
    )
    return preview


def install_steamgriddb_artwork(
    *,
    steamgriddb_game_id: int,
    shortcut_id: int,
    steam_root: Path | None = None,
    steam_id: str | None = None,
    overwrite: bool = False,
    client: SteamGridDbArtworkClient | None = None,
) -> ArtworkInstallResult:
    """Install selected SteamGridDB artwork for one verified local shortcut."""
    preview, resolved_client = _resolve_steamgriddb_artwork(
        steamgriddb_game_id=steamgriddb_game_id,
        shortcut_id=shortcut_id,
        steam_root=steam_root,
        steam_id=steam_id,
        client=client,
    )
    return install_artwork(
        grid_dir=preview.grid_dir,
        shortcut_id=shortcut_id,
        artwork=preview.artwork,
        downloader=resolved_client.download_asset,
        overwrite=overwrite,
        before_commit=ensure_steam_not_running,
    )


def _resolve_steamgriddb_artwork(
    *,
    steamgriddb_game_id: int,
    shortcut_id: int,
    steam_root: Path | None,
    steam_id: str | None,
    client: SteamGridDbArtworkClient | None,
) -> tuple[ArtworkPreview, SteamGridDbArtworkClient]:
    installation = detect_steam(steam_root)
    ensure_steam_not_running()
    profile = select_profile(installation.steam_root, steam_id)
    _require_shortcut(profile, shortcut_id)
    resolved_client = client if client is not None else steamgriddb_client_from_environment()
    artwork = resolved_client.get_artwork(steamgriddb_game_id)
    grid_dir = profile.shortcuts_path.parent / "grid"
    paths_by_kind = {
        kind: path for kind, path, _ in artwork_targets(grid_dir, shortcut_id, artwork)
    }
    portrait_path = paths_by_kind["portrait"]
    hero_path = paths_by_kind["hero"]
    logo_path = paths_by_kind["logo"]
    paths = (portrait_path, hero_path, logo_path)
    return (
        ArtworkPreview(
            steam_root=installation.steam_root,
            profile=profile,
            artwork=artwork,
            grid_dir=grid_dir,
            portrait_path=portrait_path,
            hero_path=hero_path,
            logo_path=logo_path,
            conflicting_paths=find_existing_artwork_paths(paths),
        ),
        resolved_client,
    )


def _require_shortcut(profile: SteamProfile, shortcut_id: int) -> None:
    shortcuts = _shortcut_map(load_shortcuts(profile.shortcuts_path))
    for entry in shortcuts.values():
        if not isinstance(entry, dict):
            continue
        raw_app_id = entry.get("appid")
        if not isinstance(raw_app_id, int) or isinstance(raw_app_id, bool):
            continue
        try:
            app_id = to_unsigned_int32(raw_app_id)
        except ValueError:
            continue
        if app_id == shortcut_id:
            return
    raise ShortcutNotFound(shortcut_id, profile.profile_id)


def _resolve_archive_destination(archive: Path, extract_to: Path | None) -> Path:
    destination = extract_to if extract_to is not None else Path.cwd() / _archive_stem(archive)
    resolved = destination.expanduser().resolve(strict=False)
    if not resolved.parent.is_dir():
        raise InvalidArchive(archive, f"destination parent is not a directory: {resolved.parent}")
    if resolved.exists() or resolved.is_symlink():
        raise InvalidArchive(archive, f"destination already exists: {resolved}")
    return resolved


def _archive_stem(archive: Path) -> str:
    name = archive.name
    lowered = name.casefold()
    for suffix in _ARCHIVE_SUFFIXES:
        if lowered.endswith(suffix):
            return name[: -len(suffix)]
    return archive.stem


def _shortcut_map(root: VdfMap) -> dict[str, VdfValue]:
    shortcuts = root["shortcuts"]
    if not isinstance(shortcuts, dict):
        raise ValueError("'shortcuts' must be a mapping")
    return shortcuts


def _listing(index: str, entry: dict[str, VdfValue]) -> ShortcutListing:
    name = entry.get("AppName", entry.get("appname", ""))
    executable = entry.get("Exe", entry.get("exe", ""))
    raw_app_id = entry.get("appid")
    app_id = (
        to_unsigned_int32(raw_app_id)
        if isinstance(raw_app_id, int) and not isinstance(raw_app_id, bool)
        else None
    )
    return ShortcutListing(
        index=index,
        name=name if isinstance(name, str) else "",
        executable=_unquote(executable) if isinstance(executable, str) else "",
        app_id=app_id,
    )


def _shortcut_sort_key(item: tuple[str, VdfValue]) -> tuple[int, int | str]:
    index, _ = item
    return (0, int(index)) if index.isdecimal() else (1, index)


def _unquote(value: str) -> str:
    return value.strip().removeprefix('"').removesuffix('"')
