from __future__ import annotations

import pandas as pd
import pytest

from jayu.double_oos import (
    LockboxLedger,
    LockboxReuseError,
    LockboxSplit,
    assert_lockbox_isolation,
    double_oos_evaluate,
    evaluate_final_lockbox,
    final_lockbox_key,
    lockbox_split,
)


def test_lockbox_split_carves_gapped_final_region():
    split = lockbox_split(1000, lockbox_fraction=0.2, purge_rows=5, embargo_rows=1)

    assert split is not None
    assert split.lockbox_start == 800  # last 20%
    assert split.lockbox_end == 1000
    assert split.development_end == 800 - 6  # purge + embargo gap
    assert split.development_rows == 794
    assert split.lockbox_rows == 200
    assert_lockbox_isolation(split)


def test_lockbox_split_returns_none_when_too_small():
    # 100 rows, 20% lockbox = 20 < default minimum_lockbox_rows (40).
    assert lockbox_split(100, lockbox_fraction=0.2) is None
    # Lockbox big enough but development too small.
    assert lockbox_split(300, lockbox_fraction=0.5, minimum_dev_rows=220) is None


def test_lockbox_split_validates_fraction():
    with pytest.raises(ValueError):
        lockbox_split(1000, lockbox_fraction=1.5)


def test_assert_isolation_rejects_overlap():
    bad = LockboxSplit(
        development_start=0,
        development_end=805,
        lockbox_start=800,
        lockbox_end=1000,
        purge_rows=5,
        embargo_rows=1,
    )
    with pytest.raises(AssertionError):
        assert_lockbox_isolation(bad)


def test_double_oos_evaluate_computes_retention():
    data = pd.DataFrame({"Close": range(1000)})
    split = lockbox_split(1000, lockbox_fraction=0.2)

    # Fake evaluator: development scores 1.0, lockbox scores 0.4 (60% decay).
    def evaluate(df):
        return {"fitness": 1.0 if len(df) > 300 else 0.4}

    report = double_oos_evaluate(data, split=split, evaluate_fn=evaluate)

    assert report["development"]["fitness"] == 1.0
    assert report["lockbox"]["fitness"] == 0.4
    assert report["lockbox_retention"] == pytest.approx(0.4)
    assert report["degraded"] is True  # retained below half


def test_double_oos_marks_healthy_when_retained():
    data = pd.DataFrame({"Close": range(1000)})
    split = lockbox_split(1000, lockbox_fraction=0.2)

    def evaluate(df):
        return {"fitness": 1.0 if len(df) > 300 else 0.8}

    report = double_oos_evaluate(data, split=split, evaluate_fn=evaluate)
    assert report["lockbox_retention"] == pytest.approx(0.8)
    assert report["degraded"] is False


def test_lockbox_ledger_blocks_reuse(tmp_path):
    ledger = LockboxLedger(tmp_path / "lockbox.json")
    key = "dataset_abc:strategy_1"

    assert not ledger.is_sealed(key)
    ledger.record_open(key, metrics={"fitness": 0.5})
    assert ledger.is_sealed(key)
    assert ledger.opens(key)["open_count"] == 1

    with pytest.raises(LockboxReuseError):
        ledger.record_open(key)

    # force re-open is allowed but counted.
    record = ledger.record_open(key, force=True)
    assert record["open_count"] == 2


def test_lockbox_ledger_persists_across_instances(tmp_path):
    path = tmp_path / "lockbox.json"
    LockboxLedger(path).record_open("k")

    # A fresh ledger instance reading the same file still sees the seal.
    assert LockboxLedger(path).is_sealed("k")


def test_final_lockbox_is_evaluated_once_and_reused(tmp_path):
    data = pd.DataFrame({"Close": range(1000)})
    split = lockbox_split(1000, lockbox_fraction=0.2)
    ledger = LockboxLedger(tmp_path / "lockbox.json")
    calls = 0

    def evaluate(frame):
        nonlocal calls
        calls += 1
        assert len(frame) == split.lockbox_rows
        return {"total_return": 8.0, "trades": 4}

    key = final_lockbox_key(
        data_hash="data",
        ticker="SOXL",
        regime="bull",
        params={"rsi_lo": 30},
        split=split,
        fitness_version="v2_daily_equity",
    )
    first = evaluate_final_lockbox(
        data,
        split=split,
        development_metrics={"total_return": 10.0},
        evaluate_fn=evaluate,
        ledger=ledger,
        ledger_key=key,
    )
    second = evaluate_final_lockbox(
        data,
        split=split,
        development_metrics={"total_return": 10.0},
        evaluate_fn=evaluate,
        ledger=ledger,
        ledger_key=key,
    )
    stricter = evaluate_final_lockbox(
        data,
        split=split,
        development_metrics={"total_return": 10.0},
        evaluate_fn=evaluate,
        ledger=ledger,
        ledger_key=key,
        minimum_retention=0.9,
    )

    assert first["approved"] is True
    assert first["lockbox_retention"] == pytest.approx(0.8)
    assert first["reused"] is False
    assert second["reused"] is True
    assert stricter["approved"] is False
    assert stricter["reused"] is True
    assert calls == 1


def test_final_lockbox_rejects_non_positive_return(tmp_path):
    data = pd.DataFrame({"Close": range(1000)})
    split = lockbox_split(1000, lockbox_fraction=0.2)

    report = evaluate_final_lockbox(
        data,
        split=split,
        development_metrics={"total_return": 10.0},
        evaluate_fn=lambda frame: {"total_return": -1.0},
        ledger=LockboxLedger(tmp_path / "lockbox.json"),
        ledger_key="negative",
    )

    assert report["approved"] is False
    assert "non_positive_final_lockbox_return" in report["reasons"]
    assert "final_lockbox_retention_below_threshold" in report["reasons"]
