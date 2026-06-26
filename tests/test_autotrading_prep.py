from pathlib import Path

from jayu.autotrading_prep import build_autotrading_status_payload
from jayu.io import atomic_write_json
from jayu.paths import RuntimePaths


def _paths(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths.from_root(tmp_path)
    paths.ensure_runtime_dirs()
    return paths


def _write_success_run(paths: RuntimePaths) -> Path:
    run_dir = paths.runs_dir / "run-success"
    run_dir.mkdir()
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": "run-success",
            "status": "success",
            "execution_mode": "paper",
            "finished_at": "2026-06-21T09:00:00+09:00",
            "data_reports": {
                "SOXL": {"valid": True},
                "TQQQ": {"valid": True},
                "portfolio_snapshot": {"valid": True},
            },
        },
    )
    atomic_write_json(
        run_dir / "risk_explanation.json",
        {
            "approved_count": 4,
            "blocked_count": 0,
            "hold_count": 1,
            "signals": [],
        },
    )
    return run_dir


def _write_operational_status(paths: RuntimePaths) -> None:
    atomic_write_json(
        paths.state_dir / "operational_status.json",
        {
            "promotion": {
                "shadow_days": [f"2026-06-{day:02d}" for day in range(1, 21)],
                "criteria": [
                    {
                        "name": "shadow_days",
                        "passed": True,
                        "observed": 20,
                        "required": 20,
                    }
                ],
            }
        },
    )


def _write_paper_report(
    paths: RuntimePaths,
    *,
    tripped: bool = False,
    orders_submitted: int = 20,
    orders_filled: int = 20,
    orders_blocked: int = 0,
) -> None:
    atomic_write_json(
        paths.state_dir / "paper_trading.json",
        {
            "starting_equity": 1_000_000.0,
            "ending_equity": 1_012_000.0,
            "realized_pnl": 12_000.0,
            "orders_submitted": orders_submitted,
            "orders_filled": orders_filled,
            "orders_blocked": orders_blocked,
            "execution_quality": {
                "avg_fill_rate": orders_filled / orders_submitted if orders_submitted else 0,
                "avg_implementation_shortfall_bps": 18.0,
            },
            "kill_switch": {
                "tripped": tripped,
                "reasons": ["daily_loss_limit"] if tripped else [],
            },
        },
    )


def test_autotrading_readiness_score_promotes_only_as_review_candidate(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_success_run(paths)
    _write_operational_status(paths)
    _write_paper_report(paths)

    payload = build_autotrading_status_payload(paths)
    score = payload["readiness_score"]

    assert payload["status"]["enabled"] is False
    assert score["score"] == 100
    assert score["stage"] == "auto_candidate"
    assert score["thresholds"]["semi_auto_review"] == 80
    assert payload["paper_promotion_report"]["eligible_for_semi_auto"] is True
    assert payload["paper_promotion_report"]["eligible_for_auto_candidate"] is True
    assert payload["paper_promotion_report"]["status"] == "success"
    assert {item["id"] for item in score["components"]} == {
        "data_validation",
        "risk_gate",
        "shadow_period",
        "paper_performance",
        "implementation_shortfall",
        "kill_switch",
    }


def test_autotrading_readiness_kill_switch_blocks_stage(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_success_run(paths)
    _write_operational_status(paths)
    _write_paper_report(paths, tripped=True)

    payload = build_autotrading_status_payload(paths)
    score = payload["readiness_score"]

    assert score["stage"] == "blocked"
    kill_switch = next(item for item in score["components"] if item["id"] == "kill_switch")
    assert kill_switch["status"] == "blocked"
    assert kill_switch["score"] == 0
    report = payload["paper_promotion_report"]
    assert report["status"] == "blocked"
    assert report["eligible_for_auto_candidate"] is False
    paper_kill_switch = next(item for item in report["criteria"] if item["id"] == "paper_kill_switch")
    assert paper_kill_switch["status"] == "blocked"


def test_autotrading_readiness_without_artifacts_is_not_evaluated(tmp_path: Path):
    paths = _paths(tmp_path)

    payload = build_autotrading_status_payload(paths)
    score = payload["readiness_score"]
    report = payload["paper_promotion_report"]

    assert score["score"] == 0
    assert score["stage"] == "analysis_only"
    assert score["next_actions"]
    assert report["status"] == "not_evaluated"
    assert report["eligible_for_semi_auto"] is False
    assert report["criteria"][0]["id"] == "paper_report"


def test_paper_promotion_report_requires_enough_order_samples(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_success_run(paths)
    _write_operational_status(paths)
    _write_paper_report(paths, orders_submitted=4, orders_filled=4)

    report = build_autotrading_status_payload(paths)["paper_promotion_report"]

    assert report["status"] == "warning"
    assert report["eligible_for_semi_auto"] is False
    order_sample = next(item for item in report["criteria"] if item["id"] == "paper_orders")
    assert order_sample["status"] == "warning"
    assert order_sample["passed"] is False
