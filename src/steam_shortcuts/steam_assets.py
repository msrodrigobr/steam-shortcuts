"""Unauthenticated official Steam library artwork lookup."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .errors import SteamStoreRequestFailed
from .models import SteamLibraryArtwork

_ITEMS_URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"
_ASSETS_BASE_URL = "https://shared.fastly.steamstatic.com/store_item_assets/"
Transport = Callable[[Request], bytes]


def get_steam_library_artwork(
    app_id: int,
    *,
    transport: Transport | None = None,
) -> SteamLibraryArtwork:
    """Resolve official library art through Steam's public, unauthenticated API."""
    if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
        raise ValueError("Steam AppID must be a positive integer")

    input_payload = {
        "ids": [{"appid": app_id}],
        "context": {"country_code": "US", "language": "english"},
        "data_request": {"include_assets": True},
    }
    encoded_payload = urlencode(
        {"input_json": json.dumps(input_payload, separators=(",", ":"))}
    )
    request = Request(
        f"{_ITEMS_URL}?{encoded_payload}",
        headers={
            "Accept": "application/json",
            "User-Agent": "steam-shortcuts/online-enrichment",
        },
    )
    content = _request_bytes(request, transport if transport is not None else _default_transport)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SteamStoreRequestFailed("library assets response was not valid JSON") from error
    if not isinstance(payload, dict):
        raise SteamStoreRequestFailed("library assets response root was not an object")
    response = payload.get("response")
    if not isinstance(response, dict):
        raise SteamStoreRequestFailed("library assets response did not contain a response object")
    store_items = response.get("store_items")
    if not isinstance(store_items, list):
        raise SteamStoreRequestFailed("library assets response did not contain store_items")
    item = next(
        (
            candidate
            for candidate in store_items
            if isinstance(candidate, dict)
            and candidate.get("appid", candidate.get("id")) == app_id
            and candidate.get("success") == 1
        ),
        None,
    )
    if item is None:
        raise SteamStoreRequestFailed(f"Steam did not return library assets for AppID {app_id}")
    assets = item.get("assets")
    if not isinstance(assets, dict):
        raise SteamStoreRequestFailed(f"Steam AppID {app_id} has no library asset metadata")
    template = assets.get("asset_url_format")
    if not isinstance(template, str):
        raise SteamStoreRequestFailed(f"Steam AppID {app_id} has no asset URL template")

    portrait_url = _asset_url(
        app_id,
        template,
        _first_string(assets, "library_capsule_2x", "library_capsule"),
    )
    hero_url = _asset_url(
        app_id,
        template,
        _first_string(assets, "library_hero_2x", "library_hero"),
    )
    logo_url = _asset_url(
        app_id,
        template,
        _first_string(assets, "library_logo_2x", "library_logo"),
    )
    if logo_url is None:
        logo_url = f"{_ASSETS_BASE_URL}steam/apps/{app_id}/logo.png"
    return SteamLibraryArtwork(
        app_id=app_id,
        portrait_url=portrait_url,
        hero_url=hero_url,
        logo_url=logo_url,
    )


def download_steam_asset(
    url: str,
    *,
    transport: Transport | None = None,
) -> bytes:
    """Download one Steam library image from Steam's public CDN."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc not in {
        "shared.fastly.steamstatic.com",
        "shared.akamai.steamstatic.com",
    }:
        raise ValueError("Steam artwork URL must use Steam's HTTPS asset CDN")
    request = Request(
        url,
        headers={
            "Accept": "image/*",
            "User-Agent": "steam-shortcuts/online-enrichment",
        },
    )
    content = _request_bytes(request, transport if transport is not None else _default_transport)
    suffix = parsed.path.casefold()
    if suffix.endswith((".jpg", ".jpeg")):
        if not content.startswith(b"\xff\xd8\xff"):
            raise SteamStoreRequestFailed("Steam artwork response was not a JPEG image")
    elif suffix.endswith(".png"):
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SteamStoreRequestFailed("Steam artwork response was not a PNG image")
    else:
        raise SteamStoreRequestFailed("Steam artwork URL has an unsupported image format")
    return content


def _asset_url(app_id: int, template: str, filename: str | None) -> str | None:
    if filename is None:
        return None
    if "${FILENAME}" not in template:
        raise SteamStoreRequestFailed("Steam library asset URL template is malformed")
    path = template.replace("${FILENAME}", filename)
    parsed = urlsplit(path)
    prefix = f"steam/apps/{app_id}/"
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith(prefix)
        or ".." in parsed.path.split("/")
        or "\\" in parsed.path
    ):
        raise SteamStoreRequestFailed("Steam library asset metadata contained an unsafe path")
    return f"{_ASSETS_BASE_URL}{path}"


def _first_string(values: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


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
        raise SteamStoreRequestFailed("Steam response was empty")
    return content


def _default_transport(request: Request) -> bytes:
    with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed Steam API/CDN endpoints
        content = response.read()
    if not isinstance(content, bytes):
        raise SteamStoreRequestFailed("Steam response body was not bytes")
    return content
