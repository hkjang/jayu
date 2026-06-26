from __future__ import annotations

import pytest
from pathlib import Path
from datetime import datetime, UTC

from jayu.paths import RuntimePaths
from jayu.dashboard import (
    SCHEMA_VERSION,
    build_dashboard_overview,
    build_dashboard_decision,
    build_dashboard_data_quality,
    build_dashboard_risk,
    build_dashboard_signals,
    build_dashboard_trader_lens,
    build_autotrading_status_data,
    list_dashboard_runs,
)
from jayu.dashboard_contracts import (
    OverviewResponse,
    DecisionResponse,
    DataQualityResponse,
    RiskResponse,
    SignalsResponse,
    TraderLensResponse,
    AutotradingStatusResponse,
    RunsResponse,
)

# Re-use the existing test helpers from tests.test_dashboard
from tests.test_dashboard import _paths, _write_run


def test_dashboard_contracts_overview(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    raw_overview = build_dashboard_overview(
        paths,
        run_id="run-001",
        now=datetime(2026, 6, 14, 1, tzinfo=UTC),
    )
    
    # Contract validation
    validated = OverviewResponse.model_validate(raw_overview)
    assert validated.schema_version == SCHEMA_VERSION
    assert validated.run.run_id == "run-001"
    assert validated.run.mode == "shadow"
    assert validated.decision.overall == "data_error"


def test_dashboard_contracts_decision(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    raw_decision = build_dashboard_decision(
        paths,
        run_id="run-001",
        now=datetime(2026, 6, 14, 1, tzinfo=UTC),
    )
    
    # Contract validation
    validated = DecisionResponse.model_validate(raw_decision)
    assert validated.schema_version == SCHEMA_VERSION
    assert validated.run_id == "run-001"
    assert validated.overall == "data_error"
    assert "data_hash" in validated.context


def test_dashboard_contracts_data_quality(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    raw_dq = build_dashboard_data_quality(paths, run_id="run-001")
    
    # Contract validation
    validated = DataQualityResponse.model_validate(raw_dq)
    assert validated.schema_version == SCHEMA_VERSION
    assert validated.run_id == "run-001"
    assert validated.summary.status == "data_error"
    assert len(validated.mismatches) > 0


def test_dashboard_contracts_risk(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    raw_risk = build_dashboard_risk(paths, run_id="run-001")
    
    # Contract validation
    validated = RiskResponse.model_validate(raw_risk)
    assert validated.schema_version == SCHEMA_VERSION
    assert validated.run_id == "run-001"
    assert validated.summary.status == "blocked"
    assert validated.summary.blocked_count == 1


def test_dashboard_contracts_signals(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    raw_signals = build_dashboard_signals(paths, run_id="run-001")
    
    # Contract validation
    validated = SignalsResponse.model_validate(raw_signals)
    assert validated.schema_version == SCHEMA_VERSION
    assert validated.run_id == "run-001"


def test_dashboard_contracts_trader_lens(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    raw_tl = build_dashboard_trader_lens(paths, run_id="run-001")
    
    # Contract validation
    validated = TraderLensResponse.model_validate(raw_tl)
    assert validated.schema_version == SCHEMA_VERSION
    assert validated.run_id == "run-001"


def test_dashboard_contracts_autotrading_status(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    raw_status = build_autotrading_status_data(paths)
    
    # Contract validation
    validated = AutotradingStatusResponse.model_validate(raw_status)
    assert validated.status["phase"] == "disabled"
    assert validated.status["enabled"] is False


def test_dashboard_contracts_runs(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)
    
    raw_runs = {
        "schema_version": SCHEMA_VERSION,
        "runs": list_dashboard_runs(paths),
        "failure_patterns": None
    }
    
    # Contract validation
    validated = RunsResponse.model_validate(raw_runs)
    assert validated.schema_version == SCHEMA_VERSION
    assert len(validated.runs) > 0

