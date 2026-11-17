import io
import json
import tarfile
from pathlib import Path

from steam_shortcuts import api
from steam_shortcuts.cli import main
from steam_shortcuts.models import (
    ArtworkInstallResult,
    ExecutableMetadata,
    ExecutableTitleCandidate,
    ProtonDbReport,
    SteamGridDbArtwork,
    SteamGridDbGame,
    SteamProfile,
    SteamStoreGame,
)
from steam_shortcuts.vdf_store import load_shortcuts, serialize_shortcuts


def _steam_profile(root: Path, profile_id: str = "123") -> Path:
    shortcuts_path = root / "userdata" / profile_id / "config" / "shortcuts.vdf"
    shortcuts_path.parent.mkdir(parents=True)
    shortcuts_path.write_bytes(serialize_shortcuts({"shortcuts": {}}))
    return shortcuts_path


def _write_tar(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path


def test_detect_reports_explicit_steam_root_as_json(tmp_path: Path, capsys) -> None:
    steam_root = tmp_path / "Steam"
    _steam_profile(steam_root)

    assert main(["detect", "--steam-root", str(steam_root), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"profiles": ["123"], "steam_root": str(steam_root.resolve())}


def test_list_displays_shortcuts_for_selected_profile(tmp_path: Path, capsys) -> None:
    steam_root = tmp_path / "Steam"
    shortcuts_path = _steam_profile(steam_root)
    shortcuts_path.write_bytes(
        serialize_shortcuts(
            {"shortcuts": {"0": {"appid": -1, "AppName": "Existing", "Exe": '"/game"'}}}
        )
    )

    assert main(["list", "--steam-root", str(steam_root), "--steam-id", "123", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["profile_id"] == "123"
    assert payload["shortcuts"] == [
        {"app_id": 4_294_967_295, "executable": "/game", "index": "0", "name": "Existing"}
    ]


def test_add_dry_run_returns_plan_without_mutating_vdf(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    steam_root = tmp_path / "Steam"
    shortcuts_path = _steam_profile(steam_root)
    executable = tmp_path / "game.exe"
    executable.touch()
    original = shortcuts_path.read_bytes()
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)

    assert (
        main(
            [
                "add",
                "--steam-root",
                str(steam_root),
                "--steam-id",
                "123",
                "--name",
                "My Game",
                "--exe",
                str(executable),
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "added"
    assert payload["dry_run"] is True
    assert shortcuts_path.read_bytes() == original
    assert not list(shortcuts_path.parent.glob("shortcuts.vdf.bak.*"))


def test_add_returns_verified_result_as_json(tmp_path: Path, capsys, monkeypatch) -> None:
    steam_root = tmp_path / "Steam"
    shortcuts_path = _steam_profile(steam_root)
    executable = tmp_path / "game.exe"
    executable.touch()
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)

    assert (
        main(
            [
                "add",
                "--steam-root",
                str(steam_root),
                "--steam-id",
                "123",
                "--name",
                "My Game",
                "--exe",
                str(executable),
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "added"
    assert payload["profile_id"] == "123"
    assert payload["shortcuts_path"] == str(shortcuts_path)
    assert payload["backup_path"].startswith(str(shortcuts_path) + ".bak.")
    assert Path(payload["backup_path"]).is_file()
    assert load_shortcuts(shortcuts_path)["shortcuts"]["0"]["AppName"] == "My Game"


def test_cli_returns_nonzero_and_concise_error_for_domain_failure(capsys) -> None:
    assert main(["detect", "--steam-root", "/definitely/not/steam"]) == 2

    captured = capsys.readouterr()
    assert "Steam installation was not found" in captured.err
    assert "Traceback" not in captured.err


def test_archive_preview_selects_a_future_executable_without_extracting(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root = tmp_path / "Steam"
    _steam_profile(steam_root)
    archive = _write_tar(tmp_path / "Game.tar", {"Game/Game.exe": b"game"})
    destination = tmp_path / "Deck" / "Game"
    destination.parent.mkdir()
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)

    preview = api.preview_archive_shortcut(
        name="Game",
        archive=archive,
        extract_to=destination,
        steam_root=steam_root,
        steam_id="123",
    )

    assert preview.inspection.executable == destination / "Game.exe"
    assert preview.plan.status == "added"
    assert not destination.exists()


def test_add_shortcut_from_archive_extracts_then_writes_the_final_executable(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root = tmp_path / "Steam"
    shortcuts_path = _steam_profile(steam_root)
    archive = _write_tar(tmp_path / "Game.tar", {"Game/Game.exe": b"game"})
    destination = tmp_path / "Deck" / "Game"
    destination.parent.mkdir()
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)

    result = api.add_shortcut_from_archive(
        name="Game",
        archive=archive,
        extract_to=destination,
        steam_root=steam_root,
        steam_id="123",
    )

    assert result.shortcut.status == "added"
    assert result.inspection.executable.is_file()
    stored = load_shortcuts(shortcuts_path)["shortcuts"]["0"]
    assert stored["Exe"] == f'"{result.inspection.executable}"'
    assert stored["StartDir"] == f'"{result.inspection.executable.parent}"'


def test_cli_archive_dry_run_returns_a_plan_without_extracting(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    steam_root = tmp_path / "Steam"
    shortcuts_path = _steam_profile(steam_root)
    archive = _write_tar(tmp_path / "Game.tar", {"Game/Game.exe": b"game"})
    destination = tmp_path / "Deck" / "Game"
    destination.parent.mkdir()
    original = shortcuts_path.read_bytes()
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)

    assert (
        main(
            [
                "add",
                "--steam-root",
                str(steam_root),
                "--steam-id",
                "123",
                "--name",
                "Game",
                "--archive",
                str(archive),
                "--extract-to",
                str(destination),
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["archive"] == str(archive.resolve())
    assert payload["extract_to"] == str(destination)
    assert payload["executable"] == str(destination / "Game.exe")
    assert payload["executable_relative"] == "Game/Game.exe"
    assert payload["archive_root"] == "Game"
    assert payload["selection"] == "single_candidate"
    assert payload["backup_path"] is None
    assert shortcuts_path.read_bytes() == original
    assert not destination.exists()


def test_cli_rejects_combining_direct_and_archive_targets(tmp_path: Path, capsys) -> None:
    executable = tmp_path / "game.exe"
    executable.touch()
    archive = _write_tar(tmp_path / "Game.tar", {"Game/Game.exe": b"game"})

    assert main(["add", "--name", "Game", "--exe", str(executable), "--archive", str(archive)]) == 2

    assert "not allowed with argument" in capsys.readouterr().err


def test_archive_preview_defaults_extraction_below_the_current_directory(
    tmp_path: Path, monkeypatch
) -> None:
    steam_root = tmp_path / "Steam"
    _steam_profile(steam_root)
    archive = _write_tar(tmp_path / "Game.tar", {"Game/Game.exe": b"game"})
    local_games = tmp_path / "LocalGames"
    local_games.mkdir()
    monkeypatch.chdir(local_games)
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)

    preview = api.preview_archive_shortcut(
        name="Game",
        archive=archive,
        steam_root=steam_root,
        steam_id="123",
    )

    assert preview.inspection.extract_to == local_games / "Game"


def test_cli_archive_add_extracts_and_reports_the_verified_shortcut(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    steam_root = tmp_path / "Steam"
    shortcuts_path = _steam_profile(steam_root)
    archive = _write_tar(tmp_path / "Game.tar", {"Game/Game.exe": b"game"})
    destination = tmp_path / "Deck" / "Game"
    destination.parent.mkdir()
    monkeypatch.setattr(api, "ensure_steam_not_running", lambda: None)

    assert (
        main(
            [
                "add",
                "--steam-root",
                str(steam_root),
                "--steam-id",
                "123",
                "--name",
                "Game",
                "--archive",
                str(archive),
                "--extract-to",
                str(destination),
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "added"
    assert payload["backup_path"].startswith(str(shortcuts_path) + ".bak.")
    assert payload["executable"] == str(destination / "Game.exe")
    assert (destination / "Game.exe").is_file()


def test_cli_metadata_emits_local_executable_title_candidates(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    executable = tmp_path / "Decktamer.exe"
    executable.touch()
    metadata = ExecutableMetadata(
        executable=executable,
        product_name="Decktamer",
        file_description="Decktamer",
        original_filename="Decktamer.exe",
        company_name="Horizon Edge",
        internal_name="Decktamer",
        product_version="1.0.0",
        title_candidates=(
            ExecutableTitleCandidate(value="Decktamer", source="product_name"),
        ),
    )
    monkeypatch.setattr("steam_shortcuts.cli.read_executable_metadata", lambda _: metadata)

    assert main(["metadata", "--exe", str(executable), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "company_name": "Horizon Edge",
        "executable": str(executable),
        "file_description": "Decktamer",
        "internal_name": "Decktamer",
        "original_filename": "Decktamer.exe",
        "product_name": "Decktamer",
        "product_version": "1.0.0",
        "title_candidates": [{"source": "product_name", "value": "Decktamer"}],
    }


def test_cli_lookup_searches_steamgriddb_using_the_best_local_title(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    executable = tmp_path / "Decktamer.exe"
    executable.touch()
    metadata = ExecutableMetadata(
        executable=executable,
        product_name="Decktamer",
        file_description=None,
        original_filename="Decktamer.exe",
        company_name=None,
        internal_name=None,
        product_version=None,
        title_candidates=(
            ExecutableTitleCandidate(value="Decktamer", source="product_name"),
        ),
    )
    monkeypatch.setattr("steam_shortcuts.cli.read_executable_metadata", lambda _: metadata)
    monkeypatch.setattr(
        "steam_shortcuts.cli.search_steamgriddb_games",
        lambda query: (SteamGridDbGame(id=42, name=query, types=("steam",), verified=True),),
    )

    assert main(["lookup", "--exe", str(executable), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "Decktamer"
    assert payload["games"] == [
        {"id": 42, "name": "Decktamer", "types": ["steam"], "verified": True},
    ]


def test_cli_artwork_dry_run_reports_exact_paths_without_writing(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    grid_dir = tmp_path / "grid"
    preview = api.ArtworkPreview(
        steam_root=tmp_path / "Steam",
        profile=SteamProfile(profile_id="123", shortcuts_path=tmp_path / "shortcuts.vdf"),
        artwork=SteamGridDbArtwork(
            game_id=42,
            portrait_url="https://cdn.example/portrait.jpg",
            hero_url="https://cdn.example/hero.jpg",
            logo_url="https://cdn.example/logo.png",
        ),
        grid_dir=grid_dir,
        portrait_path=grid_dir / "42p.jpg",
        hero_path=grid_dir / "42_hero.jpg",
        logo_path=grid_dir / "42_logo.png",
        conflicting_paths=(),
    )
    monkeypatch.setattr(api, "preview_steamgriddb_artwork", lambda **_: preview)

    assert (
        main(
            [
                "artwork",
                "--steamgriddb-id",
                "42",
                "--shortcut-id",
                "42",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["artwork"]["game_id"] == 42
    assert payload["paths"] == {
        "hero": str(grid_dir / "42_hero.jpg"),
        "logo": str(grid_dir / "42_logo.png"),
        "portrait": str(grid_dir / "42p.jpg"),
    }


def test_cli_artwork_installs_only_after_dry_run_is_omitted(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    grid_dir = tmp_path / "grid"
    result = ArtworkInstallResult(
        shortcut_id=42,
        artwork_id=180_422_180_864,
        grid_dir=grid_dir,
        portrait_path=grid_dir / "42p.jpg",
        hero_path=grid_dir / "42_hero.jpg",
        logo_path=grid_dir / "42_logo.png",
        backup_paths=(),
    )
    monkeypatch.setattr(api, "install_steamgriddb_artwork", lambda **_: result)

    assert (
        main(
            [
                "artwork",
                "--steamgriddb-id",
                "42",
                "--shortcut-id",
                "42",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert payload["artwork_id"] == 180_422_180_864
    assert payload["backup_paths"] == []


def test_cli_store_search_uses_the_best_local_title_candidate(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    executable = tmp_path / "Decktamer.exe"
    executable.touch()
    metadata = ExecutableMetadata(
        executable=executable,
        product_name="Decktamer",
        file_description=None,
        original_filename="Decktamer.exe",
        company_name=None,
        internal_name=None,
        product_version=None,
        title_candidates=(
            ExecutableTitleCandidate(value="Decktamer", source="product_name"),
        ),
    )
    monkeypatch.setattr("steam_shortcuts.cli.read_executable_metadata", lambda _: metadata)
    monkeypatch.setattr(
        "steam_shortcuts.cli.search_steam_store_games",
        lambda query: (SteamStoreGame(app_id=123, name=query, kind="game"),),
    )

    assert main(["store-search", "--exe", str(executable), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "Decktamer"
    assert payload["games"] == [{"app_id": 123, "kind": "game", "name": "Decktamer"}]


def test_cli_proton_report_returns_evidence_without_applying_any_tool(
    capsys, monkeypatch
) -> None:
    report = ProtonDbReport(
        app_id=730,
        tier="gold",
        best_reported_tier="platinum",
        trending_tier="platinum",
        confidence="strong",
        score=0.72,
        total_reports=2075,
    )
    monkeypatch.setattr("steam_shortcuts.cli.get_protondb_report", lambda _: report)

    assert main(["proton-report", "--steam-appid", "730", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["app_id"] == 730
    assert payload["tier"] == "gold"
    assert payload["proton_tool_recommendation"] is None
    assert "does not identify a Proton version" in payload["recommendation_reason"]
