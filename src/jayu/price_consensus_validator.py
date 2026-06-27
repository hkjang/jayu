from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


PRICE_FIELDS = ("open", "high", "low", "close", "price")
VOLUME_FIELDS = ("volume",)


def validate_price_consensus(
    provider_payloads: Mapping[str, Any],
    *,
    max_relative_price_delta: float = 0.005,
    max_relative_volume_delta: float = 0.05,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for provider, payload in provider_payloads.items():
        for row in _rows(payload):
            symbol = _text(row, "symbol", "ticker", "stockCode").upper()
            date = _text(row, "date", "time", "timestamp", "asOf")
            if symbol:
                grouped[(symbol, date or "latest")][provider] = row

    disagreements = []
    for (symbol, date), providers in grouped.items():
        names = list(providers)
        if len(names) < 2:
            continue
        baseline_name = names[0]
        baseline = providers[baseline_name]
        for candidate_name in names[1:]:
            candidate = providers[candidate_name]
            disagreements.extend(
                _compare_rows(
                    symbol,
                    date,
                    baseline_name,
                    baseline,
                    candidate_name,
                    candidate,
                    max_relative_price_delta=max_relative_price_delta,
                    max_relative_volume_delta=max_relative_volume_delta,
                )
            )
    blocked = sorted({item["symbol"] for item in disagreements})
    return {
        "status": "failed" if blocked else "success",
        "summary": {
            "group_count": len(grouped),
            "disagreement_count": len(disagreements),
            "blocked_symbol_count": len(blocked),
            "blocked_symbols": blocked,
        },
        "disagreements": disagreements[:200],
        "source": "price_consensus_validator.py - provider price/volume agreement",
    }


def _compare_rows(
    symbol: str,
    date: str,
    baseline_name: str,
    baseline: Mapping[str, Any],
    candidate_name: str,
    candidate: Mapping[str, Any],
    *,
    max_relative_price_delta: float,
    max_relative_volume_delta: float,
) -> list[dict[str, Any]]:
    issues = []
    for field in PRICE_FIELDS:
        left = _number(baseline.get(field) or baseline.get(field.capitalize()))
        right = _number(candidate.get(field) or candidate.get(field.capitalize()))
        if left is None or right is None:
            continue
        relative = abs(left - right) / max(abs(left), 1e-12)
        if relative > max_relative_price_delta:
            issues.append(_issue(symbol, date, field, baseline_name, left, candidate_name, right, relative, max_relative_price_delta))
    for field in VOLUME_FIELDS:
        left = _number(baseline.get(field) or baseline.get(field.capitalize()))
        right = _number(candidate.get(field) or candidate.get(field.capitalize()))
        if left is None or right is None:
            continue
        relative = abs(left - right) / max(abs(left), 1.0)
        if relative > max_relative_volume_delta:
            issues.append(_issue(symbol, date, field, baseline_name, left, candidate_name, right, relative, max_relative_volume_delta))
    return issues


def _issue(
    symbol: str,
    date: str,
    field: str,
    left_provider: str,
    left_value: float,
    right_provider: str,
    right_value: float,
    relative_delta: float,
    threshold: float,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "date": date,
        "field": field,
        "providers": [left_provider, right_provider],
        "values": {left_provider: left_value, right_provider: right_value},
        "relative_delta": round(relative_delta, 8),
        "threshold": threshold,
        "failure_code": "DATA_DISAGREEMENT",
    }


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        for key in ("rows", "prices", "items", "data", "result"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return [dict(item) for item in value if isinstance(item, Mapping)]
        return [dict(payload)]
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    return []


def _text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
