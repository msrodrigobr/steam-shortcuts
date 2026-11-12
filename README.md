# steam-shortcuts

A portable Python library and command-line tool for adding non-Steam shortcuts to a local Steam profile without GUI automation.

This project is in active development. It will refuse to edit Steam data while the Steam client is running, select an explicit Steam profile when more than one exists, create a timestamped backup before every write, and verify the written shortcut afterward.

## Intended installation

```text
pipx install steam-shortcuts
steam-shortcuts --help
```

The first release targets Windows executable paths and will include Steam installation discovery for Windows, Linux, and macOS.

## Safety boundary

The tool will edit only `userdata/<steam-id>/config/shortcuts.vdf`. It will not drive the Steam UI, kill/restart Steam, modify Steam Cloud or `localconfig.vdf`, or launch games.
