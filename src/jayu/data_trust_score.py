from __future__ import annotations

from collections.abc import Mapping
from typing import Any


WEIGHTS = {
    "schema_validity": 0.25,
    "completeness": 0.25,
    "provider_agreement": 0.20,
    "reconciliation": 0.20,
    "freshness": 0.10,
}


def build_data_trust_report(datasets: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    for name, payload in datasets.items():
        rows.append(score_dataset(name, payload))
    overall = round(sum(row["score"] for row in rows) / len(rows), 2) if rows else 0.0
    decision = _decision(overall, any(row["decision"] in {"block", "exclude"} for row in rows))
    return {
        "status": "success" if decision == "pass" else "warning" if decision == "review" else "blocked",
        "overall_score": overall,
        "decision": decision,
        "datasets": rows,
        "summary": {
            "dataset_count": len(rows),
            "pass_count": sum(1 for row in rows if row["decision"] == "pass"),
            "review_count": sum(1 for row in rows if row["decision"] == "review"),
            "block_count": sum(1 for row in rows if row["decision"] == "block"),
            "exclude_count": sum(1 for row in rows if row["decision"] == "exclude"),
        },
        "source": "data_trust_score.py - data quality, API contracts, Toss integrity, reconciliation",
    }


def score_dataset(name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    components = {
        "schema_validity": _schema_score(payload),
        "completeness": _completeness_score(payload),
        "provider_agreement": _provider_agreement_score(payload),
        "reconciliation": _reconciliation_score(payload),
        "freshness": _freshness_score(payload),
    }
    score = round(sum(components[key] * weight for key, weight in WEIGHTS.items()), 2)
    hard_block = bool(payload.get("hard_block"))
    decision = _decision(score, hard_block)
    return {
        "name": name,
        "score": score,
        "decision": decision,
        "status": "success" if decision == "pass" else "warning" if decision == "review" else "blocked",
        "components": {key: round(value, 2) for key, value in components.items()},
        "reasons": _reasons(payload, components, score, hard_block),
        "source": payload.get("source") or name,
    }


def _schema_score(payload: Mapping[str, Any]) -> float:
    contract = _mapping(payload.get("contract"))
    if not contract:
        return 80.0
    violations = _summary_number(contract, "violation_count")
    rows = _summary_number(contract, "row_count")
    if violations <= 0:
        return 100.0
    return max(0.0, 100.0 - violations * 20.0 - (10.0 if rows <= 0 else 0.0))


def _completeness_score(payload: Mapping[str, Any]) -> float:
    integrity = _mapping(payload.get("integrity") or payload.get("quality") or payload.get("data_quality"))
    if not integrity:
        return 80.0
    if "integrity_score" in integrity:
        return float(integrity.get("integrity_score") or 0.0)
    if "quality_score" in integrity:
        return float(integrity.get("quality_score") or 0.0)
    summary = _mapping(integrity.get("summary"))
    total = _number(summary.get("total") or summary.get("order_count") or summary.get("total_source_count"))
    failed = _number(summary.get("failed_issue_count") or summary.get("failed_source_count"))
    warnings = _number(summary.get("warning_issue_count") or summary.get("disagreement_count"))
    if total <= 0 and failed <= 0 and warnings <= 0:
        return 75.0
    return max(0.0, 100.0 - failed * 15.0 - warnings * 5.0)


def _provider_agreement_score(payload: Mapping[str, Any]) -> float:
    disagreements = payload.get("disagreements")
    if isinstance(disagreements, list):
        return max(0.0, 100.0 - len(disagreements) * 25.0)
    data_quality = _mapping(payload.get("data_quality"))
    summary = _mapping(data_quality.get("summary"))
    disagreement_count = _number(summary.get("disagreement_count"))
    return max(0.0, 100.0 - disagreement_count * 25.0)


def _reconciliation_score(payload: Mapping[str, Any]) -> float:
    reconciliation = _mapping(payload.get("reconciliation"))
    if not reconciliation:
        return 80.0
    summary = _mapping(reconciliation.get("summary"))
    failed = _number(summary.get("failed_discrepancy_count"))
    discrepancies = _number(summary.get("position_discrepancy_count"))
    if reconciliation.get("status") == "success":
        return 100.0
    return max(0.0, 100.0 - failed * 35.0 - discrepancies * 12.0)


def _freshness_score(payload: Mapping[str, Any]) -> float:
    if payload.get("stale_cache") is True:
        return 45.0
    if payload.get("fallback_snapshot_used") is True:
        return 60.0
    return 100.0


def _decision(score: float, hard_block: bool = False) -> str:
    if hard_block:
        return "block"
    if score >= 80:
        return "pass"
    if score >= 60:
        return "review"
    if score >= 40:
        return "block"
    return "exclude"


def _reasons(
    payload: Mapping[str, Any],
    components: Mapping[str, float],
    score: float,
    hard_block: bool,
) -> list[str]:
    reasons = []
    if hard_block:
        reasons.append("hard_block_requested")
    for name, value in components.items():
        if value < 60:
            reasons.append(f"{name}_low")
        elif value < 80:
            reasons.append(f"{name}_review")
    if score < 80:
        reasons.append("trust_score_below_pass_threshold")
    return reasons


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _summary_number(payload: Mapping[str, Any], key: str) -> float:
    return _number(_mapping(payload.get("summary")).get(key))


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
