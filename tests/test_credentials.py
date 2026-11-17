from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from steam_shortcuts.credentials import configure_steamgriddb_api_key, resolve_steamgriddb_api_key
from steam_shortcuts.errors import SteamGridDbApiKeyMissing


def test_resolve_steamgriddb_api_key_prompts_once_and_saves_a_private_credential(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    key = resolve_steamgriddb_api_key(
        environ={},
        config_dir=tmp_path,
        prompt=lambda message: prompts.append(message) or "saved-secret",
        is_interactive=lambda: True,
    )

    credential_path = tmp_path / "credentials.json"
    assert key == "saved-secret"
    assert len(prompts) == 1
    assert json.loads(credential_path.read_text()) == {"steamgriddb_api_key": "saved-secret"}
    assert stat.S_IMODE(credential_path.stat().st_mode) == 0o600


def test_resolve_steamgriddb_api_key_reuses_saved_credential_without_prompting(
    tmp_path: Path,
) -> None:
    (tmp_path / "credentials.json").write_text('{"steamgriddb_api_key":"saved-secret"}')

    key = resolve_steamgriddb_api_key(
        environ={},
        config_dir=tmp_path,
        prompt=lambda _: pytest.fail("saved credential should not prompt"),
        is_interactive=lambda: True,
    )

    assert key == "saved-secret"


def test_resolve_steamgriddb_api_key_prefers_environment_override(tmp_path: Path) -> None:
    (tmp_path / "credentials.json").write_text('{"steamgriddb_api_key":"saved-secret"}')

    key = resolve_steamgriddb_api_key(
        environ={"STEAMGRIDDB_API_KEY": "environment-secret"},
        config_dir=tmp_path,
        prompt=lambda _: pytest.fail("environment override should not prompt"),
        is_interactive=lambda: True,
    )

    assert key == "environment-secret"


def test_resolve_steamgriddb_api_key_fails_in_noninteractive_mode_without_a_key(
    tmp_path: Path,
) -> None:
    with pytest.raises(SteamGridDbApiKeyMissing, match="interactive terminal"):
        resolve_steamgriddb_api_key(
            environ={},
            config_dir=tmp_path,
            is_interactive=lambda: False,
        )


def test_configure_steamgriddb_api_key_replaces_a_saved_credential(tmp_path: Path) -> None:
    credential_path = tmp_path / "credentials.json"
    credential_path.write_text('{"steamgriddb_api_key":"old-secret"}')

    saved_path = configure_steamgriddb_api_key(
        config_dir=tmp_path,
        prompt=lambda _: "replacement-secret",
        is_interactive=lambda: True,
    )

    assert saved_path == credential_path
    assert json.loads(credential_path.read_text()) == {"steamgriddb_api_key": "replacement-secret"}
