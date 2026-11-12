# Real Steam-client acceptance test

Run this on a Windows machine where Steam is installed for the same Windows user that will use the shortcut. Automated unit tests only prove that we wrote a valid binary VDF according to the tested codec; Steam itself remains the gloriously opaque final judge.

## Preconditions

1. Use a harmless, locally present target such as `C:\Windows\System32\notepad.exe`.
2. Do not use a real game as the first test.
3. Fully exit Steam, including its tray process.
4. Record the Steam version and Windows version in the test notes.

## Procedure

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

## Failure handling

- If Steam is running when `add` is attempted, the tool must refuse to write. Do not workaround this by killing processes blindly.
- If the shortcut is absent after restart, keep the current VDF, restore the timestamped backup, and record the current Steam version plus the JSON output.
- If Steam changes the file format or sanitizes fields unexpectedly, add a regression fixture/test before changing the library behavior.
