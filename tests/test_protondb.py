from __future__ import annotations

import json
from urllib.request import Request

from steam_shortcuts.protondb import get_protondb_report


def test_get_protondb_report_returns_compatibility_evidence_without_inventing_a_tool() -> None:
    requests: list[Request] = []

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(
            {
                "tier": "gold",
                "bestReportedTier": "platinum",
                "trendingTier": "platinum",
                "confidence": "strong",
                "score": 0.72,
                "total": 2075,
            }
        ).encode()

    report = get_protondb_report(730, transport=transport)

    assert report.app_id == 730
    assert report.tier == "gold"
    assert report.best_reported_tier == "platinum"
    assert report.trending_tier == "platinum"
    assert report.confidence == "strong"
    assert report.score == 0.72
    assert report.total_reports == 2075
    assert requests[0].full_url.endswith("/reports/summaries/730.json")
