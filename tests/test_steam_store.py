from __future__ import annotations

import json
from http.client import IncompleteRead
from urllib.request import Request

import pytest

from steam_shortcuts.errors import SteamStoreRequestFailed
from steam_shortcuts.steam_store import search_steam_store_games


def test_search_steam_store_games_returns_explicit_app_id_candidates() -> None:
    requests: list[Request] = []

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(
            {
                "total": 2,
                "items": [
                    {"id": 123, "name": "Decktamer", "type": "game"},
                    {"id": 124, "name": "Decktamer Demo", "type": "game"},
                ],
            }
        ).encode()

    games = search_steam_store_games("Decktamer Deluxe", transport=transport)

    assert [(game.app_id, game.name, game.kind) for game in games] == [
        (123, "Decktamer", "game"),
        (124, "Decktamer Demo", "game"),
    ]
    assert "term=Decktamer+Deluxe" in requests[0].full_url
    assert "cc=us" in requests[0].full_url
    assert "l=en" in requests[0].full_url


def test_search_steam_store_games_wraps_incomplete_http_body() -> None:
    def transport(_request: Request) -> bytes:
        raise IncompleteRead(b"partial", 12)

    with pytest.raises(SteamStoreRequestFailed, match="incomplete HTTP response"):
        search_steam_store_games("Toy Shire", transport=transport)
