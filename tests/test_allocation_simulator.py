from __future__ import annotations

from datetime import UTC, datetime

from jayu.allocation_simulator import (
    build_allocation_preview_report,
    write_allocation_preview_report,
)


def test_allocation_preview_applies_orders_and_cash_limits(tmp_path):
    report = build_allocation_preview_report(
        {
            "orders": [
                {
                    "ticker": "TSLA",
                    "action": "BUY",
                    "estimated_cash_krw": 100_000,
                    "sector": "Consumer",
                }
            ]
        },
        [
            {
                "ticker": "AAPL",
                "market_value_krw": 400_000,
                "sector": "Technology",
            }
        ],
        cash_krw=200_000,
        settings={
            "max_single_position_pct": 0.70,
            "max_sector_exposure": 0.75,
            "min_cash_pct": 0.15,
        },
        now=datetime(2026, 6, 21, tzinfo=UTC),
    )

    assert report["status"] == "success"
    assert report["summary"]["after_cash_krw"] == 100_000
    assert report["summary"]["cash_pct_after"] == 0.166667
    assert report["summary"]["applied_order_count"] == 1
    assert report["summary"]["max_position_breach_count"] == 0
    assert report["orders"][0]["cash_source"] == "estimated_cash_krw"
    tsla = next(row for row in report["holdings"] if row["ticker"] == "TSLA")
    assert tsla["after_weight"] == 0.166667


def test_allocation_preview_blocks_sector_and_cash_breaches(tmp_path):
    output = tmp_path / "allocation_preview.json"
    report = write_allocation_preview_report(
        {
            "orders": [
                {
                    "ticker": "NVDA",
                    "action": "BUY",
                    "estimated_cash_krw": 450_000,
                    "sector": "Technology",
                }
            ]
        },
        [
            {
                "ticker": "AAPL",
                "market_value_krw": 400_000,
                "sector": "Technology",
            }
        ],
        output,
        cash_krw=500_000,
        settings={
            "max_single_position_pct": 0.60,
            "max_sector_exposure": 0.80,
            "min_cash_pct": 0.10,
        },
        now=datetime(2026, 6, 21, tzinfo=UTC),
    )

    assert output.exists()
    assert report["status"] == "blocked"
    assert report["summary"]["after_cash_krw"] == 50_000
    assert report["summary"]["sector_breach_count"] == 1
    assert any(item["id"] == "cash_floor" and item["status"] == "blocked" for item in report["limit_checks"])
    assert any(row["sector"] == "Technology" and row["status"] == "blocked" for row in report["sector_totals"])
