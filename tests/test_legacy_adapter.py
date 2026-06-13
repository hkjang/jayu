from __future__ import annotations

import json

import numpy as np

from jayu.legacy_adapter import (
    load_json,
    migrate_gene_pool,
    migrate_history,
    migrate_json_structure,
    numpy_to_python,
    save_json,
)


def test_migrate_json_structure_non_dict_returns_empty():
    assert migrate_json_structure(None) == {}
    assert migrate_json_structure([1, 2]) == {}


def test_migrate_json_structure_keeps_regimes_and_fills_params():
    data = {"SOXL": {"bull": {"params": {"rsi_lo": 25}}}}
    migrated = migrate_json_structure(data)
    # bull retained with filled params; missing regimes get defaults.
    assert migrated["SOXL"]["bull"]["params"]["rsi_lo"] == 25
    assert "strategy_mode" in migrated["SOXL"]["bull"]["params"]
    assert migrated["SOXL"]["bear"]["params"]["strategy_mode"] == "ensemble"


def test_migrate_json_structure_expands_flat_entry_to_all_regimes():
    data = {"TQQQ": {"params": {"rsi_lo": 30}}}
    migrated = migrate_json_structure(data)
    assert set(migrated["TQQQ"]) == {"bull", "bear", "sideways"}
    for regime in ("bull", "bear", "sideways"):
        assert migrated["TQQQ"][regime]["params"]["rsi_lo"] == 30


def test_migrate_gene_pool_flat_list_replicates_across_regimes():
    data = {"SOXL": [{"params": {"rsi_lo": 30}}]}
    migrated = migrate_gene_pool(data)
    assert set(migrated["SOXL"]) == {"bull", "bear", "sideways"}
    assert migrated["SOXL"]["bull"][0]["params"]["rsi_lo"] == 30
    assert len(migrated["SOXL"]["bear"]) == 1


def test_migrate_gene_pool_regime_dict_fills_params():
    data = {"SOXL": {"bull": [{"params": {"rsi_lo": 35}}], "bear": [], "sideways": []}}
    migrated = migrate_gene_pool(data)
    assert migrated["SOXL"]["bull"][0]["params"]["rsi_lo"] == 35
    assert migrated["SOXL"]["bear"] == []


def test_migrate_history_replicates_list_and_keeps_regimes():
    listed = migrate_history({"SOXL": [{"date": "2026-06-01"}]})
    assert listed["SOXL"]["bull"] == [{"date": "2026-06-01"}]

    regimed = migrate_history({"TQQQ": {"bull": [1], "bear": [], "sideways": []}})
    assert regimed["TQQQ"]["bull"] == [1]

    empty = migrate_history({"IONQ": {"other": 1}})
    assert empty["IONQ"] == {"bull": [], "bear": [], "sideways": []}


def test_numpy_to_python_converts_nested_numpy_scalars():
    obj = {
        "flag": np.bool_(True),
        "count": np.int64(5),
        "ratio": np.float64(1.5),
        "nested": [np.int32(2), {"x": np.float32(0.5)}],
    }
    out = numpy_to_python(obj)
    assert out["flag"] is True and isinstance(out["flag"], bool)
    assert out["count"] == 5 and isinstance(out["count"], int)
    assert out["ratio"] == 1.5 and isinstance(out["ratio"], float)
    assert out["nested"][0] == 2 and isinstance(out["nested"][0], int)
    assert isinstance(out["nested"][1]["x"], float)


def test_save_and_load_json_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    save_json({"value": np.int64(7), "items": [np.float64(1.0)]}, path)
    loaded = load_json(path)
    assert loaded == {"value": 7, "items": [1.0]}


def test_load_json_missing_returns_default(tmp_path):
    path = str(tmp_path / "absent.json")
    assert load_json(path) == {}
    assert load_json(path, default={"d": 1}) == {"d": 1}


def test_load_json_corrupt_backs_up_and_returns_default(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json", encoding="utf-8")

    result = load_json(str(path), default={"fallback": True})

    assert result == {"fallback": True}
    assert (tmp_path / "broken.json.corrupt").exists()
    # The original corrupt file is preserved as-is in the backup.
    assert (tmp_path / "broken.json.corrupt").read_text(encoding="utf-8") == "{not valid json"


def test_save_json_writes_valid_json_file(tmp_path):
    path = str(tmp_path / "out.json")
    save_json({"a": 1}, path)
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle) == {"a": 1}
