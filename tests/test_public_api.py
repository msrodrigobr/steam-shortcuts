from steam_shortcuts import (
    add_shortcut_from_archive,
    install_steamgriddb_artwork,
    preview_steamgriddb_artwork,
    read_executable_metadata,
)


def test_package_exports_archive_add_api() -> None:
    assert callable(add_shortcut_from_archive)


def test_package_exports_executable_metadata_api() -> None:
    assert callable(read_executable_metadata)


def test_package_exports_steamgriddb_artwork_api() -> None:
    assert callable(preview_steamgriddb_artwork)
    assert callable(install_steamgriddb_artwork)
