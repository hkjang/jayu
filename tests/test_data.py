import pandas as pd

from jayu.data import (
    DataRequest,
    build_quality_report,
    dataframe_sha256,
    exchange_calendar_for_ticker,
)


def test_quality_report_rejects_invalid_ohlc():
    frame = pd.DataFrame(
        {
            "Open": [100],
            "High": [99],
            "Low": [98],
            "Close": [100],
            "Volume": [1000],
        },
        index=pd.to_datetime(["2026-01-02"]),
    )

    report = build_quality_report(DataRequest("TEST"), frame)

    assert not report.valid
    assert report.invalid_ohlc_rows == 1


def test_ohlcv_hash_depends_on_content_not_row_order():
    frame = pd.DataFrame(
        {
            "Open": [100, 101],
            "High": [102, 103],
            "Low": [99, 100],
            "Close": [101, 102],
            "Volume": [1000, 1100],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )

    assert dataframe_sha256(frame) == dataframe_sha256(frame.iloc[::-1])


def test_exchange_calendar_matches_us_and_korean_tickers():
    assert exchange_calendar_for_ticker("SOXL") == "XNYS"
    assert exchange_calendar_for_ticker("005930.KS") == "XKRX"
    assert exchange_calendar_for_ticker("247540.KQ") == "XKRX"


def test_quality_report_rejects_duplicate_unsorted_and_negative_volume():
    frame = pd.DataFrame(
        {
            "Open": [100, 101, 102],
            "High": [102, 103, 104],
            "Low": [99, 100, 101],
            "Close": [101, 102, 103],
            "Volume": [1000, -1, 1200],
        },
        index=pd.to_datetime(["2026-01-05", "2026-01-02", "2026-01-02"]),
    )

    report = build_quality_report(DataRequest("TEST"), frame)

    assert report.valid is False
    assert report.duplicate_index_count == 1
    assert report.non_monotonic_index is True
    assert report.invalid_volume_rows == 1
