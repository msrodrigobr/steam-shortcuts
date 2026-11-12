# steam-shortcuts

A portable Python library and command-line tool for adding non-Steam shortcuts to a local Steam profile without GUI automation.

It edits only Steam's per-user binary `userdata/<steam-id>/config/shortcuts.vdf`, never `localconfig.vdf`. Before replacing an existing shortcut file it creates a timestamped sibling backup, uses an atomic replacement, then rereads the VDF and verifies the exact shortcut it added.

Steam must be fully closed before using `add`. The tool refuses to write if it detects the main `steam` or `steam.exe` process. It will not murder Steam for you; that is a feature, not a missing feature.

## Status and support

- Windows is the primary acceptance target for Windows executable paths.
- Steam discovery supports Windows registry/default locations, common Linux locations (including Flatpak), and macOS.
- If a Steam root has multiple numeric profiles, `--steam-id` is required. The tool never guesses an account.
- The first release intentionally does not add artwork, modify Steam Cloud or `localconfig.vdf`, restart Steam, launch games, or drive the Steam UI.

## Install

Until this distribution is published, install a checkout into an isolated `pipx` environment:

```text
pipx install .
steam-shortcuts --help
```

After a published release exists, the equivalent will be:

```text
pipx install steam-shortcuts
```

After a published release exists, use it as a library in another Python project:

```text
python -m pip install steam-shortcuts
```

## Command-line use

First, inspect the local Steam installation and profiles:

```text
steam-shortcuts detect --json
steam-shortcuts list --steam-id 123456789 --json
```

Add a Windows executable. Quote the shell argument normally; do not add the internal Steam quotes yourself:

```text
steam-shortcuts add \
  --steam-id 123456789 \
  --name "My Game" \
  --exe "D:\Games\My Game\Game.exe" \
  --start-dir "D:\Games\My Game" \
  --args "--windowed" \
  --tag "Local" \
  --json
```

Use `--dry-run` first whenever you are doing something unusual. It validates Steam discovery, profile selection, the executable, duplicates, and the planned fields without writing a VDF or backup:

```text
steam-shortcuts add \
  --steam-id 123456789 \
  --name "My Game" \
  --exe "D:\Games\My Game\Game.exe" \
  --dry-run --json
```

For portable or nonstandard installs, give the Steam root — the directory that contains `userdata`, not the VDF file itself:

```text
steam-shortcuts add \
  --steam-root "E:\PortableSteam" \
  --steam-id 123456789 \
  --name "My Game" \
  --exe "D:\Games\My Game\Game.exe"
```

A successful JSON result includes `status`, `profile_id`, `shortcuts_path`, a 32-bit shortcut ID, `steam://rungameid/...`, and `backup_path`. Rerunning the exact name/executable combination returns `already_exists` and creates no backup. Reusing an executable under a different display name is deliberately a conflict rather than a surprise duplicate.

Restart Steam normally after a successful add so it reloads `shortcuts.vdf`; then the item should appear in the library.

## Python API

```python
from pathlib import Path
from steam_shortcuts import add_shortcut

result = add_shortcut(
    name="My Game",
    executable=Path(r"D:\Games\My Game\Game.exe"),
    start_dir=Path(r"D:\Games\My Game"),
    launch_options="--windowed",
    tags=("Local",),
    steam_id="123456789",  # omit only when exactly one profile exists
)

print(result.status, result.run_game_url, result.backup_path)
```

The API and CLI run on the same local user account that owns the Steam profile. They do not communicate with a Steam account, web API, or remote computer.

## Recovery

For an existing VDF, every successful mutation creates a sibling backup named like:

```text
shortcuts.vdf.bak.20261112T020000Z
```

If Steam rejects or does not show an added shortcut:

1. Fully exit Steam.
2. Preserve the current `shortcuts.vdf` for investigation instead of deleting it.
3. Replace it with the timestamped `.bak.*` file from the same directory.
4. Start Steam and verify the prior library state.

A malformed VDF is rejected without overwriting it. Keep that file and its error message; it is evidence, not clutter.

## Development

```text
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m build
```

See `docs/acceptance-test.md` for the real Steam-client validation procedure.
