from steam_shortcuts import add_shortcut_from_archive, read_executable_metadata


def test_package_exports_archive_add_api() -> None:
    assert callable(add_shortcut_from_archive)


def test_package_exports_executable_metadata_api() -> None:
    assert callable(read_executable_metadata)
