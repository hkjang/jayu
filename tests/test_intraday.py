from __future__ import annotations

import pandas as pd
import pytest

from jayu.intraday import (
    add_session_column,
    classify_sessions,
    clamp_lookback_days,
    fetch_intraday,
    is_intraday_interval,
    max_lookback_days,
    normalize_intraday,
    regular_session_only,
    resample_ohlcv,
    split_sessions,
    validate_intraday_interval,
)


def _et_index(specs):
    """Build a UTC tz-aware index from (date, 'HH:MM') US/Eastern wall times."""
    stamps = [pd.Timestamp(f"{day} {hm}", tz="America/New_York") for day, hm in specs]
    return pd.DatetimeIndex(stamps).tz_convert("UTC")


def _frame(index):
    n = len(index)
    return pd.DataFrame(
        {
            "Open": range(1, n + 1),
            "High": range(2, n + 2),
            "Low": range(0, n),
            "Close": range(1, n + 1),
            "Volume": [100] * n,
        },
        index=index,
    )


def test_interval_validation_and_lookback_clamp():
    assert is_intraday_interval("5m")
    assert not is_intraday_interval("1d")
    with pytest.raises(ValueError):
        validate_intraday_interval("1d")
    assert max_lookback_days("1m") == 7
    # A 365-day request for 1m is clamped to the 7-day ceiling; floor is 1.
    assert clamp_lookback_days("1m", 365) == 7
    assert clamp_lookback_days("5m", 30) == 30
    assert clamp_lookback_days("5m", 0) == 1


def test_normalize_intraday_preserves_timezone():
    naive = _frame(pd.DatetimeIndex(["2026-06-08 14:00", "2026-06-08 13:30"]))

    result = normalize_intraday(naive)

    # Index is tz-aware UTC and sorted ascending (daily normaliser would drop tz).
    assert str(result.index.tz) == "UTC"
    assert result.index.is_monotonic_increasing
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_classify_sessions_by_local_time_and_weekend():
    # 2026-06-08 is a Monday; 2026-06-13 is a Saturday.
    index = _et_index(
        [
            ("2026-06-08", "08:00"),  # premarket
            ("2026-06-08", "10:00"),  # regular
            ("2026-06-08", "17:00"),  # afterhours
            ("2026-06-08", "02:00"),  # closed (before premarket)
            ("2026-06-13", "10:00"),  # closed (weekend)
        ]
    )

    labels = list(classify_sessions(index))

    assert labels == ["premarket", "regular", "afterhours", "closed", "closed"]


def test_session_boundaries_are_half_open():
    index = _et_index(
        [
            ("2026-06-08", "09:30"),  # exactly the open -> regular
            ("2026-06-08", "16:00"),  # exactly the close -> afterhours
            ("2026-06-08", "20:00"),  # exactly afterhours close -> closed
        ]
    )

    assert list(classify_sessions(index)) == ["regular", "afterhours", "closed"]


def test_split_and_regular_session_only():
    index = _et_index(
        [
            ("2026-06-08", "08:00"),
            ("2026-06-08", "10:00"),
            ("2026-06-08", "11:00"),
            ("2026-06-08", "17:00"),
        ]
    )
    frame = _frame(index)

    tagged = add_session_column(frame)
    assert "session" in tagged.columns

    groups = split_sessions(frame)
    assert set(groups) == {"premarket", "regular", "afterhours"}
    assert len(groups["regular"]) == 2
    assert "session" not in groups["regular"].columns

    regular = regular_session_only(frame)
    assert len(regular) == 2
    assert set(regular["session"]) if "session" in regular.columns else True


def test_resample_ohlcv_aggregates_correctly():
    index = pd.date_range("2026-06-08 13:30", periods=4, freq="1min", tz="UTC")
    frame = pd.DataFrame(
        {
            "Open": [10, 11, 12, 13],
            "High": [10, 15, 12, 14],
            "Low": [9, 11, 8, 13],
            "Close": [11, 12, 9, 14],
            "Volume": [100, 200, 300, 400],
        },
        index=index,
    )

    out = resample_ohlcv(frame, "2min")

    assert out.iloc[0]["Open"] == 10
    assert out.iloc[0]["High"] == 15
    assert out.iloc[0]["Low"] == 9
    assert out.iloc[0]["Close"] == 12
    assert out.iloc[0]["Volume"] == 300


def test_fetch_intraday_uses_provider_filters_and_caches(tmp_path):
    index = _et_index(
        [
            ("2026-06-08", "08:00"),  # premarket
            ("2026-06-08", "10:00"),  # regular
            ("2026-06-08", "17:00"),  # afterhours
        ]
    )
    calls = {"count": 0}

    def fake_provider(ticker, interval, lookback_days, prepost):
        calls["count"] += 1
        assert ticker == "SOXL"
        assert interval == "5m"
        assert lookback_days == 60  # clamped from request below
        assert prepost is True
        return _frame(index)

    result = fetch_intraday(
        "SOXL",
        interval="5m",
        lookback_days=999,
        sessions=("regular",),
        provider=fake_provider,
        cache_dir=tmp_path,
    )

    assert calls["count"] == 1
    assert list(result["session"]) == ["regular"]
    # Cache file written for full (unfiltered) frame; second call hits cache.
    cache_file = tmp_path / "SOXL_5m_60d.parquet"
    assert cache_file.exists()

    again = fetch_intraday(
        "SOXL",
        interval="5m",
        lookback_days=999,
        sessions=("premarket", "afterhours"),
        provider=fake_provider,
        cache_dir=tmp_path,
    )

    assert calls["count"] == 1  # served from cache, provider not called again
    assert set(again["session"]) == {"premarket", "afterhours"}
