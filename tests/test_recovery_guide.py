from __future__ import annotations

from datetime import UTC, datetime

from jayu.recovery_guide import build_recovery_guide, write_recovery_guide


def test_recovery_guide_maps_survivorship_bias_to_steps(tmp_path):
    guide = build_recovery_guide(
        [
            {
                "component": "survivorship",
                "code": "SURVIVORSHIP_BIAS_RISK",
                "message": "manual_current_universe is not point-in-time membership",
            }
        ],
        now=datetime(2026, 6, 21, tzinfo=UTC),
    )

    assert guide["status"] == "warning"
    assert guide["summary"]["top_code"] == "SURVIVORSHIP_BIAS_RISK"
    assert guide["items"][0]["title"] == "시점별 universe 확인 필요"
    assert "manifest.json survivorship_audit" in guide["items"][0]["artifacts"]
    assert "uv run jayu validate-config --mode research" in guide["items"][0]["commands"]


def test_recovery_guide_dedupes_manifest_and_verdict_failure_codes(tmp_path):
    output = tmp_path / "recovery_guide.json"
    guide = write_recovery_guide(
        output,
        manifest={"status": "failed", "failure_code": "SECTOR_EXPOSURE_EXCEEDED"},
        verdict={
            "overall": "blocked",
            "reasons": [
                {
                    "component": "risk",
                    "code": "SECTOR_EXPOSURE_EXCEEDED",
                    "message": "sector exposure exceeded",
                }
            ],
        },
        now=datetime(2026, 6, 21, tzinfo=UTC),
    )

    assert output.exists()
    assert guide["status"] == "blocked"
    assert guide["summary"]["issue_count"] == 1
    assert guide["summary"]["blocked_count"] == 1
    assert guide["items"][0]["code"] == "SECTOR_EXPOSURE_EXCEEDED"
    assert "allocation_preview.json" in guide["items"][0]["artifacts"]
