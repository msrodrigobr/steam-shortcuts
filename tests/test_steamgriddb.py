from __future__ import annotations

import json
from http.client import IncompleteRead
from urllib.request import Request

import pytest

from steam_shortcuts.errors import SteamGridDbApiKeyMissing, SteamGridDbRequestFailed
from steam_shortcuts.steamgriddb import (
    SteamGridDbClient,
    search_steamgriddb_games,
    steamgriddb_client_from_environment,
)


def test_search_steamgriddb_games_requires_an_api_key() -> None:
    with pytest.raises(SteamGridDbApiKeyMissing, match="STEAMGRIDDB_API_KEY"):
        search_steamgriddb_games("Decktamer", environ={})


def test_steamgriddb_client_factory_reads_the_api_key_from_environment() -> None:
    client = steamgriddb_client_from_environment(environ={"STEAMGRIDDB_API_KEY": "secret"})

    assert isinstance(client, SteamGridDbClient)


def test_steamgriddb_client_searches_title_with_bearer_authentication() -> None:
    requests: list[Request] = []

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(
            {
                "success": True,
                "data": [
                    {"id": 42, "name": "Decktamer", "types": ["steam"], "verified": True},
                    {"id": 43, "name": "Decktamer Demo", "types": ["steam"], "verified": False},
                ],
            }
        ).encode()

    games = search_steamgriddb_games(
        "Decktamer Deluxe",
        environ={"STEAMGRIDDB_API_KEY": "secret"},
        transport=transport,
    )

    assert [(game.id, game.name, game.types, game.verified) for game in games] == [
        (42, "Decktamer", ("steam",), True),
        (43, "Decktamer Demo", ("steam",), False),
    ]
    assert len(requests) == 1
    assert requests[0].full_url.endswith("/search/autocomplete/Decktamer%20Deluxe")
    assert requests[0].get_header("Authorization") == "Bearer secret"


def test_steamgriddb_client_rejects_malformed_search_payload() -> None:
    client = SteamGridDbClient("secret", transport=lambda _: b'{"success": true, "data": {}}')

    with pytest.raises(ValueError, match="data must be a list"):
        client.search_games("Decktamer")


def test_steamgriddb_client_selects_highest_scored_artwork_for_each_required_kind() -> None:
    requests: list[Request] = []

    def transport(request: Request) -> bytes:
        requests.append(request)
        if "/grids/game/42" in request.full_url:
            data = [
                {"url": "https://cdn.example/portrait-low.jpg", "score": 3},
                {"url": "https://cdn.example/portrait-best.jpg", "score": 12},
            ]
        elif "/heroes/game/42" in request.full_url:
            data = [{"url": "https://cdn.example/hero.jpg", "score": 9}]
        elif "/logos/game/42" in request.full_url:
            data = [{"url": "https://cdn.example/logo.png", "score": 5}]
        else:  # pragma: no cover - every expected endpoint is asserted below
            raise AssertionError(request.full_url)
        return json.dumps({"success": True, "data": data}).encode()

    artwork = SteamGridDbClient("secret", transport=transport).get_artwork(42)

    assert artwork.portrait_url == "https://cdn.example/portrait-best.jpg"
    assert artwork.hero_url == "https://cdn.example/hero.jpg"
    assert artwork.logo_url == "https://cdn.example/logo.png"
    assert any("dimensions=600x900" in request.full_url for request in requests)
    assert any("mimes=image%2Fjpeg" in request.full_url for request in requests)
    assert any("mimes=image%2Fpng" in request.full_url for request in requests)


def test_steamgriddb_client_downloads_asset_without_sending_api_key_to_the_cdn() -> None:
    requests: list[Request] = []

    def transport(request: Request) -> bytes:
        requests.append(request)
        return b"\xff\xd8\xffimage-bytes"

    content = SteamGridDbClient("secret", transport=transport).download_asset(
        "https://cdn.example/game-art.jpg"
    )

    assert content == b"\xff\xd8\xffimage-bytes"
    assert requests[0].get_header("Authorization") is None


def test_steamgriddb_client_rejects_non_image_asset_content() -> None:
    client = SteamGridDbClient("secret", transport=lambda _: b"<html>error</html>")

    with pytest.raises(SteamGridDbRequestFailed, match="not a valid JPEG image"):
        client.download_asset("https://cdn.example/game-art.jpg")


def test_steamgriddb_client_wraps_incomplete_asset_response() -> None:
    def transport(_request: Request) -> bytes:
        raise IncompleteRead(b"partial", 12)

    client = SteamGridDbClient("secret", transport=transport)

    with pytest.raises(SteamGridDbRequestFailed, match="incomplete HTTP response"):
        client.download_asset("https://cdn.example/game-art.jpg")
