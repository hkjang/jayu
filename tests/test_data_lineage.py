from __future__ import annotations

from datetime import UTC, datetime

from jayu.data_lineage import build_data_lineage_report, write_data_lineage_report
from jayu.io import atomic_write_json


def _write_lineage_run(tmp_path):
    run_dir = tmp_path / "runs" / "run-001"
    run_dir.mkdir(parents=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": "run-001",
            "command": "signal",
            "execution_mode": "shadow",
            "status": "success",
            "failure_code": "DATA_DISAGREEMENT",
            "result": {"mode": "shadow", "safety_verdict": "blocked"},
        },
    )
    atomic_write_json(
        run_dir / "data_sources.json",
        {
            "sources": [
                {"provider": "yahoo", "ticker": "SOXL", "status": "success", "rows": 3},
                {"provider": "tiingo", "ticker": "SOXL", "status": "failed", "rows": 0},
            ]
        },
    )
    atomic_write_json(
        run_dir / "provider_disagreement_report.json",
        {"disagreements": [{"ticker": "SOXL", "field": "Close"}]},
    )
    atomic_write_json(run_dir / "signal_replay.json", {"signal_hash": "abc123"})
    atomic_write_json(
        run_dir / "signals_risk.json",
        {"SOXL": {"action": "buy", "eligible": False, "blocked": True}},
    )
    atomic_write_json(
        run_dir / "risk_explanation.json",
        {"approved_count": 0, "blocked_count": 1, "hold_count": 0},
    )
    atomic_write_json(
        run_dir / "safety_verdict.json",
        {"overall": "blocked", "reasons": [{"code": "DATA_DISAGREEMENT"}]},
    )
    atomic_write_json(run_dir / "signal_publication.json", {"status": "blocked"})
    atomic_write_json(run_dir / "promotion.json", {"eligible": False})
    atomic_write_json(state_dir / "order_plan.json", {"orders": [{"ticker": "SOXL"}]})
    atomic_write_json(state_dir / "allocation_preview.json", {"status": "warning"})
    atomic_write_json(state_dir / "stock_warning_gate.json", {"SOXL": {"has_warning": True}})
    return run_dir, state_dir


def test_data_lineage_builds_provider_artifact_and_gate_edges(tmp_path):
    run_dir, state_dir = _write_lineage_run(tmp_path)

    report = build_data_lineage_report(
        run_dir,
        project_root=tmp_path,
        state_dir=state_dir,
        now=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert report["summary"]["provider_count"] == 2
    assert report["summary"]["failed_provider_count"] == 1
    assert report["summary"]["blocked_gate_count"] >= 2
    node_ids = {node["id"] for node in report["nodes"]}
    assert {"provider:yahoo", "provider:tiingo", "process:risk_gate"} <= node_ids
    assert any(
        edge["from"] == "artifact:risk_explanation"
        and edge["to"] == "process:safety_verdict"
        for edge in report["edges"]
    )
    assert any(edge["to"] == "artifact:data_sources" for edge in report["edges"])


def test_data_lineage_write_report(tmp_path):
    run_dir, state_dir = _write_lineage_run(tmp_path)
    output = tmp_path / "data_lineage.json"

    report = write_data_lineage_report(
        run_dir,
        output,
        project_root=tmp_path,
        state_dir=state_dir,
    )

    assert output.exists()
    assert report["summary"]["run_id"] == "run-001"
