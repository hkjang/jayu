from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Iterable

import pandas as pd
import pandas.testing as pdt


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    purge_rows: int
    embargo_rows: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def purged_walk_forward_splits(
    row_count: int,
    *,
    train_rows: int,
    validation_rows: int,
    windows: int,
    purge_rows: int,
    embargo_rows: int,
    minimum_train_rows: int = 220,
    minimum_validation_rows: int = 20,
) -> list[WalkForwardFold]:
    if row_count <= 0:
        return []
    folds: list[WalkForwardFold] = []
    validation_end = row_count
    for fold_number in range(windows):
        validation_start = validation_end - validation_rows
        train_end = validation_start - purge_rows
        train_start = max(0, train_end - train_rows)
        if (
            train_end - train_start < minimum_train_rows
            or validation_end - validation_start < minimum_validation_rows
        ):
            break
        folds.append(
            WalkForwardFold(
                fold=fold_number,
                train_start=train_start,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
                purge_rows=purge_rows,
                embargo_rows=embargo_rows,
            )
        )
        validation_end = validation_start - embargo_rows
    return list(reversed(folds))


def assert_purged_splits(splits: Iterable[WalkForwardFold]) -> None:
    previous_validation_end = -1
    for split in splits:
        if split.train_end + split.purge_rows > split.validation_start:
            raise AssertionError(f"fold {split.fold} has no purge gap")
        if split.validation_start < previous_validation_end:
            raise AssertionError(f"fold {split.fold} overlaps a prior validation fold")
        previous_validation_end = split.validation_end + split.embargo_rows


def assert_no_lookahead(
    raw: pd.DataFrame,
    indicator_builder: Callable[[pd.DataFrame], pd.DataFrame],
    *,
    cutoff: int,
    columns: Iterable[str] | None = None,
    multiplier: float = 7.0,
) -> None:
    if cutoff <= 0 or cutoff >= len(raw):
        raise ValueError("cutoff must split the input into past and future rows")
    baseline = indicator_builder(raw)
    changed = raw.copy()
    future_index = changed.index[cutoff:]
    price_columns = [
        column for column in ("Open", "High", "Low", "Close", "Volume") if column in changed
    ]
    changed.loc[future_index, price_columns] *= multiplier
    recalculated = indicator_builder(changed)
    common = baseline.index.intersection(recalculated.index)
    past = common[common < raw.index[cutoff]]
    selected = list(columns) if columns else list(baseline.columns)
    pdt.assert_frame_equal(
        baseline.loc[past, selected],
        recalculated.loc[past, selected],
        check_dtype=False,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
