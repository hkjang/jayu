from __future__ import annotations

import pytest

from jayu.costs import breakeven_transaction_cost, cost_sensitivity


def _trades_with_detail():
    return [
        {"gross_return_pct": 3.0, "net_return_pct": 2.7, "fee_cost_pct": 0.3, "position_pct": 10.0},
        {
            "gross_return_pct": -1.0,
            "net_return_pct": -1.3,
            "fee_cost_pct": 0.3,
            "position_pct": 10.0,
        },
    ]


def test_breakeven_is_mean_pre_fee_return():
    breakeven = breakeven_transaction_cost(_trades_with_detail())

    assert breakeven["has_cost_detail"] is True
    # mean of pre-fee returns (3.0, -1.0) = 1.0% = 100 bps round-trip head-room.
    assert breakeven["breakeven_round_trip_pct"] == pytest.approx(1.0)
    assert breakeven["breakeven_round_trip_bps"] == pytest.approx(100.0)


def test_breakeven_handles_empty():
    breakeven = breakeven_transaction_cost([])

    assert breakeven["trades"] == 0
    assert breakeven["breakeven_round_trip_bps"] == 0.0


def test_cost_sensitivity_flags_survival_per_level():
    # Pre-fee returns average 0.15% (= 15 bps): survives at 0/5/10, dies at 20/50.
    trades = [
        {"gross_return_pct": 0.20, "position_pct": 10.0},
        {"gross_return_pct": 0.10, "position_pct": 10.0},
    ]

    report = cost_sensitivity(trades, fee_levels_bps=(0, 5, 10, 20, 50))

    by_bps = {level["round_trip_bps"]: level for level in report["levels"]}
    assert by_bps[0]["survives"] is True
    assert by_bps[10]["survives"] is True
    assert by_bps[20]["survives"] is False
    assert by_bps[50]["survives"] is False
    assert report["max_survivable_bps"] == 10
    assert report["position_weighted"] is True


def test_cost_sensitivity_recompounds_total_return():
    trades = [
        {"gross_return_pct": 2.0, "position_pct": 50.0},
        {"gross_return_pct": 2.0, "position_pct": 50.0},
    ]

    report = cost_sensitivity(trades, fee_levels_bps=(0,))
    level = report["levels"][0]

    # Two trades, each +2% gross at 50% sizing => (1 + 0.5*0.02)^2 - 1 = 2.01%.
    assert level["total_return_pct"] == pytest.approx(2.01, abs=1e-2)


def test_degrades_without_cost_detail():
    trades = [{"ret": 1.0}, {"ret": -0.5}]

    breakeven = breakeven_transaction_cost(trades)
    report = cost_sensitivity(trades)

    assert breakeven["has_cost_detail"] is False
    assert breakeven["breakeven_round_trip_pct"] == pytest.approx(0.25)
    assert report["has_cost_detail"] is False
    assert report["position_weighted"] is False
