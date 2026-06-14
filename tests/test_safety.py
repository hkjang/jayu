from datetime import UTC, date, datetime, timedelta

import pytest

from jayu.io import atomic_write_json
from jayu.provider_core import ProviderCategory, ProviderRegistry
from jayu.safety import (
    SafetyGateError,
    enforce_live_price_safety,
    enforce_research_universe,
    evaluate_shadow_promotion,
)
from jayu.settings import PromotionSettings, Settings


class PriceProvider:
    category = ProviderCategory.PRICE

    def __init__(self, name: str):
        self.name = name


def _live_settings() -> Settings:
    return Settings.model_validate(
        {
            "mode": "live",
            "data": {
                "cross_validation_providers": ["tiingo"],
                "minimum_valid_price_sources": 2,
                "price_disagreement_policy": "block",
                "require_verified_price_for_eligibility": True,
            },
        }
    )


def test_live_price_safety_requires_two_available_providers():
    registry = ProviderRegistry()
    registry.register(PriceProvider("yahoo"))

    with pytest.raises(SafetyGateError, match="LIVE_PRICE_SAFETY_FAILED"):
        enforce_live_price_safety(_live_settings(), registry)

    registry.register(PriceProvider("tiingo"))
    report = enforce_live_price_safety(_live_settings(), registry)

    assert report["eligible"] is True


def test_research_universe_requires_strict_point_in_time_universe():
    with pytest.raises(SafetyGateError, match="SURVIVORSHIP_GATE_FAILED"):
        enforce_research_universe(Settings())

    settings = Settings.model_validate(
        {
            "universe": {
                "policy": "strict",
                "as_of": "2025-12-31",
                "source": "point_in_time_fixture",
                "includes_delisted": True,
            }
        }
    )

    assert enforce_research_universe(settings)["valid"] is True


def test_shadow_promotion_requires_days_completion_health_and_clean_data(tmp_path):
    now = datetime(2026, 6, 30, 12, tzinfo=UTC)
    shadow_dir = tmp_path / "signals" / "shadow"
    health_path = tmp_path / "state" / "health.json"
    atomic_write_json(health_path, {"health_score": 95})
    for offset in range(20):
        signal_date = date(2026, 5, 1) + timedelta(days=offset)
        atomic_write_json(
            shadow_dir / f"{signal_date.isoformat()}.json",
            {
                "SOXL": {
                    "signal": "entry",
                    "signal_date": signal_date.isoformat(),
                    "action": "buy",
                    "eligible": True,
                    "shadow_status": "completed",
                    "future_return_1d": 0.01,
                    "future_return_5d": 0.02,
                    "future_return_20d": 0.03,
                    "risk": {
                        "violation_details": [],
                        "data_trust": {
                            "price": {
                                "verified": True,
                                "provider_disagreements": [],
                            }
                        },
                    },
                }
            },
        )

    report = evaluate_shadow_promotion(
        shadow_dir,
        health_path,
        PromotionSettings(),
        now=now,
    )

    assert report["eligible"] is True
    assert report["failure_code"] is None
    assert report["completed_signal_count"] == 20
    assert report["metrics"]["data_validation_success_rate"] == 1.0
    assert report["metrics"]["provider_disagreement_rate"] == 0.0
    assert report["metrics"]["risk_gate_pass_rate"] == 1.0
    assert report["metrics"]["max_signal_count_change_ratio"] == 0.0


def test_shadow_promotion_rejects_data_disagreement(tmp_path):
    now = datetime(2026, 6, 30, 12, tzinfo=UTC)
    shadow_dir = tmp_path / "signals" / "shadow"
    health_path = tmp_path / "state" / "health.json"
    atomic_write_json(health_path, {"health_score": 95})
    signal_date = date(2026, 5, 1)
    atomic_write_json(
        shadow_dir / f"{signal_date.isoformat()}.json",
        {
            "SOXL": {
                "signal": "entry",
                "signal_date": signal_date.isoformat(),
                "action": "buy",
                "eligible": False,
                "shadow_status": "completed",
                "risk": {
                    "violation_details": [{"code": "DATA_DISAGREEMENT", "message": "mismatch"}]
                },
            }
        },
    )

    report = evaluate_shadow_promotion(
        shadow_dir,
        health_path,
        PromotionSettings(
            min_shadow_days=1,
            min_completed_signals=1,
            min_mature_completion_ratio=1,
        ),
        now=now,
    )

    assert report["eligible"] is False
    assert report["failure_code"] == "SHADOW_PROMOTION_FAILED"
    criterion = next(
        item for item in report["criteria"] if item["name"] == "critical_data_failures"
    )
    assert criterion["passed"] is False


def test_shadow_promotion_blocks_unstable_signal_count_and_low_risk_pass_rate(tmp_path):
    now = datetime(2026, 6, 30, 12, tzinfo=UTC)
    shadow_dir = tmp_path / "signals" / "shadow"
    health_path = tmp_path / "state" / "health.json"
    atomic_write_json(health_path, {"health_score": 95})
    for offset, count in enumerate((1, 4)):
        signal_date = date(2026, 5, 1) + timedelta(days=offset)
        atomic_write_json(
            shadow_dir / f"{signal_date.isoformat()}.json",
            {
                f"T{index}": {
                    "signal": "entry",
                    "signal_date": signal_date.isoformat(),
                    "action": "buy",
                    "eligible": index == 0,
                    "shadow_status": "completed",
                    "risk": {
                        "violation_details": [],
                        "data_trust": {"price": {"verified": True}},
                    },
                }
                for index in range(count)
            },
        )

    report = evaluate_shadow_promotion(
        shadow_dir,
        health_path,
        PromotionSettings(
            min_shadow_days=2,
            min_completed_signals=1,
            min_mature_completion_ratio=1,
            min_risk_gate_pass_rate=0.8,
            max_signal_count_change_ratio=1,
        ),
        now=now,
    )

    assert report["eligible"] is False
    failed = {item["name"] for item in report["criteria"] if not item["passed"]}
    assert {"risk_gate_pass_rate", "signal_count_change_ratio"} <= failed
