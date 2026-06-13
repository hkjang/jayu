from datetime import datetime, timedelta

import pytest

from jayu.risk_ledger import (
    _load_snapshots,
    compute_risk_status,
    record_portfolio_snapshot,
)


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


def test_compute_risk_status_handles_empty_and_zero_baseline():
    now = datetime.fromisoformat("2026-06-13T09:00:00+09:00")

    empty = compute_risk_status([], now=now, account_value_krw=1_000_000)
    assert empty["daily_return"] == 0.0
    assert empty["weekly_return"] == 0.0
    # No prior data and account == its own peak -> no drawdown.
    assert empty["monthly_drawdown"] == 0.0

    zero_baseline = compute_risk_status(
        [{"_timestamp": now, "account_value_krw": 0.0}],
        now=now,
        account_value_krw=1_000_000,
    )
    assert zero_baseline["daily_return"] == 0.0  # baseline 0 -> guarded


def _read_lines(path):
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_snapshot_appends_then_dedups_same_day(tmp_path):
    path = tmp_path / "snapshots.jsonl"
    day1 = datetime.fromisoformat("2026-06-13T10:00:00+09:00")

    record_portfolio_snapshot(path, account_value_krw=1_000_000, cash_balance_krw=200_000, now=day1)
    assert len(_read_lines(path)) == 1

    # Same day, identical values -> no new row.
    record_portfolio_snapshot(
        path,
        account_value_krw=1_000_000,
        cash_balance_krw=200_000,
        now=day1 + timedelta(hours=2),
    )
    assert len(_read_lines(path)) == 1

    # Same day, changed account value -> appended.
    record_portfolio_snapshot(
        path,
        account_value_krw=1_010_000,
        cash_balance_krw=200_000,
        now=day1 + timedelta(hours=3),
    )
    assert len(_read_lines(path)) == 2

    # Next day -> appended.
    record_portfolio_snapshot(
        path,
        account_value_krw=1_010_000,
        cash_balance_krw=200_000,
        now=day1 + timedelta(days=1),
    )
    assert len(_read_lines(path)) == 3


def test_record_snapshot_computes_status_from_history(tmp_path):
    path = tmp_path / "snapshots.jsonl"
    base = datetime.fromisoformat("2026-06-12T10:00:00+09:00")
    record_portfolio_snapshot(path, account_value_krw=1_000_000, cash_balance_krw=0.0, now=base)

    status = record_portfolio_snapshot(
        path,
        account_value_krw=950_000,
        cash_balance_krw=0.0,
        now=base + timedelta(days=1),
    )
    # Down 5% vs the prior-day baseline of 1,000,000.
    assert status["daily_return"] == pytest.approx(-0.05)
    assert status["monthly_drawdown"] == pytest.approx(0.05)


def test_load_snapshots_skips_malformed_and_sorts(tmp_path):
    path = tmp_path / "snapshots.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"timestamp": "2026-06-12T10:00:00+09:00", "account_value_krw": 1000}',
                "not-json-garbage",
                '{"account_value_krw": 500}',  # missing timestamp -> skipped
                '{"timestamp": "2026-06-10T10:00:00+09:00", "account_value_krw": 900}',
            ]
        ),
        encoding="utf-8",
    )

    rows = _load_snapshots(path)

    # Two valid rows, sorted ascending by timestamp.
    assert [row["account_value_krw"] for row in rows] == [900, 1000]


def test_load_snapshots_missing_file_is_empty(tmp_path):
    assert _load_snapshots(tmp_path / "absent.jsonl") == []
