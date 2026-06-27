from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def evaluate_data_decision_gate(
    trust_report: Mapping[str, Any],
    *,
    min_score: float = 60.0,
    review_score: float = 80.0,
) -> dict[str, Any]:
    score = _number(trust_report.get("overall_score"))
    datasets = [item for item in trust_report.get("datasets", []) if isinstance(item, Mapping)]
    blocking = [
        {
            "dataset": item.get("name"),
            "score": item.get("score"),
            "decision": item.get("decision"),
            "reasons": item.get("reasons", []),
        }
        for item in datasets
        if item.get("decision") in {"block", "exclude"} or _number(item.get("score")) < min_score
    ]
    review = [
        {
            "dataset": item.get("name"),
            "score": item.get("score"),
            "decision": item.get("decision"),
            "reasons": item.get("reasons", []),
        }
        for item in datasets
        if not any(block.get("dataset") == item.get("name") for block in blocking)
        and _number(item.get("score")) < review_score
    ]
    if blocking:
        status = "blocked"
        allowed = False
        decision = "block"
    elif review or score < review_score:
        status = "warning"
        allowed = True
        decision = "review"
    else:
        status = "success"
        allowed = True
        decision = "pass"
    return {
        "status": status,
        "decision": decision,
        "allowed": allowed,
        "overall_score": score,
        "blocking": blocking,
        "review": review,
        "summary": {
            "blocking_count": len(blocking),
            "review_count": len(review),
            "dataset_count": len(datasets),
        },
        "source": "data_decision_gate.py - data_trust_score.py",
    }


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
