from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jayu.io import read_json
from jayu.stock_lifecycle import build_stock_lifecycle_report, write_stock_lifecycle_report


def test_stock_lifecycle_tracks_transitions_and_reasons() -> None:
    previous = {
        "states": {
            "SOXL": {
                "ticker": "SOXL",
                "status": "candidate",
                "transitioned_at": "2026-06-20T00:00:00+00:00",
            }
        },
        "history": [],
    }

    report = build_stock_lifecycle_report(
        {
            "SOXL": {
                "action": "buy",
                "eligible": False,
                "blocked": True,
                "reason_codes": ["SECTOR_EXPOSURE_EXCEEDED"],
            },
            "TQQQ": {"action": "sell", "eligible": True},
            "QBTS": {"action": "hold"},
        },
        [{"symbol": "TQQQ", "quantity": 2, "market_value_krw": 500000}],
        previous=previous,
        now=datetime(2026, 6, 22, tzinfo=UTC),
    )

    states = {item["ticker"]: item for item in report["items"]}
    assert states["SOXL"]["status"] == "caution"
    assert states["SOXL"]["previous_status"] == "candidate"
    assert states["SOXL"]["related_risk_codes"] == ["SECTOR_EXPOSURE_EXCEEDED"]
    assert states["TQQQ"]["status"] == "reduce"
    assert states["TQQQ"]["holding"] is True
    assert states["QBTS"]["status"] == "watch"
    assert report["summary"]["status_counts"]["caution"] == 1
    assert report["history"][0]["from_status"] == "candidate"
    assert report["history"][0]["to_status"] == "caution"


def test_stock_lifecycle_persists_history(tmp_path: Path) -> None:
    output = tmp_path / "stock_lifecycle.json"
    first = write_stock_lifecycle_report(
        {"AAPL": {"action": "buy", "eligible": True}},
        [],
        output,
        now=datetime(2026, 6, 21, tzinfo=UTC),
    )
    second = write_stock_lifecycle_report(
        {"AAPL": {"action": "buy", "eligible": False, "blocked": True}},
        [],
        output,
        now=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert first["states"]["AAPL"]["status"] == "candidate"
    assert second["states"]["AAPL"]["status"] == "caution"
    assert second["history"][-1]["from_status"] == "candidate"
    assert second["history"][-1]["to_status"] == "caution"
    assert read_json(output)["states"]["AAPL"]["status"] == "caution"
