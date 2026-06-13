"""Double out-of-sample validation with a one-time final lockbox.

Roadmap module ``jayu.validation.double_oos`` (#7, #10, #40). Plain walk-forward
(``jayu.validation.purged_walk_forward_splits``) reuses the same OOS windows on
every development iteration, so the reported OOS score drifts upward as the
search overfits to those windows. The fix is a *second*, truly untouched
out-of-sample region:

* The most recent ``lockbox_fraction`` of the timeline is carved off as a
  **final lockbox**, separated from the development region by a purge+embargo
  gap so no information leaks across the boundary.
* All training, validation and parameter search happen on the development
  region only.
* The lockbox is evaluated **exactly once**, at the very end. :class:`LockboxLedger`
  persists which lockboxes have been opened so a second peek raises instead of
  silently inflating the reported score.

:func:`double_oos_evaluate` is engine-agnostic: it takes an injected
``evaluate_fn(df_slice) -> metrics`` so it stays pure and offline-testable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .io import atomic_write_json, read_json


class LockboxReuseError(RuntimeError):
    """Raised when a sealed (already-opened) lockbox is opened again."""


@dataclass(frozen=True)
class LockboxSplit:
    development_start: int
    development_end: int
    lockbox_start: int
    lockbox_end: int
    purge_rows: int
    embargo_rows: int

    @property
    def development_rows(self) -> int:
        return self.development_end - self.development_start

    @property
    def lockbox_rows(self) -> int:
        return self.lockbox_end - self.lockbox_start

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def lockbox_split(
    row_count: int,
    *,
    lockbox_fraction: float = 0.2,
    purge_rows: int = 5,
    embargo_rows: int = 1,
    minimum_dev_rows: int = 220,
    minimum_lockbox_rows: int = 40,
) -> LockboxSplit | None:
    """Carve the final ``lockbox_fraction`` of rows into an isolated lockbox.

    A purge+embargo gap sits between the development region and the lockbox.
    Returns ``None`` when either region would be too small to be meaningful.
    """
    if row_count <= 0:
        return None
    if not 0.0 < lockbox_fraction < 1.0:
        raise ValueError("lockbox_fraction must be between 0 and 1 (exclusive)")
    lockbox_size = int(row_count * lockbox_fraction)
    if lockbox_size < minimum_lockbox_rows:
        return None
    lockbox_start = row_count - lockbox_size
    development_end = lockbox_start - (purge_rows + embargo_rows)
    if development_end < minimum_dev_rows:
        return None
    return LockboxSplit(
        development_start=0,
        development_end=development_end,
        lockbox_start=lockbox_start,
        lockbox_end=row_count,
        purge_rows=purge_rows,
        embargo_rows=embargo_rows,
    )


def assert_lockbox_isolation(split: LockboxSplit) -> None:
    """Verify the development region and lockbox cannot leak into each other."""
    if split.development_end + split.purge_rows + split.embargo_rows > split.lockbox_start:
        raise AssertionError("lockbox lacks a full purge+embargo gap from development")
    if split.lockbox_start < split.development_end:
        raise AssertionError("lockbox overlaps the development region")
    if split.lockbox_end > split.lockbox_start and split.development_rows <= 0:
        raise AssertionError("development region is empty")


def double_oos_evaluate(
    data: pd.DataFrame,
    *,
    split: LockboxSplit,
    evaluate_fn: Callable[[pd.DataFrame], Mapping[str, Any] | None],
    metric_key: str = "fitness",
) -> dict[str, Any]:
    """Evaluate a strategy on the development region and, once, on the lockbox.

    ``lockbox_retention`` is lockbox/development for ``metric_key`` — a proxy for
    how much edge survives on never-seen data. ``degraded`` flags a lockbox
    metric that is non-positive or retained below half.
    """
    assert_lockbox_isolation(split)
    development = data.iloc[split.development_start : split.development_end]
    lockbox = data.iloc[split.lockbox_start : split.lockbox_end]
    development_metrics = evaluate_fn(development)
    lockbox_metrics = evaluate_fn(lockbox)

    retention: float | None = None
    degraded: bool | None = None
    if (
        isinstance(development_metrics, Mapping)
        and isinstance(lockbox_metrics, Mapping)
        and metric_key in development_metrics
        and metric_key in lockbox_metrics
    ):
        dev_value = float(development_metrics[metric_key])
        lock_value = float(lockbox_metrics[metric_key])
        retention = round(lock_value / dev_value, 4) if dev_value != 0 else None
        degraded = lock_value <= 0 or (retention is not None and retention < 0.5)

    return {
        "split": split.to_dict(),
        "metric_key": metric_key,
        "development": development_metrics,
        "lockbox": lockbox_metrics,
        "lockbox_retention": retention,
        "degraded": degraded,
    }


class LockboxLedger:
    """Append-only record of which lockboxes have been opened (one peek allowed).

    Keyed by an arbitrary string (e.g. dataset hash + strategy id). Backed by a
    JSON file so the seal survives across process runs.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        data = read_json(self.path, default={})
        return data if isinstance(data, dict) else {}

    def is_sealed(self, key: str) -> bool:
        """True once ``key`` has been opened at least once."""
        return key in self._load()

    def opens(self, key: str) -> dict[str, Any] | None:
        record = self._load().get(key)
        return record if isinstance(record, dict) else None

    def record_open(
        self,
        key: str,
        *,
        metrics: Mapping[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Record a lockbox open. Raises :class:`LockboxReuseError` on reuse.

        ``force=True`` deliberately re-opens (incrementing the count) — use only
        when you accept that the lockbox is no longer a clean OOS.
        """
        data = self._load()
        existing = data.get(key) if isinstance(data.get(key), dict) else None
        if existing is not None and not force:
            raise LockboxReuseError(
                f"lockbox {key!r} was already opened; reuse would invalidate the OOS"
            )
        open_count = int(existing.get("open_count", 0)) + 1 if existing else 1
        record = {"open_count": open_count, "metrics": dict(metrics) if metrics else None}
        data[key] = record
        atomic_write_json(self.path, data)
        return record
