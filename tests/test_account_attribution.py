from __future__ import annotations

from datetime import UTC, datetime

from jayu.account_attribution import (
    build_account_attribution_report,
    write_account_attribution_report,
)


def test_account_attribution_decomposes_price_fx_cash_and_flow(tmp_path):
    previous = {
        "summary": {"total_market_value_krw": 1_000_000, "cash_available": 200_000},
        "holdings": [
            {"symbol": "AAPL", "market_value_krw": 500_000, "currency": "USD"},
            {"symbol": "005930", "market_value_krw": 500_000, "currency": "KRW"},
        ],
    }
    current = {
        "summary": {"total_market_value_krw": 1_090_000, "cash_available": 150_000},
        "holdings": [
            {
                "symbol": "AAPL",
                "market_value_krw": 560_000,
                "currency": "USD",
                "asset_effect_krw": 40_000,
                "fx_effect_krw": 10_000,
                "cross_effect_krw": 0,
            },
            {
                "symbol": "005930",
                "market_value_krw": 480_000,
                "currency": "KRW",
                "asset_effect_krw": -20_000,
                "fx_effect_krw": 0,
                "cross_effect_krw": 0,
            },
            {"symbol": "NVDA", "market_value_krw": 50_000, "currency": "USD"},
        ],
    }

    report = build_account_attribution_report(
        previous,
        current,
        now=datetime(2026, 6, 21, tzinfo=UTC),
    )

    assert report["status"] == "success"
    assert report["summary"]["account_value_delta_krw"] == 40_000
    assert report["summary"]["price_effect_krw"] == 20_000
    assert report["summary"]["fx_effect_krw"] == 10_000
    assert report["summary"]["cash_delta_krw"] == -50_000
    assert report["summary"]["holding_flow_krw"] == 60_000
    assert report["summary"]["residual_effect_krw"] == 0
    nvda = next(row for row in report["rows"] if row["symbol"] == "NVDA")
    assert nvda["position_status"] == "new"
    assert nvda["holding_flow_krw"] == 50_000


def test_account_attribution_write_report(tmp_path):
    output = tmp_path / "account_attribution.json"
    report = write_account_attribution_report(
        [{"symbol": "AAPL", "market_value_krw": 100_000}],
        [{"symbol": "AAPL", "market_value_krw": 110_000, "asset_effect_krw": 10_000, "fx_effect_krw": 0}],
        output,
        now=datetime(2026, 6, 21, tzinfo=UTC),
    )

    assert output.exists()
    assert report["summary"]["market_value_delta_krw"] == 10_000
    assert report["rows"][0]["dominant_effect"] == "price"
