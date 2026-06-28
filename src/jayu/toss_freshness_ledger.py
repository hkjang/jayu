from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .api_response_contracts import validate_api_response_contract
from .unified_quality_policy import evaluate_unified_quality_policy


@dataclass(frozen=True)
class TossFreshnessSpec:
    endpoint: str
    label: str
    source_file: str
    section: str | None = None
    contract_endpoint: str | None = None
    max_age_hours: float = 24.0
    critical: bool = True


DEFAULT_SPECS = [
    TossFreshnessSpec("accounts", "Toss accounts", "toss_account_snapshot.json", "accounts", "accounts", 24, True),
    TossFreshnessSpec("holdings", "Toss holdings", "toss_account_snapshot.json", "holdings", "holdings", 6, True),
    TossFreshnessSpec("orders", "Toss order history", "toss_orders.json", None, "orders", 24, True),
    TossFreshnessSpec("stocks", "Toss stock metadata", "toss_security_master_cache.json", None, None, 168, False),
    TossFreshnessSpec("warnings", "Toss stock warnings", "toss_warning_history.json", None, None, 24, False),
    TossFreshnessSpec("prices", "Toss prices in account snapshot", "toss_account_snapshot.json", "holdings", "holdings", 2, True),
    TossFreshnessSpec("exchange_rate", "Toss USD/KRW exchange rate", "toss_fx_cache.json", None, "exchange_rate", 24, True),
    TossFreshnessSpec("commissions", "Toss commissions", "toss_account_snapshot.json", "commissions", "commissions", 168, False),
    TossFreshnessSpec("api_drift", "Toss OpenAPI drift check", "toss_api_drift.json", None, None, 168, True),
]


def build_toss_freshness_ledger(
    project_root: Path,
    *,
    now: datetime | None = None,
    write: bool = True,
) -> dict[str, Any]:
    now = _as_utc(now or datetime.now(UTC))
    state_dir = project_root / "state"
    endpoints = [_evaluate_spec(state_dir, spec, now=now) for spec in DEFAULT_SPECS]
    policy = evaluate_unified_quality_policy(
        {
            row["endpoint"]: {
                "domain": "toss_freshness",
                "trust_score": row["trust_score"],
                "decision": row["decision"],
                "status": row["status"],
                "reasons": row["reasons"],
                "cache_status": row["cache_status"],
                "fallback_used": row["fallback_used"],
                "source": row["source"],
            }
            for row in endpoints
        },
        default_domain="toss_freshness",
    )
    result = {
        "status": policy["status"],
        "decision": policy["decision"],
        "allowed": policy["allowed"],
        "generated_at": now.isoformat(),
        "summary": {
            "endpoint_count": len(endpoints),
            "pass_count": sum(row["decision"] == "pass" for row in endpoints),
            "review_count": sum(row["decision"] == "review" for row in endpoints),
            "block_count": sum(row["decision"] == "block" for row in endpoints),
            "exclude_count": sum(row["decision"] == "exclude" for row in endpoints),
            "stale_count": sum(row["cache_status"] in {"stale", "stale_hit"} for row in endpoints),
            "missing_count": sum(row["cache_status"] == "miss" for row in endpoints),
            "fallback_count": sum(row["fallback_used"] for row in endpoints),
            "critical_block_count": sum(row["critical"] and row["decision"] in {"block", "exclude"} for row in endpoints),
            "average_trust_score": policy["overall_score"],
        },
        "endpoints": endpoints,
        "policy": policy,
        "source": "toss_freshness_ledger.py - state/toss_account_snapshot.json, state/toss_orders.json, state/toss_fx_cache.json",
    }
    if write:
        _write_ledger(state_dir, result)
    return result


def _evaluate_spec(state_dir: Path, spec: TossFreshnessSpec, *, now: datetime) -> dict[str, Any]:
    path = state_dir / spec.source_file
    payload = _read_json(path)
    section_payload = _section_payload(payload, spec.section)
    file_time = _file_time(path)
    payload_time = _payload_time(payload)
    last_success = payload_time or file_time
    if spec.endpoint == "exchange_rate":
        fx_payload = _fx_payload(payload)
        if fx_payload:
            section_payload = fx_payload
            ts = _timestamp_time(payload.get("timestamp")) if isinstance(payload, Mapping) else None
            last_success = ts or last_success
    if spec.endpoint == "api_drift" and isinstance(payload, Mapping):
        last_success = _parse_datetime(payload.get("last_checked_at")) or last_success

    age_hours = round((now - last_success).total_seconds() / 3600.0, 2) if last_success else None
    reasons: list[str] = []
    contract = None
    fallback_used = False

    if not path.exists():
        cache_status = "miss"
        score = 45.0 if spec.critical else 70.0
        reasons.append("source_file_missing")
    elif payload is None:
        cache_status = "error"
        score = 35.0 if spec.critical else 55.0
        reasons.append("source_file_unreadable")
    elif spec.section and section_payload is None:
        cache_status = "error" if _snapshot_has_error(payload, spec.section) else "miss"
        score = 35.0 if spec.critical else 55.0
        reasons.append(f"{spec.section}_section_missing")
    else:
        cache_status = _cache_status(age_hours, spec.max_age_hours)
        score = _score_from_age(age_hours, spec.max_age_hours)

    if isinstance(payload, Mapping) and _snapshot_has_error(payload, spec.section or spec.endpoint):
        reasons.append(f"{spec.endpoint}_snapshot_error")
        score = min(score, 35.0 if spec.critical else 55.0)
        cache_status = "error"

    if spec.contract_endpoint and section_payload is not None:
        contract = validate_api_response_contract(
            spec.contract_endpoint,
            section_payload,
            provider="toss",
            source=str(path),
        )
        violations = int(contract.get("summary", {}).get("violation_count") or 0)
        if violations > 0:
            reasons.append("api_contract_violation")
            score = min(score, 45.0)
        elif contract.get("status") == "not_evaluated" and spec.critical:
            reasons.append("contract_not_evaluated")
            score = min(score, 70.0)

    if spec.endpoint == "exchange_rate" and path.name == "toss_fx_cache.json" and section_payload is None:
        snapshot = _read_json(state_dir / "toss_account_snapshot.json")
        snapshot_fx = _section_payload(snapshot, "exchange_rate")
        if snapshot_fx is not None:
            section_payload = snapshot_fx
            fallback_used = True
            fallback_time = _payload_time(snapshot) or _file_time(state_dir / "toss_account_snapshot.json")
            last_success = fallback_time or last_success
            age_hours = round((now - fallback_time).total_seconds() / 3600.0, 2) if fallback_time else age_hours
            cache_status = _cache_status(age_hours, spec.max_age_hours)
            score = min(_score_from_age(age_hours, spec.max_age_hours), 70.0)
            reasons.append("used_account_snapshot_exchange_rate_fallback")

    decision = _decision(score, spec.critical, cache_status)
    status = "success" if decision == "pass" else "warning" if decision == "review" else "blocked"
    return {
        "endpoint": spec.endpoint,
        "label": spec.label,
        "status": status,
        "decision": decision,
        "critical": spec.critical,
        "trust_score": round(score, 2),
        "cache_status": cache_status,
        "fallback_used": fallback_used,
        "last_success_at": last_success.isoformat() if last_success else None,
        "age_hours": age_hours,
        "max_age_hours": spec.max_age_hours,
        "row_count": _row_count(section_payload if section_payload is not None else payload),
        "contract": contract,
        "reasons": sorted(set(reasons)),
        "source": str(path),
    }


def _cache_status(age_hours: float | None, max_age_hours: float) -> str:
    if age_hours is None:
        return "miss"
    if age_hours <= max_age_hours:
        return "hit"
    return "stale_hit" if age_hours <= max_age_hours * 3 else "stale"


def _score_from_age(age_hours: float | None, max_age_hours: float) -> float:
    if age_hours is None:
        return 50.0
    if age_hours <= max_age_hours:
        return 95.0
    if age_hours <= max_age_hours * 3:
        return 68.0
    return 45.0


def _decision(score: float, critical: bool, cache_status: str) -> str:
    if cache_status == "miss" and not critical:
        return "review"
    if critical and score < 50:
        return "block"
    if score >= 80:
        return "pass"
    if score >= 60:
        return "review"
    return "block" if critical else "review"


def _section_payload(payload: Any, section: str | None) -> Any:
    if section is None:
        return payload
    if not isinstance(payload, Mapping):
        return None
    return payload.get(section)


def _snapshot_has_error(payload: Any, section: str) -> bool:
    if not isinstance(payload, Mapping):
        return False
    errors = payload.get("errors")
    return isinstance(errors, Mapping) and bool(errors.get(section))


def _fx_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    rate = payload.get("usd_krw") or payload.get("rate") or payload.get("exchangeRate")
    if rate is None:
        return None
    return {"base_currency": "USD", "quote_currency": "KRW", "rate": rate}


def _payload_time(payload: Any) -> datetime | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("generated_at", "updated_at", "created_at", "fetched_at_iso", "last_success_at"):
        parsed = _parse_datetime(payload.get(key))
        if parsed is not None:
            return parsed
    ts = _timestamp_time(payload.get("fetched_at") or payload.get("timestamp"))
    return ts


def _timestamp_time(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), UTC)
    except (TypeError, ValueError, OSError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _as_utc(parsed)


def _file_time(path: Path) -> datetime | None:
    if not path.exists():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _row_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, Mapping):
        for key in ("items", "data", "result", "accounts", "holdings", "prices", "commissions"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, Mapping):
                nested = _row_count(value)
                if nested:
                    return nested
        return 1
    return 0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _write_ledger(state_dir: Path, result: dict[str, Any]) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "toss_freshness_ledger.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
