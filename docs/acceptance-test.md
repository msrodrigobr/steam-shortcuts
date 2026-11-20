# Real Steam-client acceptance test

Run this on the machine and local user account whose Steam library will receive the shortcut. Automated tests prove the package's VDF and archive behavior; Steam itself remains the gloriously opaque final judge.

## Direct executable acceptance

### Preconditions

1. Use a harmless locally present target such as `C:\Windows\System32\notepad.exe`.
2. Do not use a real game as the first direct-mode test.
3. Fully exit Steam, including its tray process.
4. Record the Steam version and OS version in the test notes.

### Procedure

1. Identify the profile:

   ```text
   steam-shortcuts detect --json
   ```

2. Confirm the planned operation makes no change:

   ```text
   steam-shortcuts add \
     --steam-id <profile-id> \
     --name "steam-shortcuts acceptance test" \
     --exe "C:\Windows\System32\notepad.exe" \
     --dry-run --json
   ```

   Verify that `shortcuts.vdf` has no new backup and no changed timestamp.

3. Perform the actual write:

   ```text
   steam-shortcuts add \
     --steam-id <profile-id> \
     --name "steam-shortcuts acceptance test" \
     --exe "C:\Windows\System32\notepad.exe" \
     --json
   ```

   Confirm the JSON says `status: added`, contains a backup path, and identifies the expected profile and VDF path.

4. Start Steam normally. Confirm the item appears with the requested display name, then launch it from the Steam library. Notepad must open.

5. Fully exit Steam and rerun the same command. It must return `status: already_exists`, create no second backup, and leave the VDF bytes unchanged.

6. Remove the disposable shortcut manually in Steam, or restore the backup with Steam fully closed. Preserve the command output and redact any profile ID before filing it as project evidence.

## Steam Deck archive acceptance

### Preconditions

1. Use a legally owned tar containing an already-installed game directory, not an installer payload.
2. Mount or copy the source archive so the Deck can read it.
3. Choose a new destination on the Deck's local storage, for example `$HOME/Games/Archive Acceptance`. It must not already exist.
4. Fully exit Steam in both Gaming Mode and Desktop Mode.
5. Identify the Deck profile with `steam-shortcuts detect --json`; specify `--steam-id` if more than one numeric profile is present.

### Procedure

1. Confirm an ambiguous archive is safe. Use an archive that contains two non-installer `.exe` files, or make a disposable fixture with that shape. Run archive dry-run without `--exe-relative`:

   ```text
   steam-shortcuts add \
     --steam-id <profile-id> \
     --name "archive ambiguity acceptance" \
     --archive "$HOME/media-nas/Ambiguous Game.tar" \
     --extract-to "$HOME/Games/Archive Ambiguity" \
     --dry-run --json
   ```

   Expected: exit code 2; stderr lists candidate archive-relative paths and `--exe-relative`; neither the destination nor a VDF backup exists.

2. Confirm dry-run makes no local or VDF mutation:

   ```text
   steam-shortcuts add \
     --steam-id <profile-id> \
     --name "archive acceptance test" \
     --archive "$HOME/media-nas/My Game.tar" \
     --extract-to "$HOME/Games/Archive Acceptance" \
     --exe-relative "My Game/Game.exe" \
     --dry-run --json
   ```

   Expected JSON includes `dry_run: true`, `archive`, `extract_to`, `executable`, `executable_relative`, `archive_root`, and `selection`. If all archive members share one top-level folder, `archive_root` names it and the final executable path does not repeat that folder below `extract_to`. Verify the destination does not exist and `shortcuts.vdf` has no new backup or changed timestamp.

3. With Steam still fully closed, run the same command without `--dry-run`:

   ```text
   steam-shortcuts add \
     --steam-id <profile-id> \
     --name "archive acceptance test" \
     --archive "$HOME/media-nas/My Game.tar" \
     --extract-to "$HOME/Games/Archive Acceptance" \
     --exe-relative "My Game/Game.exe" \
     --json
   ```

   Expected: `status: added`, a valid VDF backup path, and an executable path under `$HOME/Games/Archive Acceptance`. Confirm the archive source was not modified.

4. Start Steam normally. Confirm the shortcut appears with the requested display name. If it launches a Windows executable, select a Proton compatibility version in Steam, then launch manually and record the result.

5. Preserve the JSON output and exact archive-relative executable selection. Do not delete the VDF backup until the real Steam client result is recorded.

## SteamGridDB artwork acceptance

### Preconditions

1. Complete one direct or archive acceptance shortcut creation and retain its `shortcut_id`.
2. Fully exit Steam in every mode.
3. Run `steam-shortcuts configure-steamgriddb` in an interactive shell and enter a personal SteamGridDB key at the hidden prompt. Confirm the reported per-user credential file exists with mode `0600` on Linux/macOS; never place the key in a command argument, project file, or test evidence.
4. Record the current contents of `userdata/<profile-id>/config/grid/` for the shortcut's 32-bit `appid`, if any. Steam's 64-bit run-game ID is not the normal library-grid artwork ID. Do not use an existing game with artwork you care about as the disposable test.

### Procedure

1. Inspect the local executable and record the returned title candidates:

   ```text
   steam-shortcuts metadata --exe "$HOME/Games/Artwork Acceptance/Game.exe" --json
   ```

2. Search SteamGridDB, inspect the returned candidates, and choose the exact game ID manually:

   ```text
   steam-shortcuts lookup --exe "$HOME/Games/Artwork Acceptance/Game.exe" --json
   ```

3. Preview the selected artwork without downloading or writing files:

   ```text
   steam-shortcuts artwork \
     --steam-id <profile-id> \
     --shortcut-id <shortcut-id> \
     --steamgriddb-id <selected-game-id> \
     --dry-run --json
   ```

   Expected: `dry_run: true`, three HTTPS artwork URLs, exact portrait/hero/logo target paths, and no new `grid` files.

4. With Steam still closed, rerun the command without `--dry-run`. Confirm all three reported files exist and are non-empty. If any target already existed, the command must refuse without `--overwrite` and leave every existing file unchanged.

5. Start Steam normally. Verify the library portrait cover, game-page hero, and logo visually match the selected game. Fully exit Steam before using `--overwrite`; if used, confirm the JSON lists backup paths and each backup contains the previous file bytes.

6. Record the selected SteamGridDB game ID, Steam client version, and output. Do not publish, back up, or include the credential file or API key in test evidence.

## ProtonDB report acceptance

1. With no Steam file mutation expected, identify an explicit Store AppID from local executable metadata:

   ```text
   steam-shortcuts store-search --exe "$HOME/Games/Artwork Acceptance/Game.exe" --json
   ```

2. Manually choose the exact game from the returned AppID/name/type candidates, then run:

   ```text
   steam-shortcuts proton-report --steam-appid <selected-app-id> --json
   ```

3. Expected: output contains ProtonDB tier evidence, the matching AppID, a ProtonDB URL, `proton_tool_recommendation: null`, and an explanation that no version was selected. Confirm no `shortcuts.vdf`, `localconfig.vdf`, or `grid` file timestamps changed.

## One-command game enrichment acceptance

1. Use an existing, uniquely named non-Steam shortcut whose exact name matches a Steam Store game. Fully exit Steam and record the shortcut's `shortcuts.vdf`, `localconfig.vdf`, and grid-directory state.
2. Preview the operation:

   ```text
   steam-shortcuts enrich-game-data "Toy Shire" --dry-run --json
   ```

   Expected: exact local shortcut and Steam Store match, Steam AppID, available official Steam portrait/hero/logo paths, ProtonDB evidence/status, and `settings_changed: false`. Confirm the command does not download or write grid images and does not change either VDF.

3. Apply artwork:

   ```text
   steam-shortcuts enrich-game-data "Toy Shire" --json
   ```

   Expected: available official Steam library images are written under the selected profile's `config/grid/`. Existing slots are preserved individually across `.jpg`, `.jpeg`, and `.png` extensions while missing slots are filled. `--overwrite-artwork` backs up and replaces a same-format file; alternate-format variants are retained and reported as conflicts, never deleted. This Steam artwork path needs no SteamGridDB API key.

4. ProtonDB summaries do not identify a specific Proton tool/version. Expected: report the compatibility evidence; if reports are missing or confidence is weak, include a warning. In all cases where there is no exact version recommendation, `settings_changed` remains false and `localconfig.vdf` is byte-for-byte unchanged. A missing ProtonDB report must not prevent available artwork from being installed.

5. Start Steam and visually verify the portrait, hero, and logo. Confirm the non-Steam shortcut remains present and launches as before.

## Failure handling

- If Steam is running when `add` is attempted, the tool must refuse to write. Do not workaround this by killing processes blindly.
- If archive selection is ambiguous, choose one displayed path and rerun with `--exe-relative`; do not expect the package to make a confident guess from filenames.
- If archive extraction fails, preserve the source archive and error. The package must remove only its own `.steam-shortcuts-*` staging directory and must not overwrite an existing destination.
- If Steam rejects or does not show an added shortcut, keep the current VDF, restore the timestamped backup, and record the Steam version plus JSON output.
- If Steam changes the file format or sanitizes fields unexpectedly, add a regression fixture/test before changing library behavior.
