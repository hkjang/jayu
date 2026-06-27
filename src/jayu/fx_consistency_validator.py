from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def validate_fx_consistency(
    rates_by_provider: Mapping[str, Any],
    *,
    max_relative_delta: float = 0.003,
) -> dict[str, Any]:
    rows = {
        provider: _extract_rate(payload)
        for provider, payload in rates_by_provider.items()
    }
    rows = {provider: rate for provider, rate in rows.items() if rate is not None}
    names = list(rows)
    disagreements = []
    if len(names) >= 2:
        baseline_name = names[0]
        baseline = rows[baseline_name] or 0.0
        for candidate_name in names[1:]:
            candidate = rows[candidate_name] or 0.0
            relative = abs(baseline - candidate) / max(abs(baseline), 1e-12)
            if relative > max_relative_delta:
                disagreements.append(
                    {
                        "pair": "USD/KRW",
                        "providers": [baseline_name, candidate_name],
                        "values": {baseline_name: baseline, candidate_name: candidate},
                        "relative_delta": round(relative, 8),
                        "threshold": max_relative_delta,
                        "failure_code": "DATA_DISAGREEMENT",
                    }
                )
    return {
        "status": "failed" if disagreements else "success" if rows else "not_evaluated",
        "summary": {
            "provider_count": len(rows),
            "disagreement_count": len(disagreements),
            "min_rate": min(rows.values()) if rows else None,
            "max_rate": max(rows.values()) if rows else None,
        },
        "disagreements": disagreements,
        "source": "fx_consistency_validator.py - exchange-rate provider agreement",
    }


def _extract_rate(payload: Any) -> float | None:
    if isinstance(payload, Mapping):
        for key in ("rate", "exchangeRate", "basePrice", "price", "usd_krw"):
            value = payload.get(key)
            try:
                return float(str(value).replace(",", ""))
            except (TypeError, ValueError):
                continue
    try:
        return float(str(payload).replace(",", ""))
    except (TypeError, ValueError):
        return None
