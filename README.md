# steam-shortcuts

A portable Python library and command-line tool for adding non-Steam shortcuts to a local Steam profile without GUI automation.

It edits only Steam's per-user binary `userdata/<steam-id>/config/shortcuts.vdf`, never `localconfig.vdf`. Before replacing an existing shortcut file it creates a timestamped sibling backup, uses an atomic replacement, then rereads the VDF and verifies the exact shortcut it added.

Steam must be fully closed before using `add`. The tool refuses to write if it detects the main `steam` or `steam.exe` process. It will not murder Steam for you; that is a feature, not a missing feature.

## Status and support

- Windows is the primary acceptance target for Windows executable paths.
- Steam discovery supports Windows registry/default locations, common Linux locations (including Flatpak), and macOS.
- If a Steam root has multiple numeric profiles, `--steam-id` is required. The tool never guesses an account.
- Archive mode safely supports already-installed game directories in `.tar`, `.tar.gz` / `.tgz`, `.tar.bz2`, and `.tar.xz` files.
- The tool does not add artwork, modify Steam Cloud or `localconfig.vdf`, restart Steam, launch games, configure Proton, or drive the Steam UI.

## Install

Install the CLI into an isolated `pipx` environment:

```text
pipx install steam-shortcuts
steam-shortcuts --help
```

Use it as a library in another Python project:

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

## Archive mode (Steam Deck / local installs)

Archive mode is for a tar containing an already-installed game directory. It never runs `setup.exe`, does not unpack FreeArc `.bin` installer payloads, and does not execute Wine, Proton, `7z`, or another installer. Supported inputs are standard tar formats: `.tar`, `.tar.gz` / `.tgz`, `.tar.bz2`, and `.tar.xz`.

Use a new directory on the Deck's local storage as the extraction destination. Start with a dry run; it inspects archive metadata and Steam's VDF but does not extract files or write a shortcut:

```text
cd "$HOME/Games"
steam-shortcuts add \
  --name "My Game" \
  --archive "$HOME/media-nas/My Game.tar" \
  --extract-to "$HOME/Games/My Game" \
  --exe-relative "My Game/Game.exe" \
  --dry-run --json
```

Run the same command without `--dry-run` after reviewing the JSON plan:

```text
steam-shortcuts add \
  --name "My Game" \
  --archive "$HOME/media-nas/My Game.tar" \
  --extract-to "$HOME/Games/My Game" \
  --exe-relative "My Game/Game.exe" \
  --json
```

`--extract-to` must not already exist; the archive is extracted through a private staging directory and is never merged over an existing game. When omitted, the destination defaults to `<current-working-directory>/<archive-stem>`, so running the command from `~/Games` with `Game.tar` extracts to `~/Games/Game`. Use an explicit local destination when the archive itself lives on a NAS.

`--exe-relative` is relative to the archive root and always uses `/` separators. It is required when more than one non-installer `.exe` exists. If exactly one eligible `.exe` exists, the tool chooses it and reports `selection: "single_candidate"`; common installer names such as `setup.exe`, `install.exe`, and `unins*.exe` are never selected automatically. Ambiguous archives fail before extraction and print the candidate paths plus the `--exe-relative` recovery option.

When every archive member is inside one top-level directory, archive mode removes that wrapper while extracting. For example, `Decktamer/Decktamer.exe` inside `Decktamer.tar`, with `--extract-to "$HOME/Games/Decktamer"`, becomes `$HOME/Games/Decktamer/Decktamer.exe`, not `$HOME/Games/Decktamer/Decktamer/Decktamer.exe`. JSON reports that decision as `archive_root: "Decktamer"`. Archives with root-level regular files keep their original layout and report `archive_root: null`.

After Steam restarts, configure a Proton compatibility version in Steam if the selected executable is a Windows game. Registering a Windows executable does not magically make it a Linux game. Shocking, I know.

## Python API

```python
from pathlib import Path, PurePosixPath
from steam_shortcuts import add_shortcut, add_shortcut_from_archive

result = add_shortcut(
    name="My Game",
    executable=Path(r"D:\Games\My Game\Game.exe"),
    start_dir=Path(r"D:\Games\My Game"),
    launch_options="--windowed",
    tags=("Local",),
    steam_id="123456789",  # omit only when exactly one profile exists
)

print(result.status, result.run_game_url, result.backup_path)

archive_result = add_shortcut_from_archive(
    name="My Game",
    archive=Path("/home/deck/media-nas/My Game.tar"),
    extract_to=Path("/home/deck/Games/My Game"),
    executable_relative=PurePosixPath("My Game/Game.exe"),
    steam_id="123456789",
)
print(archive_result.shortcut.status, archive_result.inspection.executable)
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

## Public releases

Public releases are created by pushing a semantic version tag such as `v0.2.1`. The release workflow rebuilds the package, runs tests, linting, and type checks, then publishes with PyPI Trusted Publishing through GitHub OIDC. It intentionally contains no long-lived PyPI API token.

Before tagging a new release, verify the PyPI Trusted Publisher matches project `steam-shortcuts`, GitHub owner `msrodrigobr`, repository `steam-shortcuts`, workflow filename `publish.yml`, and the protected GitHub environment `pypi`.
