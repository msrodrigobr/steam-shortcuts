from __future__ import annotations

import json
from http.client import IncompleteRead
from urllib.request import Request

import pytest

from steam_shortcuts import steam_assets
from steam_shortcuts.errors import SteamStoreRequestFailed
from steam_shortcuts.steam_assets import get_steam_library_artwork


def test_get_steam_library_artwork_uses_public_store_item_assets_without_authentication() -> None:
    payload = {
        "response": {
            "store_items": [
                {
                    "appid": 2361460,
                    "success": 1,
                    "name": "Toy Shire",
                    "assets": {
                        "asset_url_format": "steam/apps/2361460/${FILENAME}?t=123",
                        "library_capsule_2x": "library_600x900_2x.jpg",
                        "library_hero_2x": "library_hero_2x.jpg",
                    },
                }
            ]
        }
    }
    requests: list[Request] = []

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(payload).encode()

    artwork = get_steam_library_artwork(2361460, transport=transport)

    assert artwork.app_id == 2361460
    assert artwork.portrait_url == (
        "https://shared.fastly.steamstatic.com/store_item_assets/"
        "steam/apps/2361460/library_600x900_2x.jpg?t=123"
    )
    assert artwork.hero_url == (
        "https://shared.fastly.steamstatic.com/store_item_assets/"
        "steam/apps/2361460/library_hero_2x.jpg?t=123"
    )
    assert artwork.logo_url == (
        "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/2361460/logo.png"
    )
    assert len(requests) == 1
    assert requests[0].full_url.startswith(
        "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json="
    )
    assert requests[0].get_header("Authorization") is None


def test_download_steam_asset_rejects_non_image_content() -> None:
    def transport(_request: Request) -> bytes:
        return b"<html>temporary CDN error</html>"

    with pytest.raises(SteamStoreRequestFailed, match="not a JPEG image"):
        steam_assets.download_steam_asset(
            "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1/library_hero.jpg",
            transport=transport,
        )


def test_download_steam_asset_wraps_incomplete_http_body() -> None:
    def transport(_request: Request) -> bytes:
        raise IncompleteRead(b"partial", 20)

    with pytest.raises(SteamStoreRequestFailed, match="incomplete HTTP response"):
        steam_assets.download_steam_asset(
            "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1/library_hero.jpg",
            transport=transport,
        )
