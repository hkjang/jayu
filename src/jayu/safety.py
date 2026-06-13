"""Operational safety gates for research and live signal execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .failure_codes import FailureCode
from .io import atomic_write_json, read_json
from .provider_core import ProviderCategory, ProviderRegistry
from .settings import PromotionSettings, Settings
from .survivorship import audit_survivorship


class SafetyGateError(RuntimeError):
    def __init__(self, code: FailureCode, reasons: list[str]):
        self.code = code
        self.reasons = reasons
        super().__init__(f"{code.value}: {'; '.join(reasons)}")


@dataclass(frozen=True)
class SafetyCriterion:
    name: str
    passed: bool
    observed: Any
    required: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def enforce_live_price_safety(settings: Settings, registry: ProviderRegistry) -> dict[str, Any]:
    requested = {
        settings.data_provider,
        *settings.data.cross_validation_providers,
    }
    available = set(registry.inventory()[ProviderCategory.PRICE.value])
    criteria = [
        SafetyCriterion(
            "minimum_valid_price_sources",
            settings.data.minimum_valid_price_sources >= 2,
            settings.data.minimum_valid_price_sources,
            2,
        ),
        SafetyCriterion(
            "distinct_configured_price_sources",
            len(requested) >= 2,
            sorted(requested),
            "at least 2",
        ),
        SafetyCriterion(
            "available_live_price_sources",
            len(requested & available) >= settings.data.minimum_valid_price_sources,
            sorted(requested & available),
            settings.data.minimum_valid_price_sources,
        ),
        SafetyCriterion(
            "price_disagreement_policy",
            settings.data.price_disagreement_policy == "block",
            settings.data.price_disagreement_policy,
            "block",
        ),
        SafetyCriterion(
            "verified_price_required",
            settings.data.require_verified_price_for_eligibility,
            settings.data.require_verified_price_for_eligibility,
            True,
        ),
    ]
    report = {
        "eligible": all(item.passed for item in criteria),
        "requested_sources": sorted(requested),
        "available_sources": sorted(available),
        "criteria": [item.to_dict() for item in criteria],
    }
    report["failure_code"] = (
        None if report["eligible"] else FailureCode.LIVE_PRICE_SAFETY_FAILED.value
    )
    if not report["eligible"]:
        reasons = [item.name for item in criteria if not item.passed]
        raise SafetyGateError(FailureCode.LIVE_PRICE_SAFETY_FAILED, reasons)
    return report


def enforce_research_universe(settings: Settings) -> dict[str, Any]:
    reasons = []
    if settings.universe.policy != "strict":
        reasons.append("research requires universe.policy=strict")
    if reasons:
        raise SafetyGateError(FailureCode.SURVIVORSHIP_GATE_FAILED, reasons)
    try:
        return audit_survivorship(settings).to_dict()
    except ValueError as exc:
        raise SafetyGateError(
            FailureCode.SURVIVORSHIP_GATE_FAILED,
            [str(exc)],
        ) from exc


def evaluate_shadow_promotion(
    shadow_dir: Path,
    health_path: Path,
    settings: PromotionSettings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = now or datetime.now(UTC)
    shadow_dates: set[date] = set()
    buy_signals: list[dict[str, Any]] = []
    critical_failures: list[dict[str, str]] = []
    critical_codes = {
        FailureCode.DATA_CONTRACT_FAILED.value,
        FailureCode.DATA_DISAGREEMENT.value,
        FailureCode.UNVERIFIED_PRICE_DATA.value,
    }
    for path in sorted(shadow_dir.glob("*.json")):
        try:
            shadow_dates.add(date.fromisoformat(path.stem))
        except ValueError:
            continue
        payload = read_json(path, default={})
        if not isinstance(payload, Mapping):
            continue
        for ticker, raw_signal in payload.items():
            if not isinstance(raw_signal, Mapping):
                continue
            risk = raw_signal.get("risk")
            details = risk.get("violation_details", []) if isinstance(risk, Mapping) else []
            for detail in details if isinstance(details, list) else []:
                if isinstance(detail, Mapping) and detail.get("code") in critical_codes:
                    critical_failures.append({"ticker": str(ticker), "code": str(detail["code"])})
            if raw_signal.get("action") == "buy":
                buy_signals.append(dict(raw_signal))

    mature_signals = []
    for signal in buy_signals:
        raw_date = signal.get("signal_date")
        try:
            signal_date = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        if reference.date() - signal_date >= timedelta(days=settings.maturity_horizon_days):
            mature_signals.append(signal)
    completed_signals = [
        signal for signal in mature_signals if signal.get("shadow_status") == "completed"
    ]
    completion_ratio = len(completed_signals) / len(mature_signals) if mature_signals else 0.0
    health = read_json(health_path, default={})
    health_score = health.get("health_score") if isinstance(health, Mapping) else None
    criteria = [
        SafetyCriterion(
            "shadow_days",
            len(shadow_dates) >= settings.min_shadow_days,
            len(shadow_dates),
            settings.min_shadow_days,
        ),
        SafetyCriterion(
            "completed_shadow_signals",
            len(completed_signals) >= settings.min_completed_signals,
            len(completed_signals),
            settings.min_completed_signals,
        ),
        SafetyCriterion(
            "mature_completion_ratio",
            completion_ratio >= settings.min_mature_completion_ratio,
            round(completion_ratio, 4),
            settings.min_mature_completion_ratio,
        ),
        SafetyCriterion(
            "health_score",
            isinstance(health_score, (int, float)) and health_score >= settings.min_health_score,
            health_score,
            settings.min_health_score,
        ),
        SafetyCriterion(
            "critical_data_failures",
            not critical_failures,
            len(critical_failures),
            0,
        ),
    ]
    report = {
        "generated_at": reference.isoformat(),
        "eligible": all(item.passed for item in criteria),
        "shadow_days": sorted(item.isoformat() for item in shadow_dates),
        "buy_signal_count": len(buy_signals),
        "mature_signal_count": len(mature_signals),
        "completed_signal_count": len(completed_signals),
        "critical_failures": critical_failures,
        "criteria": [item.to_dict() for item in criteria],
    }
    report["failure_code"] = (
        None if report["eligible"] else FailureCode.SHADOW_PROMOTION_FAILED.value
    )
    return report


def write_promotion_report(
    path: Path,
    shadow_dir: Path,
    health_path: Path,
    settings: PromotionSettings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = evaluate_shadow_promotion(
        shadow_dir,
        health_path,
        settings,
        now=now,
    )
    atomic_write_json(path, report)
    return report


def enforce_shadow_promotion(
    path: Path,
    shadow_dir: Path,
    health_path: Path,
    settings: PromotionSettings,
) -> dict[str, Any]:
    report = write_promotion_report(path, shadow_dir, health_path, settings)
    if settings.enabled and not report["eligible"]:
        reasons = [
            str(item["name"])
            for item in report["criteria"]
            if isinstance(item, Mapping) and item.get("passed") is not True
        ]
        raise SafetyGateError(FailureCode.SHADOW_PROMOTION_FAILED, reasons)
    return report
