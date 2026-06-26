from __future__ import annotations

from datetime import UTC, datetime

from jayu.io import atomic_write_json
from jayu.run_evidence import build_run_evidence_report, write_run_evidence_report


def _write_evidence_run(tmp_path, *, include_safety: bool = True):
    run_dir = tmp_path / "runs" / "run-001"
    run_dir.mkdir(parents=True)
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": "run-001",
            "command": "signal",
            "execution_mode": "shadow",
            "status": "success",
            "result": {"mode": "shadow"},
        },
    )
    atomic_write_json(run_dir / "data_sources.json", {"sources": []})
    atomic_write_json(run_dir / "provider_disagreement_report.json", {"disagreements": []})
    atomic_write_json(run_dir / "signals_risk.json", {"SOXL": {"action": "buy"}})
    atomic_write_json(run_dir / "risk_explanation.json", {"approved_count": 1})
    if include_safety:
        atomic_write_json(run_dir / "safety_verdict.json", {"overall": "approved"})
    return run_dir


def test_run_evidence_scores_required_artifacts(tmp_path):
    run_dir = _write_evidence_run(tmp_path)

    report = build_run_evidence_report(
        run_dir,
        now=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert report["status"] == "warning"
    assert report["summary"]["run_id"] == "run-001"
    assert report["summary"]["missing_required_count"] == 0
    assert report["summary"]["completeness_rate"] == 1.0
    assert report["summary"]["missing_warning_count"] >= 1
    signals = next(item for item in report["items"] if item["id"] == "signals")
    assert signals["exists"] is True
    assert signals["path"] == "signals_risk.json"


def test_run_evidence_blocks_when_required_artifact_missing(tmp_path):
    run_dir = _write_evidence_run(tmp_path, include_safety=False)

    report = build_run_evidence_report(run_dir)

    assert report["status"] == "blocked"
    assert report["summary"]["missing_required_count"] == 1
    missing = [item["id"] for item in report["items"] if item["exists"] is not True]
    assert "safety_verdict" in missing


def test_run_evidence_write_report(tmp_path):
    run_dir = _write_evidence_run(tmp_path)
    output = tmp_path / "run_evidence.json"

    report = write_run_evidence_report(run_dir, output)

    assert output.exists()
    assert report["summary"]["required_count"] >= 1
