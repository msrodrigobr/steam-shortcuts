"""Read-only Steam Store title search used to identify a ProtonDB AppID."""

from __future__ import annotations

import json
from collections.abc import Callable
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .errors import SteamStoreRequestFailed
from .models import SteamStoreGame

_STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
Transport = Callable[[Request], bytes]


def search_steam_store_games(
    query: str,
    *,
    transport: Transport | None = None,
) -> tuple[SteamStoreGame, ...]:
    """Return Steam Store candidates so the caller can choose an AppID explicitly."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Steam Store search query must not be blank")
    encoded_query = urlencode({"term": normalized_query, "cc": "us", "l": "en"})
    request = Request(
        f"{_STORE_SEARCH_URL}?{encoded_query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "steam-shortcuts/online-enrichment",
        },
    )
    response = _request_bytes(request, transport if transport is not None else _default_transport)
    try:
        payload = json.loads(response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SteamStoreRequestFailed("response was not valid JSON") from error
    if not isinstance(payload, dict):
        raise SteamStoreRequestFailed("response root was not an object")
    items = payload.get("items")
    if not isinstance(items, list):
        raise SteamStoreRequestFailed("response items were not a list")
    return tuple(_game_from_payload(item) for item in items)


def _request_bytes(request: Request, transport: Transport) -> bytes:
    try:
        content = transport(request)
    except HTTPError as error:
        raise SteamStoreRequestFailed(f"HTTP {error.code}") from error
    except URLError as error:
        raise SteamStoreRequestFailed(str(error.reason)) from error
    except HTTPException as error:
        raise SteamStoreRequestFailed(f"incomplete HTTP response: {error}") from error
    except OSError as error:
        raise SteamStoreRequestFailed(str(error)) from error
    if not content:
        raise SteamStoreRequestFailed("response was empty")
    return content


def _default_transport(request: Request) -> bytes:
    with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed HTTPS Store API URL
        content = response.read()
    if not isinstance(content, bytes):
        raise SteamStoreRequestFailed("response body was not bytes")
    return content


def _game_from_payload(value: object) -> SteamStoreGame:
    if not isinstance(value, dict):
        raise SteamStoreRequestFailed("Steam Store candidate was not an object")
    app_id = value.get("id")
    name = value.get("name")
    kind = value.get("type")
    if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
        raise SteamStoreRequestFailed("Steam Store candidate id was not a positive integer")
    if not isinstance(name, str) or not name.strip():
        raise SteamStoreRequestFailed("Steam Store candidate name was blank")
    if not isinstance(kind, str) or not kind.strip():
        raise SteamStoreRequestFailed("Steam Store candidate type was blank")
    return SteamStoreGame(app_id=app_id, name=name, kind=kind)
