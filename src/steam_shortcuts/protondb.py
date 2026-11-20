"""Read-only ProtonDB compatibility summaries without changing Steam settings."""

from __future__ import annotations

import json
from collections.abc import Callable
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import ProtonDbRequestFailed
from .models import ProtonDbReport

_SUMMARY_URL = "https://www.protondb.com/api/v1/reports/summaries"
Transport = Callable[[Request], bytes]


def get_protondb_report(app_id: int, *, transport: Transport | None = None) -> ProtonDbReport:
    """Fetch compatibility evidence for an explicit Steam AppID.

    ProtonDB's summary endpoint deliberately does not identify a canonical
    Proton build, so this function reports evidence and never guesses a tool.
    """
    if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
        raise ValueError("Steam AppID must be a positive integer")
    request = Request(
        f"{_SUMMARY_URL}/{app_id}.json",
        headers={
            "Accept": "application/json",
            "User-Agent": "steam-shortcuts/online-enrichment",
        },
    )
    response = _request_bytes(request, transport if transport is not None else _default_transport)
    try:
        payload = json.loads(response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtonDbRequestFailed("response was not valid JSON") from error
    if not isinstance(payload, dict):
        raise ProtonDbRequestFailed("response root was not an object")
    return _report_from_payload(app_id, payload)


def _request_bytes(request: Request, transport: Transport) -> bytes:
    try:
        content = transport(request)
    except HTTPError as error:
        raise ProtonDbRequestFailed(f"HTTP {error.code}") from error
    except URLError as error:
        raise ProtonDbRequestFailed(str(error.reason)) from error
    except HTTPException as error:
        raise ProtonDbRequestFailed(f"incomplete HTTP response: {error}") from error
    except OSError as error:
        raise ProtonDbRequestFailed(str(error)) from error
    if not content:
        raise ProtonDbRequestFailed("response was empty")
    return content


def _default_transport(request: Request) -> bytes:
    with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed HTTPS ProtonDB API URL
        content = response.read()
    if not isinstance(content, bytes):
        raise ProtonDbRequestFailed("response body was not bytes")
    return content


def _report_from_payload(app_id: int, payload: dict[object, object]) -> ProtonDbReport:
    tier = _nonblank_string(payload.get("tier"), "tier")
    best_reported_tier = _nonblank_string(payload.get("bestReportedTier"), "bestReportedTier")
    trending_tier = _nonblank_string(payload.get("trendingTier"), "trendingTier")
    confidence = _nonblank_string(payload.get("confidence"), "confidence")
    score = payload.get("score")
    total = payload.get("total")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ProtonDbRequestFailed("response score was not numeric")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ProtonDbRequestFailed("response total was not a non-negative integer")
    return ProtonDbReport(
        app_id=app_id,
        tier=tier,
        best_reported_tier=best_reported_tier,
        trending_tier=trending_tier,
        confidence=confidence,
        score=float(score),
        total_reports=total,
    )


def _nonblank_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtonDbRequestFailed(f"response {field_name} was blank")
    return value
