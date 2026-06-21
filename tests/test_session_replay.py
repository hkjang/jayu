from __future__ import annotations

from datetime import UTC, datetime

from jayu.io import atomic_write_json
from jayu.session_replay import build_session_replay_report, write_session_replay_report


def _write_replay_run(tmp_path):
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
            "started_at": "2026-06-21T00:00:00+00:00",
            "finished_at": "2026-06-21T00:02:00+00:00",
            "config_hash": "config-hash",
            "data_hashes": {"SOXL": "data-hash"},
            "result": {"mode": "shadow", "safety_verdict": "blocked"},
        },
    )
    atomic_write_json(
        run_dir / "data_sources.json",
        {"sources": [{"provider": "yahoo", "ticker": "SOXL", "status": "success"}]},
    )
    atomic_write_json(
        run_dir / "provider_disagreement_report.json",
        {"disagreements": [{"ticker": "SOXL"}]},
    )
    atomic_write_json(
        run_dir / "signal_replay.json",
        {
            "signal_hash": "abc123456789",
            "seed": 42,
            "signal_date": "2026-06-21",
            "replay": False,
        },
    )
    atomic_write_json(
        run_dir / "signals_risk.json",
        {
            "SOXL": {
                "action": "buy",
                "eligible": False,
                "blocked": True,
                "status": "blocked",
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
        },
    )
    atomic_write_json(
        run_dir / "safety_verdict.json",
        {
            "overall": "blocked",
            "reasons": [{"component": "risk", "code": "SECTOR_EXPOSURE_EXCEEDED"}],
        },
    )
    atomic_write_json(run_dir / "signal_publication.json", {"status": "blocked"})
    atomic_write_json(state_dir / "order_plan.json", {"orders": [{"ticker": "SOXL"}]})
    atomic_write_json(state_dir / "allocation_preview.json", {"status": "warning"})
    return run_dir, state_dir


def test_session_replay_builds_artifact_backed_events(tmp_path):
    run_dir, state_dir = _write_replay_run(tmp_path)

    report = build_session_replay_report(
        run_dir,
        project_root=tmp_path,
        state_dir=state_dir,
        now=datetime(2026, 6, 21, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert report["summary"]["duration_seconds"] == 120
    assert report["summary"]["step_count"] == 9
    assert report["summary"]["artifact_count"] >= 7
    assert [event["id"] for event in report["events"]][:3] == [
        "run_manifest",
        "data_collection",
        "signal_replay_hash",
    ]
    risk_event = next(event for event in report["events"] if event["id"] == "risk_review")
    assert risk_event["status"] == "blocked"
    assert risk_event["failure_code"] == "SECTOR_EXPOSURE_EXCEEDED"
    assert any(item["path"].endswith("signals_risk.json") for item in report["artifacts"])


def test_session_replay_write_report(tmp_path):
    run_dir, state_dir = _write_replay_run(tmp_path)
    output = tmp_path / "session_replay.json"

    report = write_session_replay_report(
        run_dir,
        output,
        project_root=tmp_path,
        state_dir=state_dir,
    )

    assert output.exists()
    assert report["summary"]["run_id"] == "run-001"
