import numpy as np
import pandas as pd
import pandas.testing as pdt

from jayu.engine import add_indicators, compute_atr, compute_true_range


def test_true_range_includes_previous_close_gap():
    frame = pd.read_csv(
        "tests/fixtures/ohlcv_known.csv",
        parse_dates=["Date"],
        index_col="Date",
    )

    result = compute_true_range(frame)

    assert result.tolist() == [2.0, 3.0, 4.0]
    assert not compute_atr(frame, period=2).dropna().empty


def test_future_rows_do_not_change_past_indicators():
    dates = pd.bdate_range("2025-01-01", periods=280)
    close = pd.Series(np.linspace(100, 140, len(dates)), index=dates)
    frame = pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1_000_000,
        }
    )
    baseline = add_indicators(frame)
    changed = frame.copy()
    changed.loc[dates[260] :, ["Open", "High", "Low", "Close"]] *= 5
    recalculated = add_indicators(changed)
    common = baseline.index[baseline.index < dates[260]]

    pdt.assert_frame_equal(
        baseline.loc[common],
        recalculated.loc[common],
        check_dtype=False,
    )
    assert baseline.attrs["warmup_rows_dropped"] >= 199
    assert baseline.attrs["indicator_warmup_rows"]["adx"] == 28
    assert baseline.attrs["indicator_warmup_rows"]["sma200"] == 200
