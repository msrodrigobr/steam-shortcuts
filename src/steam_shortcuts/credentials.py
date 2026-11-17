"""Local, per-user credential handling for optional online enrichments."""

from __future__ import annotations

import getpass
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import uuid4

from .errors import CredentialStorageError, SteamGridDbApiKeyMissing

Prompt = Callable[[str], str]
InteractiveCheck = Callable[[], bool]
_CREDENTIALS_FILE = "credentials.json"


def resolve_steamgriddb_api_key(
    *,
    environ: Mapping[str, str] | None = None,
    config_dir: Path | None = None,
    prompt: Prompt | None = None,
    is_interactive: InteractiveCheck | None = None,
) -> str:
    """Return an environment override, saved credential, or one prompted value.

    A prompted key is stored only for the current OS user in a local credentials
    file. It is never accepted as a command-line argument, so it cannot leak
    through shell history or ordinary process listings.
    """
    environment = os.environ if environ is None else environ
    environment_key = environment.get("STEAMGRIDDB_API_KEY", "").strip()
    if environment_key:
        return environment_key

    directory = config_dir if config_dir is not None else user_config_dir(environ=environment)
    credential_path = directory / _CREDENTIALS_FILE
    saved_key = _load_saved_key(credential_path)
    if saved_key is not None:
        return saved_key

    interactive = is_interactive if is_interactive is not None else _is_interactive
    if not interactive():
        raise SteamGridDbApiKeyMissing(
            "no saved key exists and no interactive terminal is available"
        )
    read_key = prompt if prompt is not None else _prompt_for_steamgriddb_key
    prompted_key = read_key("SteamGridDB API key (saved locally for this user): ").strip()
    if not prompted_key:
        raise SteamGridDbApiKeyMissing("a blank key was not saved")
    _save_key(credential_path, prompted_key)
    return prompted_key


def configure_steamgriddb_api_key(
    *,
    environ: Mapping[str, str] | None = None,
    config_dir: Path | None = None,
    prompt: Prompt | None = None,
    is_interactive: InteractiveCheck | None = None,
) -> Path:
    """Prompt for and replace the locally saved SteamGridDB API key."""
    environment = os.environ if environ is None else environ
    directory = config_dir if config_dir is not None else user_config_dir(environ=environment)
    interactive = is_interactive if is_interactive is not None else _is_interactive
    if not interactive():
        raise SteamGridDbApiKeyMissing("no interactive terminal is available")
    read_key = prompt if prompt is not None else _prompt_for_steamgriddb_key
    prompted_key = read_key("SteamGridDB API key (saved locally for this user): ").strip()
    if not prompted_key:
        raise SteamGridDbApiKeyMissing("a blank key was not saved")
    credential_path = directory / _CREDENTIALS_FILE
    _save_key(credential_path, prompted_key)
    return credential_path


def user_config_dir(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform_name: str | None = None,
    os_name: str | None = None,
) -> Path:
    """Return the standard per-user configuration directory for this package."""
    environment = os.environ if environ is None else environ
    user_home = home if home is not None else Path.home()
    system = platform_name if platform_name is not None else sys.platform
    operating_system = os_name if os_name is not None else os.name
    if operating_system == "nt":
        base = Path(environment.get("APPDATA", str(user_home / "AppData" / "Roaming")))
    elif system == "darwin":
        base = user_home / "Library" / "Application Support"
    else:
        base = Path(environment.get("XDG_CONFIG_HOME", str(user_home / ".config")))
    return base / "steam-shortcuts"


def _load_saved_key(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        raise CredentialStorageError(path, "credential file must not be a symbolic link")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CredentialStorageError(path, "credential file is not valid JSON") from error
    if not isinstance(loaded, dict):
        raise CredentialStorageError(path, "credential file root must be an object")
    value = loaded.get("steamgriddb_api_key")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CredentialStorageError(path, "steamgriddb_api_key must be a nonblank string")
    _restrict_permissions(path)
    return value.strip()


def _save_key(path: Path, key: str) -> None:
    directory = path.parent
    if directory.is_symlink():
        raise CredentialStorageError(directory, "credential directory must not be a symbolic link")
    temporary_path: Path | None = None
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        _restrict_permissions(directory)
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        with temporary_path.open("x", encoding="utf-8") as temporary_file:
            temporary_file.write(json.dumps({"steamgriddb_api_key": key}, sort_keys=True) + "\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        _restrict_permissions(temporary_path)
        os.replace(temporary_path, path)
        _restrict_permissions(path)
        _fsync_directory(directory)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise CredentialStorageError(path, str(error)) from error


def _prompt_for_steamgriddb_key(message: str) -> str:
    return getpass.getpass(message)


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _restrict_permissions(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o700 if path.is_dir() else 0o600)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
