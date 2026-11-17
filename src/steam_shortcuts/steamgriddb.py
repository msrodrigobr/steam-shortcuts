"""Minimal, explicit SteamGridDB API integration."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from .errors import SteamGridDbApiKeyMissing, SteamGridDbRequestFailed
from .models import SteamGridDbArtwork, SteamGridDbGame

_API_BASE_URL = "https://www.steamgriddb.com/api/v2"
Transport = Callable[[Request], bytes]


class SteamGridDbArtworkClient(Protocol):
    """Operations needed to resolve and download a selected artwork set."""

    def get_artwork(self, game_id: int) -> SteamGridDbArtwork: ...

    def download_asset(self, url: str) -> bytes: ...


def steamgriddb_client_from_environment(
    *,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> SteamGridDbClient:
    """Build a client from ``STEAMGRIDDB_API_KEY`` without exposing the secret in CLI args."""
    environment = os.environ if environ is None else environ
    api_key = environment.get("STEAMGRIDDB_API_KEY", "").strip()
    if not api_key:
        raise SteamGridDbApiKeyMissing()
    return SteamGridDbClient(api_key, transport=transport)


def search_steamgriddb_games(
    query: str,
    *,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> tuple[SteamGridDbGame, ...]:
    """Search SteamGridDB using ``STEAMGRIDDB_API_KEY`` from the environment."""
    return steamgriddb_client_from_environment(
        environ=environ,
        transport=transport,
    ).search_games(query)


class SteamGridDbClient:
    """A tiny SteamGridDB client with injectable transport for deterministic tests."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: Transport | None = None,
        base_url: str = _API_BASE_URL,
    ) -> None:
        if not api_key.strip():
            raise SteamGridDbApiKeyMissing()
        self._api_key = api_key
        self._transport = transport if transport is not None else _default_transport
        self._base_url = base_url.rstrip("/")

    def search_games(self, query: str) -> tuple[SteamGridDbGame, ...]:
        """Return ordered SteamGridDB game candidates for one human title query."""
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("SteamGridDB search query must not be blank")
        payload = self._request_json(f"/search/autocomplete/{quote(normalized_query, safe='')}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("SteamGridDB response data must be a list")
        return tuple(_game_from_payload(item) for item in data)

    def get_artwork(self, game_id: int) -> SteamGridDbArtwork:
        """Select Steam-compatible portrait, hero, and logo assets for one game."""
        if not isinstance(game_id, int) or isinstance(game_id, bool) or game_id <= 0:
            raise ValueError("SteamGridDB game id must be a positive integer")
        portrait_url = self._best_asset_url(
            "/grids/game/" + str(game_id),
            {"dimensions": "600x900", "mimes": "image/jpeg", "types": "static"},
            "portrait",
        )
        hero_url = self._best_asset_url(
            "/heroes/game/" + str(game_id),
            {"mimes": "image/jpeg", "types": "static"},
            "hero",
        )
        logo_url = self._best_asset_url(
            "/logos/game/" + str(game_id),
            {"mimes": "image/png", "types": "static"},
            "logo",
        )
        return SteamGridDbArtwork(
            game_id=game_id,
            portrait_url=portrait_url,
            hero_url=hero_url,
            logo_url=logo_url,
        )

    def download_asset(self, url: str) -> bytes:
        """Download one HTTPS artwork URL without leaking the API key to its CDN."""
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("SteamGridDB artwork URL must use HTTPS")
        request = Request(
            url,
            headers={
                "Accept": "image/*",
                "User-Agent": "steam-shortcuts/online-enrichment",
            },
        )
        try:
            content = self._transport(request)
        except HTTPError as error:
            raise SteamGridDbRequestFailed(f"asset HTTP {error.code}") from error
        except URLError as error:
            raise SteamGridDbRequestFailed(f"asset {error.reason}") from error
        except OSError as error:
            raise SteamGridDbRequestFailed(f"asset {error}") from error
        if not content:
            raise SteamGridDbRequestFailed("asset response was empty")
        return content

    def _best_asset_url(self, endpoint: str, query: Mapping[str, str], kind: str) -> str:
        payload = self._request_json(f"{endpoint}?{urlencode(query)}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise SteamGridDbRequestFailed(f"{kind} response data was not a list")
        candidates: list[tuple[int | float, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            score = item.get("score", 0)
            if (
                isinstance(url, str)
                and url.startswith("https://")
                and isinstance(score, (int, float))
                and not isinstance(score, bool)
            ):
                candidates.append((score, url))
        if not candidates:
            raise SteamGridDbRequestFailed(f"no compatible {kind} artwork was returned")
        return max(candidates, key=lambda candidate: candidate[0])[1]

    def _request_json(self, endpoint: str) -> Mapping[str, Any]:
        request = Request(
            f"{self._base_url}{endpoint}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": "steam-shortcuts/online-enrichment",
            },
        )
        try:
            response = self._transport(request)
        except HTTPError as error:
            raise SteamGridDbRequestFailed(f"HTTP {error.code}") from error
        except URLError as error:
            raise SteamGridDbRequestFailed(str(error.reason)) from error
        except OSError as error:
            raise SteamGridDbRequestFailed(str(error)) from error
        try:
            payload = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SteamGridDbRequestFailed("response was not valid JSON") from error
        if not isinstance(payload, dict):
            raise SteamGridDbRequestFailed("response root was not an object")
        if payload.get("success") is not True:
            raise SteamGridDbRequestFailed("service reported an unsuccessful response")
        return payload


def _default_transport(request: Request) -> bytes:
    with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed HTTPS API base URL
        content = response.read()
    if not isinstance(content, bytes):
        raise SteamGridDbRequestFailed("response body was not bytes")
    return content


def _game_from_payload(value: object) -> SteamGridDbGame:
    if not isinstance(value, dict):
        raise ValueError("SteamGridDB game candidate must be an object")
    game_id = value.get("id")
    name = value.get("name")
    types = value.get("types", [])
    verified = value.get("verified", False)
    if not isinstance(game_id, int) or isinstance(game_id, bool):
        raise ValueError("SteamGridDB game candidate id must be an integer")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("SteamGridDB game candidate name must be a nonblank string")
    if not isinstance(types, list) or not all(isinstance(item, str) for item in types):
        raise ValueError("SteamGridDB game candidate types must be a list of strings")
    if not isinstance(verified, bool):
        raise ValueError("SteamGridDB game candidate verified must be boolean")
    return SteamGridDbGame(id=game_id, name=name, types=tuple(types), verified=verified)
