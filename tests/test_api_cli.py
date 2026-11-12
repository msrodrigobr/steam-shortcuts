import json
from pathlib import Path

from steam_shortcuts import api
from steam_shortcuts.cli import main
from steam_shortcuts.vdf_store import load_shortcuts, serialize_shortcuts


def _steam_profile(root: Path, profile_id: str = "123") -> Path:
    shortcuts_path = root / "userdata" / profile_id / "config" / "shortcuts.vdf"
    shortcuts_path.parent.mkdir(parents=True)
    shortcuts_path.write_bytes(serialize_shortcuts({"shortcuts": {}}))
    return shortcuts_path


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
