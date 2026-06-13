from __future__ import annotations

import numpy as np
import pandas as pd

from jayu.engine import add_indicators
from jayu.validation import (
    assert_no_lookahead,
    assert_purged_splits,
    purged_walk_forward_splits,
)


def test_purged_walk_forward_folds_are_disjoint():
    splits = purged_walk_forward_splits(
        900,
        train_rows=378,
        validation_rows=63,
        windows=3,
        purge_rows=5,
        embargo_rows=2,
    )

    assert len(splits) == 3
    assert_purged_splits(splits)
    for split in splits:
        assert split.train_end + 5 == split.validation_start


def test_automatic_lookahead_check_for_all_indicators():
    dates = pd.bdate_range("2024-01-01", periods=320)
    close = pd.Series(np.linspace(100, 160, len(dates)), index=dates)
    frame = pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 1_500_000, len(dates)),
        }
    )

    assert_no_lookahead(frame, add_indicators, cutoff=285)
