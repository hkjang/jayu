import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import pytest

from jayu.dashboard import (
    build_dashboard_data_quality,
    build_dashboard_overview,
    build_dashboard_promotion,
    build_dashboard_risk,
    build_dashboard_settings_validation,
    build_dashboard_signals,
    create_dashboard_server,
    dashboard_static_dir,
    list_dashboard_runs,
)
from jayu.io import atomic_write_json, read_json
from jayu.paths import RuntimePaths


def _paths(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths.from_root(tmp_path)
    paths.ensure_runtime_dirs()
    return paths


def _write_run(paths: RuntimePaths) -> Path:
    run_dir = paths.runs_dir / "run-001"
    run_dir.mkdir()
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": "run-001",
            "command": "signal",
            "execution_mode": "shadow",
            "status": "success",
            "started_at": "2026-06-14T00:00:00+00:00",
            "finished_at": "2026-06-14T00:05:00+00:00",
            "config_hash": "config-hash",
            "data_hashes": {"SOXL": "price-hash"},
            "survivorship_audit": {
                "policy": "strict",
                "valid": True,
                "includes_delisted": True,
                "universe_source": "point_in_time",
            },
            "data_reports": {
                "SOXL": {
                    "ticker": "SOXL",
                    "valid": True,
                    "price_verified": False,
                    "price_usable": False,
                }
            },
            "result": {
                "mode": "shadow",
                "data_hash": "data-hash",
                "signal_hash": "signal-hash",
            },
        },
    )
    atomic_write_json(
        run_dir / "data_sources.json",
        {
            "sources": [
                {
                    "provider": "yahoo",
                    "ticker": "SOXL",
                    "status": "success",
                    "rows": 3,
                },
                {
                    "provider": "tiingo",
                    "ticker": "SOXL",
                    "status": "success",
                    "rows": 2,
                },
            ]
        },
    )
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
                            "value_mismatches": [
                                {
                                    "date": "2026-06-13",
                                    "field": "Close",
                                    "relative_delta": 0.02,
                                    "threshold": 0.005,
                                    "values": {"yahoo": 100.0, "tiingo": 98.0},
                                }
                            ],
                            "date_mismatches": [
                                {
                                    "date": "2026-06-12",
                                    "present_in": ["yahoo"],
                                    "missing_in": ["tiingo"],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    atomic_write_json(
        run_dir / "signals_risk.json",
        {
            "SOXL": {
                "signal": "entry",
                "action": "buy",
                "eligible": False,
                "blocked": True,
                "status": "blocked",
                "price": 100.0,
                "stop_price": 92.0,
                "target_price": 118.0,
                "approved_position_pct": 0.0,
                "reason_codes": ["SECTOR_EXPOSURE_EXCEEDED"],
                "risk": {
                    "reason_codes": ["SECTOR_EXPOSURE_EXCEEDED"],
                    "data_trust": {"price": {"verified": False}},
                    "violation_details": [
                        {
                            "code": "SECTOR_EXPOSURE_EXCEEDED",
                            "metric": "sector_exposure",
                            "observed": 0.62,
                            "limit": 0.4,
                        }
                    ],
                },
            }
        },
    )
    atomic_write_json(
        run_dir / "risk_explanation.json",
        {
            "approved_count": 0,
            "blocked_count": 1,
            "hold_count": 0,
            "top_block_reasons": [{"code": "SECTOR_EXPOSURE_EXCEEDED", "count": 1}],
            "signals": [
                {
                    "ticker": "SOXL",
                    "action": "buy",
                    "reviewed": True,
                    "eligible": False,
                    "approved_position_pct": 0.0,
                    "passed": [{"metric": "cash_pct", "observed": 0.3, "limit": 0.2}],
                    "failed": [
                        {
                            "code": "SECTOR_EXPOSURE_EXCEEDED",
                            "metric": "sector_exposure",
                            "observed": 0.62,
                            "limit": 0.4,
                            "excess": 0.22,
                        }
                    ],
                }
            ],
        },
    )
    atomic_write_json(
        run_dir / "safety_verdict.json",
        {
            "overall": "blocked",
            "reasons": [
                {
                    "component": "data",
                    "code": "DATA_DISAGREEMENT",
                    "message": "provider disagreement exceeded tolerance",
                },
                {
                    "component": "risk",
                    "code": "SECTOR_EXPOSURE_EXCEEDED",
                    "message": "sector exposure exceeded",
                },
            ],
        },
    )
    atomic_write_json(
        run_dir / "promotion.json",
        {
            "eligible": False,
            "shadow_days": ["2026-06-13", "2026-06-14"],
            "criteria": [],
            "metrics": {},
        },
    )
    atomic_write_json(paths.state_dir / "health.json", {"health_score": 72})
    return run_dir


def test_dashboard_overview_prioritizes_data_error_and_actions(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    report = build_dashboard_overview(
        paths,
        run_id="run-001",
        now=datetime(2026, 6, 14, 1, tzinfo=UTC),
    )

    assert report["run"]["mode"] == "shadow"
    assert report["decision"]["overall"] == "data_error"
    assert report["gates"]["data"]["disagreement_count"] == 1
    assert report["gates"]["risk"]["blocked_count"] == 1
    assert report["signals"]["blocked"] == 1
    assert report["decision"]["top_reasons"][0]["code"] == "DATA_DISAGREEMENT"
    assert report["recommended_actions"][0]["page"] == "data-quality"


def test_dashboard_survivorship_action_exposes_validation_command(tmp_path: Path):
    paths = _paths(tmp_path)
    run_dir = _write_run(paths)
    manifest = {
        **read_json(run_dir / "manifest.json"),
        "status": "failed",
        "failure_code": "SURVIVORSHIP_GATE_FAILED",
        "data_reports": {},
    }
    atomic_write_json(run_dir / "manifest.json", manifest)
    (run_dir / "safety_verdict.json").unlink()
    atomic_write_json(run_dir / "provider_disagreement_report.json", {"disagreements": []})
    (run_dir / "risk_explanation.json").unlink()
    (run_dir / "signals_risk.json").unlink()
    (run_dir / "promotion.json").unlink()

    report = build_dashboard_overview(paths, run_id="run-001")

    action = next(
        item for item in report["recommended_actions"] if item["id"] == "review-survivorship"
    )
    assert action["page"] is None
    assert action["command"] == "uv run jayu validate-config --mode research"


def test_dashboard_data_quality_flattens_provider_values_and_dates(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    report = build_dashboard_data_quality(paths, run_id="run-001")

    assert report["summary"]["status"] == "data_error"
    assert report["summary"]["provider_count"] == 2
    assert report["summary"]["blocked_tickers"] == ["SOXL"]
    assert {row["kind"] for row in report["mismatches"]} == {"value", "date"}
    value = next(row for row in report["mismatches"] if row["kind"] == "value")
    assert value["values"] == {"yahoo": 100.0, "tiingo": 98.0}


def test_dashboard_risk_keeps_current_limit_and_excess(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    report = build_dashboard_risk(paths, run_id="run-001")

    assert report["summary"]["status"] == "blocked"
    assert report["summary"]["blocked_count"] == 1
    failed = next(row for row in report["checks"] if row["status"] == "blocked")
    assert failed["observed"] == 0.62
    assert failed["limit"] == 0.4
    assert failed["excess"] == 0.22


def test_dashboard_signals_exposes_publication_prices_and_reasons(tmp_path: Path):
    paths = _paths(tmp_path)
    run_dir = _write_run(paths)
    atomic_write_json(
        run_dir / "signal_publication.json",
        {
            "status": "blocked",
            "run_id": "run-001",
            "signal_date": "2026-06-14",
            "failure_code": "SAFETY_VERDICT_BLOCKED",
        },
    )

    report = build_dashboard_signals(paths, run_id="run-001")

    assert report["summary"]["blocked_count"] == 1
    assert report["publication"]["status"] == "blocked"
    row = report["rows"][0]
    assert row["ticker"] == "SOXL"
    assert row["entry_price"] == 100.0
    assert row["stop_price"] == 92.0
    assert row["target_price"] == 118.0
    assert row["failed"][0]["code"] == "SECTOR_EXPOSURE_EXCEEDED"


def test_dashboard_promotion_reports_criteria_and_shadow_history(tmp_path: Path):
    paths = _paths(tmp_path)
    atomic_write_json(paths.state_dir / "health.json", {"health_score": 90})
    shadow_dir = paths.signals_dir / "shadow"
    shadow_dir.mkdir(parents=True)
    atomic_write_json(
        shadow_dir / "2026-06-14.json",
        {
            "SOXL": {
                "signal": "entry",
                "signal_date": "2026-06-14",
                "action": "buy",
                "eligible": True,
                "shadow_status": "pending",
                "risk": {
                    "violation_details": [],
                    "data_trust": {"price": {"verified": True, "provider_disagreements": []}},
                },
            }
        },
    )

    report = build_dashboard_promotion(paths)

    assert report["summary"]["status"] == "blocked"
    assert report["summary"]["shadow_day_count"] == 1
    assert report["history"][0]["date"] == "2026-06-14"
    assert report["history"][0]["data_verified_count"] == 1
    assert {item["name"] for item in report["criteria"]} >= {"shadow_days", "health_score"}


def test_dashboard_settings_validation_blocks_loose_operational_mode(tmp_path: Path):
    paths = _paths(tmp_path)

    report = build_dashboard_settings_validation(paths, mode="shadow")

    assert report["summary"]["status"] == "blocked"
    assert any(item["key"] == "settings.mode_validation" for item in report["rules"])
    assert any(item["status"] == "blocked" for item in report["rules"])
    assert report["settings"]["tiingo_api_key"] is None


def test_dashboard_lists_runs_and_rejects_path_traversal(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    assert list_dashboard_runs(paths)[0]["run_id"] == "run-001"
    with pytest.raises(ValueError, match="unknown run_id"):
        build_dashboard_overview(paths, run_id="../state")


def test_dashboard_static_assets_are_bundled_without_order_actions():
    static_dir = dashboard_static_dir()
    assert (static_dir / "index.html").exists()
    assert (static_dir / "styles.css").exists()
    assert (static_dir / "app.js").exists()
    content = (static_dir / "app.js").read_text(encoding="utf-8")
    assert "주문 실행" not in content
    assert "매수 실행" not in content


def test_dashboard_http_server_serves_static_page_and_api(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)
    server = create_dashboard_server(paths, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:  # noqa: S310
            html = response.read().decode("utf-8")
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/overview?run_id=run-001",
            timeout=5,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/runs/run-001/signals",
            timeout=5,
        ) as response:
            signals = json.loads(response.read().decode("utf-8"))
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/promotion",
            timeout=5,
        ) as response:
            promotion = json.loads(response.read().decode("utf-8"))
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/settings/validation?mode=shadow",
            timeout=5,
        ) as response:
            validation = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert "<title>Jayu Operations</title>" in html
    assert payload["run"]["run_id"] == "run-001"
    assert payload["decision"]["overall"] == "data_error"
    assert signals["summary"]["blocked_count"] == 1
    assert promotion["summary"]["status"] == "blocked"
    assert validation["mode"] == "shadow"
