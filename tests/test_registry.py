from __future__ import annotations

import json
import sqlite3

from jayu.artifacts import RunContext
from jayu.paths import RuntimePaths
from jayu.registry import ExperimentRegistry
from jayu.settings import Settings


def test_registry_records_reproducibility_metadata(tmp_path):
    paths = RuntimePaths.from_root(tmp_path)
    settings = Settings(tickers=["SOXL"], random_seed=123)
    context = RunContext.create(paths, settings, "simulate")
    context.record_data(
        "SOXL",
        data_hash="abc123",
        quality_report={"source": "fixture", "start": "2025-01-01"},
    )
    registry = ExperimentRegistry(paths.state_dir / "experiments.sqlite")

    registry.start(context)
    registry.finish(context, status="success", result={"best_fitness": 1.5})

    row = registry.latest(1)[0]
    assert row["random_seed"] == 123
    assert row["config_hash"] == context.config_hash
    assert json.loads(row["environment_json"])["python"]
    with sqlite3.connect(registry.path) as connection:
        data_row = connection.execute(
            "SELECT data_hash, quality_json FROM run_data WHERE run_id = ?",
            (context.run_id,),
        ).fetchone()
    assert data_row[0] == "abc123"
    assert json.loads(data_row[1])["source"] == "fixture"
