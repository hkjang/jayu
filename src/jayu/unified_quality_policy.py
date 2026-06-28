from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


PASS_SCORE = 80.0
REVIEW_SCORE = 60.0
BLOCK_SCORE = 40.0

DECISION_RANK = {"pass": 0, "review": 1, "block": 2, "exclude": 3}
DECISION_SCORE = {"pass": 95.0, "review": 70.0, "block": 45.0, "exclude": 20.0}


def evaluate_unified_quality_policy(
    items: Mapping[str, Any] | Iterable[Any],
    *,
    default_domain: str = "general",
) -> dict[str, Any]:
    """Normalize quality reports from different domains into one decision policy."""
    rows = _quality_rows(items, default_domain=default_domain)
    total_weight = sum(row["weight"] for row in rows if row["weight"] > 0)
    overall_score = (
        round(sum(row["score"] * row["weight"] for row in rows) / total_weight, 2)
        if total_weight > 0
        else 0.0
    )
    blocking = [row for row in rows if row["decision"] in {"block", "exclude"}]
    review = [row for row in rows if row["decision"] == "review"]
    decision = _rollup_decision(rows, overall_score)
    status = _status_from_decision(decision)
    return {
        "status": status,
        "decision": decision,
        "allowed": decision not in {"block", "exclude"},
        "overall_score": overall_score,
        "items": rows,
        "blocking": blocking,
        "review": review,
        "summary": {
            "item_count": len(rows),
            "pass_count": sum(row["decision"] == "pass" for row in rows),
            "review_count": len(review),
            "block_count": sum(row["decision"] == "block" for row in rows),
            "exclude_count": sum(row["decision"] == "exclude" for row in rows),
            "blocking_count": len(blocking),
            "domain_count": len({row["domain"] for row in rows}),
        },
        "thresholds": {
            "pass": PASS_SCORE,
            "review": REVIEW_SCORE,
            "block": BLOCK_SCORE,
        },
        "source": "unified_quality_policy.py - data_trust_score, data_decision_gate, dividend_data_quality_gate, api_response_contracts",
    }


def normalize_quality_item(
    name: str,
    payload: Any,
    *,
    domain: str = "general",
    weight: float = 1.0,
) -> dict[str, Any]:
    data = dict(payload) if isinstance(payload, Mapping) else {}
    raw_decision = _normalize_decision(data.get("decision"))
    raw_status = _normalize_status(data.get("status"))
    hard_block = bool(data.get("hard_block")) or data.get("allowed") is False
    score = _extract_score(data)

    decision = raw_decision or _decision_from_status(raw_status)
    if score is None:
        score = DECISION_SCORE.get(decision or "", 75.0)
    if decision is None:
        decision = _decision_from_score(score)
    if hard_block and decision == "pass":
        decision = "block"
        score = min(score, 45.0)

    reasons = _reasons(data, raw_status=raw_status, hard_block=hard_block, decision=decision, score=score)
    return {
        "name": name,
        "domain": str(data.get("domain") or domain),
        "decision": decision,
        "status": _status_from_decision(decision),
        "allowed": decision not in {"block", "exclude"},
        "score": round(float(score), 2),
        "weight": max(0.0, _number(data.get("weight"), default=weight)),
        "reasons": reasons,
        "source": str(data.get("source") or name),
        "raw_status": raw_status or str(data.get("status") or ""),
        "cache_status": data.get("cache_status"),
        "fallback_used": bool(data.get("fallback_used") or data.get("fallback_snapshot_used")),
        "last_success_at": data.get("last_success_at") or data.get("updated_at") or data.get("generated_at"),
    }


def _quality_rows(items: Mapping[str, Any] | Iterable[Any], *, default_domain: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(items, Mapping):
        iterable = items.items()
        for name, payload in iterable:
            domain = default_domain
            if isinstance(payload, Mapping):
                domain = str(payload.get("domain") or default_domain)
            rows.append(normalize_quality_item(str(name), payload, domain=domain))
        return rows

    for index, item in enumerate(items):
        if isinstance(item, Mapping):
            name = str(item.get("name") or item.get("endpoint") or item.get("id") or f"item_{index + 1}")
            domain = str(item.get("domain") or default_domain)
            rows.append(normalize_quality_item(name, item, domain=domain))
        else:
            rows.append(normalize_quality_item(f"item_{index + 1}", {}, domain=default_domain))
    return rows


def _extract_score(data: Mapping[str, Any]) -> float | None:
    for key in ("trust_score", "score", "overall_score", "integrity_score", "quality_score"):
        value = data.get(key)
        if value is not None:
            return _number(value, default=0.0)
    summary = data.get("summary")
    if isinstance(summary, Mapping):
        for key in ("trust_score", "score", "overall_score", "integrity_score", "quality_score"):
            value = summary.get(key)
            if value is not None:
                return _number(value, default=0.0)
    return None


def _rollup_decision(rows: list[dict[str, Any]], overall_score: float) -> str:
    if not rows:
        return "review"
    worst = max(rows, key=lambda row: DECISION_RANK.get(str(row.get("decision")), 1))
    worst_decision = str(worst.get("decision"))
    if worst_decision in {"block", "exclude"}:
        return worst_decision
    if overall_score < BLOCK_SCORE:
        return "exclude"
    if overall_score < REVIEW_SCORE:
        return "block"
    if worst_decision == "review" or overall_score < PASS_SCORE:
        return "review"
    return "pass"


def _decision_from_score(score: float) -> str:
    if score >= PASS_SCORE:
        return "pass"
    if score >= REVIEW_SCORE:
        return "review"
    if score >= BLOCK_SCORE:
        return "block"
    return "exclude"


def _decision_from_status(status: str | None) -> str | None:
    if not status:
        return None
    if status in {"success", "pass", "healthy", "ok"}:
        return "pass"
    if status in {"warning", "review", "partial", "stale"}:
        return "review"
    if status in {"failed", "blocked", "data_error", "error"}:
        return "block"
    if status in {"excluded", "exclude", "critical"}:
        return "exclude"
    if status == "not_evaluated":
        return "review"
    return None


def _normalize_decision(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text if text in DECISION_RANK else None


def _normalize_status(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _status_from_decision(decision: str) -> str:
    if decision == "pass":
        return "success"
    if decision == "review":
        return "warning"
    return "blocked"


def _reasons(
    data: Mapping[str, Any],
    *,
    raw_status: str | None,
    hard_block: bool,
    decision: str,
    score: float,
) -> list[str]:
    reasons: list[str] = []
    raw_reasons = data.get("reasons")
    if isinstance(raw_reasons, list):
        reasons.extend(_reason_text(item) for item in raw_reasons if _reason_text(item))
    block_reason = data.get("block_reason") or data.get("failure_code")
    if block_reason:
        reasons.append(str(block_reason))
    if hard_block:
        reasons.append("hard_block_or_allowed_false")
    if raw_status in {"failed", "blocked", "data_error", "error"}:
        reasons.append(f"status_{raw_status}")
    summary = data.get("summary")
    if isinstance(summary, Mapping):
        for key in ("violation_count", "failed_issue_count", "blocked_count", "missing_count", "disagreement_count"):
            if _number(summary.get(key), default=0.0) > 0:
                reasons.append(key)
    if data.get("fallback_used") or data.get("fallback_snapshot_used"):
        reasons.append("fallback_used")
    if data.get("cache_status") in {"stale", "stale_hit", "miss", "error"}:
        reasons.append(f"cache_{data.get('cache_status')}")
    if decision != "pass":
        reasons.append(f"score_below_{PASS_SCORE:g}")
    if score < REVIEW_SCORE:
        reasons.append(f"score_below_{REVIEW_SCORE:g}")
    return sorted(set(reasons))


def _reason_text(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("code") or item.get("reason") or item.get("message") or "").strip()
    return str(item).strip()


def _number(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
