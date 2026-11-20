from __future__ import annotations

from http.client import IncompleteRead
from pathlib import Path

import pytest

from steam_shortcuts import api
from steam_shortcuts.errors import ShortcutNameNotFound, SteamRunning, SteamStoreRequestFailed
from steam_shortcuts.models import (
    ProtonDbReport,
    ShortcutRequest,
    SteamLibraryArtwork,
    SteamStoreGame,
)
from steam_shortcuts.protondb import get_protondb_report
from steam_shortcuts.service import plan_shortcut_addition, shortcut_grid_artwork_id
from steam_shortcuts.vdf_store import serialize_shortcuts


def _steam_root_with_shortcut(tmp_path: Path, name: str = "Toy Shire") -> tuple[Path, int]:
    steam_root = tmp_path / "Steam"
    config_dir = steam_root / "userdata" / "123" / "config"
    config_dir.mkdir(parents=True)
    executable = tmp_path / "Games" / name / f"{name}.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    plan = plan_shortcut_addition(
        {"shortcuts": {}},
        ShortcutRequest(name=name, executable=executable),
    )
    assert plan.entry is not None
    (config_dir / "shortcuts.vdf").write_bytes(
        serialize_shortcuts({"shortcuts": {"0": plan.entry}})
    )
    return steam_root, plan.shortcut_id


def test_enrich_game_data_installs_steam_art_and_leaves_unrecommended_proton_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, shortcut_id = _steam_root_with_shortcut(tmp_path)
    config_dir = steam_root / "userdata" / "123" / "config"
    localconfig = config_dir / "localconfig.vdf"
    localconfig.write_text("existing proton settings stay untouched")
    localconfig_before = localconfig.read_bytes()
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    report = ProtonDbReport(
        app_id=2361460,
        tier="pending",
        best_reported_tier="borked",
        trending_tier="pending",
        confidence="inadequate",
        score=0.0,
        total_reports=1,
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(api, "get_protondb_report", lambda _: report, raising=False)
    monkeypatch.setattr(api, "download_steam_asset", lambda url: url.encode(), raising=False)

    result = api.enrich_game_data(
        name="Toy Shire",
        steam_root=steam_root,
        steam_id="123",
    )

    assert result.shortcut_id == shortcut_id
    assert result.steam_app_id == 2361460
    assert result.artwork_status == "installed"
    assert result.proton_status == "unchanged_no_version_recommendation"
    assert "Proton version recommendation" in result.proton_warning
    assert result.artwork_result is not None
    assert result.artwork_result.portrait_path is not None
    assert result.artwork_result.hero_path is not None
    assert result.artwork_result.logo_path is not None
    assert result.artwork_result.portrait_path.is_file()
    assert result.artwork_result.hero_path.is_file()
    assert result.artwork_result.logo_path.is_file()
    assert localconfig.read_bytes() == localconfig_before


def test_enrich_game_data_warns_on_missing_proton_data_but_still_installs_artwork(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, _ = _steam_root_with_shortcut(tmp_path)
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)

    def report_missing(_app_id: int):
        from steam_shortcuts.errors import ProtonDbRequestFailed

        raise ProtonDbRequestFailed("HTTP 404")

    monkeypatch.setattr(api, "get_protondb_report", report_missing, raising=False)
    monkeypatch.setattr(api, "download_steam_asset", lambda url: url.encode(), raising=False)

    result = api.enrich_game_data(name="Toy Shire", steam_root=steam_root, steam_id="123")

    assert result.artwork_status == "installed"
    assert result.proton_status == "unavailable"
    assert "HTTP 404" in result.proton_warning
    assert result.artwork_result is not None
    assert result.artwork_result.portrait_path is not None
    assert result.artwork_result.portrait_path.is_file()


def test_enrich_game_data_installs_art_after_incomplete_protondb_http_body(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, _ = _steam_root_with_shortcut(tmp_path)
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(api, "download_steam_asset", lambda url: url.encode(), raising=False)

    def partial_body(_app_id: int):
        def transport(_request):
            raise IncompleteRead(b"partial", 12)

        return get_protondb_report(2361460, transport=transport)

    monkeypatch.setattr(api, "get_protondb_report", partial_body, raising=False)

    result = api.enrich_game_data(name="Toy Shire", steam_root=steam_root, steam_id="123")

    assert result.proton_status == "unavailable"
    assert "incomplete HTTP response" in result.proton_warning
    assert result.artwork_status == "installed"
    assert result.artwork_result is not None
    assert result.artwork_result.portrait_path is not None
    assert result.artwork_result.portrait_path.is_file()


def test_enrich_game_data_rechecks_steam_after_download_before_writing_art(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, _ = _steam_root_with_shortcut(tmp_path)
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    ensure_calls = 0

    def ensure_steam_closed() -> None:
        nonlocal ensure_calls
        ensure_calls += 1
        if ensure_calls > 1:
            raise SteamRunning()

    monkeypatch.setattr(api, "ensure_steam_not_running", ensure_steam_closed)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(api, "get_protondb_report", lambda _: None, raising=False)
    monkeypatch.setattr(api, "download_steam_asset", lambda url: url.encode(), raising=False)

    with pytest.raises(SteamRunning):
        api.enrich_game_data(name="Toy Shire", steam_root=steam_root, steam_id="123")

    grid_dir = steam_root / "userdata" / "123" / "config" / "grid"
    assert ensure_calls == 2
    assert grid_dir.is_dir()
    assert not tuple(grid_dir.iterdir())


def test_enrich_game_data_requires_one_exact_existing_shortcut_name(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, _ = _steam_root_with_shortcut(tmp_path)
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: pytest.fail("must stop before online search when no shortcut matches"),
        raising=False,
    )

    with pytest.raises(ShortcutNameNotFound, match="No exact shortcut named 'Unknown Game'"):
        api.enrich_game_data(name="Unknown Game", steam_root=steam_root, steam_id="123")


def test_enrich_game_data_dry_run_does_not_download_or_write_artwork(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, _ = _steam_root_with_shortcut(tmp_path)
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(
        api,
        "get_protondb_report",
        lambda _: ProtonDbReport(2361460, "pending", "borked", "pending", "inadequate", 0, 1),
        raising=False,
    )
    monkeypatch.setattr(
        api,
        "download_steam_asset",
        lambda _: pytest.fail("dry-run must not download art"),
        raising=False,
    )

    result = api.enrich_game_data(
        name="Toy Shire",
        steam_root=steam_root,
        steam_id="123",
        dry_run=True,
    )

    grid_dir = steam_root / "userdata" / "123" / "config" / "grid"
    assert result.artwork_status == "planned"
    assert result.artwork_result is None
    assert not grid_dir.exists()


def test_enrich_game_data_preserves_existing_art_and_installs_missing_slots(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, shortcut_id = _steam_root_with_shortcut(tmp_path)
    grid_dir = steam_root / "userdata" / "123" / "config" / "grid"
    grid_dir.mkdir()
    portrait = grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}p.png"
    portrait.write_bytes(b"user artwork")
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(api, "download_steam_asset", lambda url: url.encode(), raising=False)

    def no_proton_report(_app_id: int):
        from steam_shortcuts.errors import ProtonDbRequestFailed

        raise ProtonDbRequestFailed("HTTP 404")

    monkeypatch.setattr(api, "get_protondb_report", no_proton_report, raising=False)

    result = api.enrich_game_data(name="Toy Shire", steam_root=steam_root, steam_id="123")

    assert result.artwork_status == "partially_installed"
    assert result.conflicting_paths == (portrait,)
    assert portrait.read_bytes() == b"user artwork"
    assert {kind for kind, _ in result.artwork_paths} == {"hero", "logo"}
    assert (grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}_hero.jpg").is_file()
    assert (grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}_logo.png").is_file()


def test_enrich_game_data_reports_no_new_paths_when_all_slots_are_already_present(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, shortcut_id = _steam_root_with_shortcut(tmp_path)
    grid_dir = steam_root / "userdata" / "123" / "config" / "grid"
    grid_dir.mkdir()
    existing_paths = (
        grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}p.png",
        grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}_hero.jpeg",
        grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}_logo.jpg",
    )
    for path in existing_paths:
        path.write_bytes(b"keep this artwork")
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(api, "get_protondb_report", lambda _: None, raising=False)
    monkeypatch.setattr(
        api,
        "download_steam_asset",
        lambda _: pytest.fail("fully configured art slots must not be downloaded"),
        raising=False,
    )

    result = api.enrich_game_data(name="Toy Shire", steam_root=steam_root, steam_id="123")

    assert result.artwork_status == "preserved_existing"
    assert result.artwork_paths == ()
    assert result.conflicting_paths == existing_paths
    assert all(path.read_bytes() == b"keep this artwork" for path in existing_paths)


def test_enrich_game_data_dry_run_marks_all_existing_slots_as_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, shortcut_id = _steam_root_with_shortcut(tmp_path)
    grid_dir = steam_root / "userdata" / "123" / "config" / "grid"
    grid_dir.mkdir()
    existing_paths = (
        grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}p.png",
        grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}_hero.jpeg",
        grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}_logo.jpg",
    )
    for path in existing_paths:
        path.write_bytes(b"keep this artwork")
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(api, "get_protondb_report", lambda _: None, raising=False)

    result = api.enrich_game_data(
        name="Toy Shire",
        steam_root=steam_root,
        steam_id="123",
        dry_run=True,
    )

    assert result.artwork_status == "preserved_existing"
    assert result.artwork_paths == ()
    assert result.conflicting_paths == existing_paths
    assert "already have images" in (result.artwork_warning or "")


def test_enrich_game_data_does_not_claim_overwrite_when_all_downloads_fail(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, shortcut_id = _steam_root_with_shortcut(tmp_path)
    grid_dir = steam_root / "userdata" / "123" / "config" / "grid"
    grid_dir.mkdir()
    existing_paths = (
        grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}p.png",
        grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}_hero.jpeg",
        grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}_logo.jpg",
    )
    for path in existing_paths:
        path.write_bytes(b"keep this artwork")
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(api, "get_protondb_report", lambda _: None, raising=False)

    def failed_download(_url: str) -> bytes:
        raise SteamStoreRequestFailed("HTTP 503")

    monkeypatch.setattr(api, "download_steam_asset", failed_download, raising=False)

    result = api.enrich_game_data(
        name="Toy Shire",
        steam_root=steam_root,
        steam_id="123",
        overwrite_artwork=True,
    )

    assert result.artwork_status == "preserved_existing_download_failed"
    assert result.artwork_paths == ()
    assert result.conflicting_paths == existing_paths
    assert len(result.artwork_failed_paths) == 3
    assert "Pass --overwrite-artwork" not in (result.artwork_warning or "")
    assert all(path.read_bytes() == b"keep this artwork" for path in existing_paths)


def test_enrich_game_data_preserves_alternate_artwork_when_overwriting(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, shortcut_id = _steam_root_with_shortcut(tmp_path)
    grid_dir = steam_root / "userdata" / "123" / "config" / "grid"
    grid_dir.mkdir()
    existing_portrait = grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}p.png"
    existing_portrait.write_bytes(b"old portrait")
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(api, "get_protondb_report", lambda _: None, raising=False)
    monkeypatch.setattr(api, "download_steam_asset", lambda url: url.encode(), raising=False)

    result = api.enrich_game_data(
        name="Toy Shire",
        steam_root=steam_root,
        steam_id="123",
        overwrite_artwork=True,
    )

    assert result.artwork_status == "partially_installed"
    assert result.conflicting_paths == (existing_portrait,)
    assert "conflicted" in (result.artwork_warning or "")
    assert result.artwork_result is not None
    assert result.artwork_result.backup_paths == ()
    assert existing_portrait.read_bytes() == b"old portrait"


def test_enrich_game_data_reports_race_conflict_without_claiming_all_art_was_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, shortcut_id = _steam_root_with_shortcut(tmp_path)
    grid_dir = steam_root / "userdata" / "123" / "config" / "grid"
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    portrait = grid_dir / f"{shortcut_grid_artwork_id(shortcut_id)}p.jpg"
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)

    def create_concurrent_portrait(url: str) -> bytes:
        if url == artwork.portrait_url:
            grid_dir.mkdir(parents=True, exist_ok=True)
            portrait.write_bytes(b"another writer's portrait")
        return url.encode()

    def no_proton(_app_id: int):
        from steam_shortcuts.errors import ProtonDbRequestFailed

        raise ProtonDbRequestFailed("unavailable")

    monkeypatch.setattr(api, "download_steam_asset", create_concurrent_portrait, raising=False)
    monkeypatch.setattr(api, "get_protondb_report", no_proton, raising=False)

    result = api.enrich_game_data(name="Toy Shire", steam_root=steam_root, steam_id="123")

    assert result.artwork_status == "partially_installed"
    assert result.conflicting_paths == (portrait,)
    assert portrait.read_bytes() == b"another writer's portrait"
    assert {kind for kind, _ in result.artwork_paths} == {"hero", "logo"}
    assert "conflicted" in (result.artwork_warning or "")


def test_enrich_game_data_keeps_proton_report_when_steam_art_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, _ = _steam_root_with_shortcut(tmp_path)
    report = ProtonDbReport(
        app_id=2361460,
        tier="gold",
        best_reported_tier="platinum",
        trending_tier="gold",
        confidence="strong",
        score=0.8,
        total_reports=12,
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )

    def unavailable_artwork(_app_id: int) -> SteamLibraryArtwork:
        raise SteamStoreRequestFailed("HTTP 503")

    monkeypatch.setattr(api, "get_steam_library_artwork", unavailable_artwork, raising=False)
    monkeypatch.setattr(api, "get_protondb_report", lambda _: report, raising=False)

    result = api.enrich_game_data(name="Toy Shire", steam_root=steam_root, steam_id="123")

    assert result.artwork_status == "unavailable"
    assert "HTTP 503" in (result.artwork_warning or "")
    assert result.proton_report == report
    assert result.proton_status == "unchanged_no_version_recommendation"


def test_enrich_game_data_keeps_proton_report_when_all_image_downloads_fail(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root, _ = _steam_root_with_shortcut(tmp_path)
    artwork = SteamLibraryArtwork(
        app_id=2361460,
        portrait_url="https://shared.fastly.steamstatic.com/portrait.jpg",
        hero_url="https://shared.fastly.steamstatic.com/hero.jpg",
        logo_url="https://shared.fastly.steamstatic.com/logo.png",
    )
    report = ProtonDbReport(
        app_id=2361460,
        tier="pending",
        best_reported_tier="borked",
        trending_tier="pending",
        confidence="inadequate",
        score=0.0,
        total_reports=1,
    )
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)
    monkeypatch.setattr(
        api,
        "search_steam_store_games",
        lambda _: (SteamStoreGame(2361460, "Toy Shire", "app"),),
        raising=False,
    )
    monkeypatch.setattr(api, "get_steam_library_artwork", lambda _: artwork, raising=False)
    monkeypatch.setattr(api, "get_protondb_report", lambda _: report, raising=False)

    def failed_download(_url: str) -> bytes:
        raise SteamStoreRequestFailed("HTTP 503")

    monkeypatch.setattr(api, "download_steam_asset", failed_download, raising=False)

    result = api.enrich_game_data(name="Toy Shire", steam_root=steam_root, steam_id="123")

    assert result.artwork_status == "unavailable"
    assert result.artwork_paths == ()
    assert len(result.artwork_failed_paths) == 3
    assert "HTTP 503" in (result.artwork_warning or "")
    assert result.proton_report == report
    assert result.proton_status == "unchanged_no_version_recommendation"
    grid_dir = steam_root / "userdata" / "123" / "config" / "grid"
    assert grid_dir.is_dir()
    assert not tuple(grid_dir.iterdir())
