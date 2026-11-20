# steam-shortcuts

A portable Python library and command-line tool for adding non-Steam shortcuts to a local Steam profile without GUI automation.

It edits Steam's per-user binary `userdata/<steam-id>/config/shortcuts.vdf` and, when explicitly requested, local `userdata/<steam-id>/config/grid/` artwork files. It never edits `localconfig.vdf`. Before replacing an existing shortcut file it creates a timestamped sibling backup, uses an atomic replacement, then rereads the VDF and verifies the exact shortcut it added.

Steam must be fully closed before using `add` or `artwork`. The tool refuses to write if it detects the main `steam` or `steam.exe` process. It will not murder Steam for you; that is a feature, not a missing feature.

## Status and support

- Windows is the primary acceptance target for Windows executable paths.
- Steam discovery supports Windows registry/default locations, common Linux locations (including Flatpak), and macOS.
- If a Steam root has multiple numeric profiles, `--steam-id` is required. The tool never guesses an account.
- Archive mode safely supports already-installed game directories in `.tar`, `.tar.gz` / `.tgz`, `.tar.bz2`, and `.tar.xz` files.
- The tool never modifies Steam Cloud or `localconfig.vdf`, restarts Steam, launches games, configures Proton, or drives the Steam UI.

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

## Title lookup and artwork

Inspect a selected Windows executable before making any internet request. `metadata` reads PE version-resource fields such as `ProductName`, `FileDescription`, `OriginalFilename`, company, and product version, then emits deduplicated title candidates in confidence order:

```text
steam-shortcuts metadata --exe "$HOME/Games/Decktamer/Decktamer.exe" --json
```

SteamGridDB lookup is optional. On the first interactive `lookup` or `artwork` operation, the CLI asks for the user's personal SteamGridDB key without echoing it, then saves it locally for that OS user. On Linux and Steam Deck the file is `$XDG_CONFIG_HOME/steam-shortcuts/credentials.json` (normally `~/.config/steam-shortcuts/credentials.json`) and is written with mode `0600`; macOS and Windows use their normal per-user application-config locations. The file is plaintext by design because this package has no desktop keychain dependency, so it is protected by the user's account permissions rather than magic. Secrets are not magic. They are files wearing a hat.

To set or replace the saved key explicitly:

```text
steam-shortcuts configure-steamgriddb
```

For CI, scripts, or a temporary override, `STEAMGRIDDB_API_KEY` still takes precedence. It is never accepted as a CLI argument, so it does not leak through shell history or normal process listings.

```text
steam-shortcuts lookup --exe "$HOME/Games/Decktamer/Decktamer.exe" --json
```

`lookup` returns candidate names and SteamGridDB IDs. Select the correct ID yourself; the tool intentionally does not attach art to the first similarly named thing the internet throws at it. With Steam fully closed, first preview the exact files and URLs:

```text
steam-shortcuts artwork \
  --steam-id 123456789 \
  --shortcut-id 3516482161 \
  --steamgriddb-id 42 \
  --dry-run --json
```

After reviewing the preview, rerun the command without `--dry-run` to download and install a portrait cover, hero, and logo beneath `userdata/<steam-id>/config/grid/`. Normal library-grid artwork filenames use the shortcut's 32-bit `appid`; the 64-bit value is for the Big Picture/run-game identifier. Existing artwork slots are preserved individually (including `.jpg`, `.jpeg`, or `.png` variants) while missing slots are filled. Slots are installed independently, so a conflict or write failure on one image does not block the others. `--overwrite` backs up and replaces an existing file at the selected format; alternate-format variants are retained and reported as conflicts rather than deleted.

## Proton compatibility report

Use the same executable metadata to search Steam's public Store index, then manually choose the exact AppID. Title matching is intentionally explicit because similarly named demos, remasters, and unrelated games are a fine way to configure the wrong thing:

```text
steam-shortcuts store-search --exe "$HOME/Games/Decktamer/Decktamer.exe" --json
steam-shortcuts proton-report --steam-appid <selected-app-id> --json
```

`proton-report` is read-only. It returns ProtonDB's current tier, best reported tier, trending tier, confidence, score, report count, and a link to the reports. ProtonDB's public summary does not identify a canonical tested Proton or GE-Proton version, so the tool explicitly returns no version recommendation and never changes Steam compatibility settings. It is evidence for a human decision, not a very confident dice roll.

After Steam restarts, configure a Proton compatibility version in Steam if the selected executable is a Windows game. Registering a Windows executable does not magically make it a Linux game. Shocking, I know.

## One-command enrichment for an existing shortcut

After adding a game with `add`, use its exact library shortcut name to fetch official Steam library artwork and ProtonDB compatibility data in one command. This uses public Steam Store endpoints and does not require a Steam or SteamGridDB API key:

```text
steam-shortcuts enrich-game-data "Toy Shire" --dry-run --json
```

Review the resolved Steam AppID and artwork paths. With Steam fully closed, run it again to install the available portrait, hero, and logo:

```text
steam-shortcuts enrich-game-data "Toy Shire" --json
```

The command only enriches an existing non-Steam shortcut; it does not replace `add`. It requires a unique exact local shortcut name and a unique exact Steam Store game match. Existing art is preserved slot-by-slot, and available missing slots are filled. Files with `.jpg`, `.jpeg`, or `.png` extensions count as the same slot. Pass `--overwrite-artwork` to back up and replace existing slots.

ProtonDB's summary reports compatibility tiers and evidence, not a specific Proton/GE-Proton version. Therefore this command reports the summary and warns when evidence is missing or weak, but it does not change Steam compatibility settings or `localconfig.vdf`. Existing Proton settings remain untouched. `proton-report` remains available for a standalone read-only report.

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

Shortcut operations run on the same local user account that owns the Steam profile. `metadata`, `detect`, `list`, and `add` are local-only. `lookup` and `artwork` make optional HTTPS requests to SteamGridDB only after the user supplies `STEAMGRIDDB_API_KEY`; no Steam account or Steam Web API is used.

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
