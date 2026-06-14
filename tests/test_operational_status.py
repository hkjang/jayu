from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jayu.failure_codes import FailureCode
from jayu.io import atomic_write_json
from jayu.operational_status import (
    OPERATIONAL_EXECUTION_MODES,
    build_operational_status,
    latest_run_dir,
    write_operational_status,
    write_operational_status_bundle,
    write_operational_status_markdown,
)
from jayu.paths import RuntimePaths
from jayu.settings import Settings


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "mode": "shadow",
            "data": {
                "cross_validation_providers": ["tiingo"],
                "cross_validation_mode": "strict",
                "minimum_valid_price_sources": 2,
                "price_disagreement_policy": "block",
                "require_verified_price_for_eligibility": True,
            },
            "promotion": {
                "min_shadow_days": 1,
                "min_completed_signals": 1,
                "min_mature_completion_ratio": 1.0,
                "maturity_horizon_days": 1,
                "min_data_validation_success_rate": 1.0,
                "max_provider_disagreement_rate": 0.0,
                "min_risk_gate_pass_rate": 1.0,
            },
        }
    )


def _paths(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths.from_root(tmp_path)
    paths.ensure_runtime_dirs()
    return paths


def _write_good_promotion_inputs(paths: RuntimePaths) -> None:
    atomic_write_json(paths.state_dir / "health.json", {"health_score": 95})
    atomic_write_json(
        paths.signals_dir / "shadow" / "2000-01-01.json",
        {
            "SOXL": {
                "signal": "entry",
                "signal_date": "2000-01-01",
                "action": "buy",
                "eligible": True,
                "shadow_status": "completed",
                "risk": {
                    "violation_details": [],
                    "data_trust": {"price": {"verified": True, "provider_disagreements": []}},
                },
            }
        },
    )


def _write_run(
    paths: RuntimePaths,
    *,
    run_id: str = "latest",
    verdict: str = "approved",
    status: str = "success",
    mode: str = "shadow",
    finished_at: str = "2026-06-13T00:00:00+00:00",
) -> None:
    run_dir = paths.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": run_id,
            "status": status,
            "execution_mode": mode,
            "config_hash": "config",
            "finished_at": finished_at,
            "result": {
                "mode": mode,
                "signal_hash": "signal",
                "data_hash": "data",
                "risk_status": "passed",
                "cost_survival": "approved",
            },
        },
    )
    atomic_write_json(run_dir / "safety_verdict.json", {"overall": verdict, "data_hash": "data"})


def test_operational_status_marks_live_ready_when_all_gates_pass(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_good_promotion_inputs(paths)
    _write_run(paths, verdict="approved")

    report = build_operational_status(
        paths,
        _settings(),
        now=datetime(2026, 6, 14, tzinfo=UTC),
    )

    assert report["paper_ready"] is True
    assert report["live_ready"] is True
    assert report["readiness_summary"]["overall"] == "ready"
    assert report["readiness_summary"]["reason_codes"] == []
    assert report["latest_run"]["safety_verdict"] == "approved"
    assert report["promotion"]["eligible"] is True
    assert report["readiness_reasons"] == []


def test_latest_operational_run_ignores_newer_research_and_running_runs(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(
        paths,
        run_id="shadow",
        mode="shadow",
        finished_at="2026-06-13T00:00:00+00:00",
    )
    _write_run(
        paths,
        run_id="research",
        mode="research",
        finished_at="2026-06-14T00:00:00+00:00",
    )
    _write_run(
        paths,
        run_id="running-live",
        mode="live",
        status="running",
        finished_at="2026-06-15T00:00:00+00:00",
    )

    latest = latest_run_dir(
        paths.runs_dir,
        execution_modes=OPERATIONAL_EXECUTION_MODES,
    )

    assert latest == paths.runs_dir / "shadow"


def test_operational_status_blocks_unapproved_latest_safety_verdict(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_good_promotion_inputs(paths)
    _write_run(paths, verdict="blocked")

    report = build_operational_status(
        paths,
        _settings(),
        now=datetime(2026, 6, 14, tzinfo=UTC),
    )

    assert report["live_ready"] is False
    assert report["checks"]["latest_safety_verdict"] == "blocked"
    assert report["readiness_summary"]["overall"] == "blocked"
    assert report["readiness_summary"]["reason_codes"] == [FailureCode.SAFETY_VERDICT_BLOCKED.value]
    assert report["readiness_summary"]["next_actions"]
    assert {reason["code"] for reason in report["readiness_reasons"]} == {
        FailureCode.SAFETY_VERDICT_BLOCKED.value
    }


def test_operational_status_blocks_stale_latest_run(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_good_promotion_inputs(paths)
    _write_run(paths, verdict="approved")

    report = build_operational_status(
        paths,
        _settings(),
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert report["live_ready"] is False
    assert report["checks"]["latest_run_fresh"] is False
    assert report["latest_run"]["run_age_hours"] == 72.0
    assert {reason["code"] for reason in report["readiness_reasons"]} == {
        FailureCode.OPERATIONAL_RUN_STALE.value
    }


def test_operational_status_writes_state_snapshot(tmp_path: Path):
    paths = _paths(tmp_path)
    report = write_operational_status(
        paths,
        _settings(),
        now=datetime(2026, 6, 14, tzinfo=UTC),
    )

    assert (paths.state_dir / "operational_status.json").exists()
    assert report["live_ready"] is False
    assert {reason["code"] for reason in report["readiness_reasons"]} >= {
        FailureCode.NO_RUN_HISTORY.value,
        FailureCode.SHADOW_PROMOTION_FAILED.value,
        FailureCode.HEALTH_SCORE_LOW.value,
    }


def test_operational_status_markdown_summarizes_readiness(tmp_path: Path):
    paths = _paths(tmp_path)
    report = build_operational_status(
        paths,
        _settings(),
        now=datetime(2026, 6, 14, tzinfo=UTC),
    )

    output = write_operational_status_markdown(paths, _settings(), report=report)

    content = output.read_text(encoding="utf-8")
    assert "# Jayu Operational Status" in content
    assert "Status: `blocked`" in content
    assert "`NO_RUN_HISTORY`" in content
    assert "Next Actions" in content


def test_operational_status_bundle_writes_matching_json_and_markdown(tmp_path: Path):
    paths = _paths(tmp_path)
    report = write_operational_status_bundle(
        paths,
        _settings(),
        now=datetime(2026, 6, 14, tzinfo=UTC),
    )

    json_content = (paths.state_dir / "operational_status.json").read_text(encoding="utf-8")
    markdown_content = (paths.state_dir / "operational_status.md").read_text(encoding="utf-8")

    assert report["generated_at"] in json_content
    assert report["generated_at"] in markdown_content
