from steam_shortcuts import add_shortcut_from_archive


def test_package_exports_archive_add_api() -> None:
    assert callable(add_shortcut_from_archive)
