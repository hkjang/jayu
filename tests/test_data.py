import pandas as pd

from jayu.data import DataRequest, build_quality_report, dataframe_sha256


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
