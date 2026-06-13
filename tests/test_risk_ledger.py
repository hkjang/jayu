from datetime import datetime

import pytest

from jayu.risk_ledger import compute_risk_status


def test_loss_status_uses_daily_weekly_and_monthly_baselines():
    snapshots = [
        {
            "_timestamp": datetime.fromisoformat("2026-06-01T09:00:00+09:00"),
            "account_value_krw": 1_000_000,
        },
        {
            "_timestamp": datetime.fromisoformat("2026-06-12T09:00:00+09:00"),
            "account_value_krw": 900_000,
        },
    ]

    status = compute_risk_status(
        snapshots,
        now=datetime.fromisoformat("2026-06-13T09:00:00+09:00"),
        account_value_krw=850_000,
    )

    assert status["daily_return"] == pytest.approx(-0.055555, rel=1e-4)
    assert status["weekly_return"] == pytest.approx(-0.055555, rel=1e-4)
    assert status["monthly_drawdown"] == pytest.approx(0.15)
