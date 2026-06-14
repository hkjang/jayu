from __future__ import annotations

from pathlib import Path

from jayu.failure_codes import FailureCode
from jayu.io import atomic_write_json
from jayu.safety_verdict import build_safety_verdict, write_safety_verdict


def _manifest(*, mode: str = "live") -> dict:
    return {
        "run_id": f"{mode}-run",
        "execution_mode": mode,
        "status": "success",
        "config_hash": "config-hash",
        "data_hashes": {"SOXL": "data-hash"},
        "result": {"mode": mode},
        "data_reports": {
            "SOXL": {
                "ticker": "SOXL",
                "valid": True,
                "price_usable": True,
                "price_verified": True,
            }
        },
        "provider_disagreements": [],
        "survivorship_audit": {
            "policy": "strict",
            "valid": True,
            "includes_delisted": True,
        },
    }


def _write_pass_artifacts(run_dir: Path) -> None:
    atomic_write_json(
        run_dir / "promotion.json",
        {"eligible": True, "criteria": [], "metrics": {"min_days": 10}},
    )
    atomic_write_json(
        run_dir / "risk_explanation.json",
        {
            "approved_count": 2,
            "blocked_count": 0,
            "hold_count": 1,
            "top_block_reasons": [],
        },
    )
    atomic_write_json(run_dir / "provider_disagreement_report.json", {"disagreements": []})


def test_safety_verdict_approves_fully_valid_live_run(tmp_path: Path):
    run_dir = tmp_path / "run"
    manifest = _manifest(mode="live")
    atomic_write_json(run_dir / "manifest.json", manifest)
    _write_pass_artifacts(run_dir)

    verdict = write_safety_verdict(run_dir)

    assert verdict["overall"] == "approved"
    assert verdict["components"]["data"]["status"] == "pass"
    assert verdict["components"]["promotion"]["status"] == "pass"
    assert verdict["components"]["risk"]["status"] == "pass"
    assert (run_dir / "safety_verdict.json").exists()


def test_safety_verdict_blocks_provider_disagreement_from_artifact(tmp_path: Path):
    run_dir = tmp_path / "run"
    manifest = _manifest(mode="live")
    manifest.pop("provider_disagreements")
    atomic_write_json(run_dir / "manifest.json", manifest)
    _write_pass_artifacts(run_dir)
    atomic_write_json(
        run_dir / "provider_disagreement_report.json",
        {
            "disagreements": [
                {
                    "ticker": "SOXL",
                    "disagreements": [
                        {
                            "baseline": "yahoo",
                            "candidate": "tiingo",
                            "reasons": [{"cause": "close_delta"}],
                        }
                    ],
                }
            ]
        },
    )

    verdict = build_safety_verdict(run_dir)

    assert verdict["overall"] == "blocked"
    assert verdict["components"]["data"]["status"] == "fail"
    assert verdict["components"]["data"]["provider_disagreement_count"] == 1
    assert {reason["code"] for reason in verdict["reasons"]} == {
        FailureCode.DATA_DISAGREEMENT.value
    }


def test_safety_verdict_reviews_shadow_run_with_unmet_promotion(tmp_path: Path):
    run_dir = tmp_path / "run"
    atomic_write_json(run_dir / "manifest.json", _manifest(mode="shadow"))
    atomic_write_json(
        run_dir / "promotion.json",
        {
            "eligible": False,
            "criteria": [{"name": "min_days", "passed": False}],
            "metrics": {"days": 2},
        },
    )
    atomic_write_json(
        run_dir / "risk_explanation.json",
        {"approved_count": 1, "blocked_count": 0, "hold_count": 0},
    )
    atomic_write_json(run_dir / "provider_disagreement_report.json", {"disagreements": []})

    verdict = build_safety_verdict(run_dir)

    assert verdict["overall"] == "review"
    assert verdict["components"]["promotion"]["required"] is False
    assert verdict["components"]["promotion"]["status"] == "warn"
    assert verdict["components"]["promotion"]["failed_criteria"] == ["min_days"]


def test_safety_verdict_blocks_failed_manifest_even_without_artifacts(tmp_path: Path):
    run_dir = tmp_path / "run"
    manifest = _manifest(mode="signal")
    manifest.update(
        {
            "status": "failed",
            "failure_code": FailureCode.DATA_FAILURE.value,
            "result": None,
        }
    )
    atomic_write_json(run_dir / "manifest.json", manifest)

    verdict = build_safety_verdict(run_dir)

    assert verdict["overall"] == "blocked"
    assert verdict["components"]["data"]["status"] == "fail"
