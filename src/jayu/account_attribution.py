from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import atomic_write_json

SCHEMA_VERSION = 1
DEFAULT_SOURCE = (
    "previous portfolio JSON · current portfolio JSON · Toss holdings GET · "
    "Toss exchange-rate GET · account_attribution.py"
)


def build_account_attribution_report(
    previous: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    current: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decompose account value change between two portfolio snapshots."""
    generated_at = (now or datetime.now(UTC)).isoformat()
    previous_rows = _holding_map(previous)
    current_rows = _holding_map(current)
    previous_summary = _summary(previous)
    current_summary = _summary(current)
    previous_market = _portfolio_market_value(previous_rows, previous_summary)
    current_market = _portfolio_market_value(current_rows, current_summary)
    previous_cash = _cash_value(previous_summary)
    current_cash = _cash_value(current_summary)
    cash_known = previous_cash is not None and current_cash is not None
    previous_account = previous_market + (previous_cash or 0.0)
    current_account = current_market + (current_cash or 0.0)

    all_symbols = sorted(set(previous_rows) | set(current_rows))
    rows = [
        _symbol_attribution(symbol, previous_rows.get(symbol), current_rows.get(symbol))
        for symbol in all_symbols
    ]
    price_effect = sum(float(row["price_effect_krw"] or 0.0) for row in rows)
    fx_effect = sum(float(row["fx_effect_krw"] or 0.0) for row in rows)
    cross_effect = sum(float(row["cross_effect_krw"] or 0.0) for row in rows)
    holding_flow = sum(float(row["holding_flow_krw"] or 0.0) for row in rows)
    market_delta = current_market - previous_market
    cash_delta = (current_cash or 0.0) - (previous_cash or 0.0) if cash_known else None
    account_delta = current_account - previous_account if cash_known else market_delta
    explained = price_effect + fx_effect + cross_effect + holding_flow + (cash_delta or 0.0)
    residual = account_delta - explained
    evaluated_count = sum(row["status"] in {"success", "partial"} for row in rows)
    common_count = sum(row["position_status"] == "common" for row in rows)
    flow_count = sum(row["position_status"] in {"new", "closed"} for row in rows)
    status = (
        "not_evaluated"
        if not previous_rows or not current_rows
        else "warning"
        if evaluated_count < common_count or not cash_known
        else "success"
    )
    if abs(residual) > max(abs(account_delta) * 0.05, 1.0):
        status = "warning" if status == "success" else status

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "summary": {
            "previous_market_value_krw": _round(previous_market, 2),
            "current_market_value_krw": _round(current_market, 2),
            "market_value_delta_krw": _round(market_delta, 2),
            "previous_cash_krw": _round(previous_cash, 2) if previous_cash is not None else None,
            "current_cash_krw": _round(current_cash, 2) if current_cash is not None else None,
            "cash_delta_krw": _round(cash_delta, 2) if cash_delta is not None else None,
            "previous_account_value_krw": _round(previous_account, 2),
            "current_account_value_krw": _round(current_account, 2),
            "account_value_delta_krw": _round(account_delta, 2),
            "price_effect_krw": _round(price_effect, 2),
            "fx_effect_krw": _round(fx_effect, 2),
            "cross_effect_krw": _round(cross_effect, 2),
            "holding_flow_krw": _round(holding_flow, 2),
            "residual_effect_krw": _round(residual, 2),
            "evaluated_count": evaluated_count,
            "common_holding_count": common_count,
            "flow_holding_count": flow_count,
            "cash_known": cash_known,
            "source": DEFAULT_SOURCE,
        },
        "rows": sorted(rows, key=lambda row: abs(float(row["value_delta_krw"])), reverse=True),
        "source": DEFAULT_SOURCE,
    }


def write_account_attribution_report(
    previous: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    current: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    output_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = build_account_attribution_report(previous, current, now=now)
    atomic_write_json(output_path, report)
    return report


def empty_account_attribution() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "not_evaluated",
        "summary": {
            "previous_market_value_krw": 0.0,
            "current_market_value_krw": 0.0,
            "market_value_delta_krw": 0.0,
            "previous_cash_krw": None,
            "current_cash_krw": None,
            "cash_delta_krw": None,
            "previous_account_value_krw": 0.0,
            "current_account_value_krw": 0.0,
            "account_value_delta_krw": 0.0,
            "price_effect_krw": 0.0,
            "fx_effect_krw": 0.0,
            "cross_effect_krw": 0.0,
            "holding_flow_krw": 0.0,
            "residual_effect_krw": 0.0,
            "evaluated_count": 0,
            "common_holding_count": 0,
            "flow_holding_count": 0,
            "cash_known": False,
            "source": "state/account_attribution.json",
        },
        "rows": [],
        "source": "state/account_attribution.json",
    }


def _symbol_attribution(
    symbol: str,
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    previous_value = _first_number(previous or {}, "market_value_krw", "value_krw") or 0.0
    current_value = _first_number(current or {}, "market_value_krw", "value_krw") or 0.0
    value_delta = current_value - previous_value
    position_status = (
        "new"
        if previous is None
        else "closed"
        if current is None
        else "common"
    )
    price_effect = _first_number(current or {}, "asset_effect_krw")
    fx_effect = _first_number(current or {}, "fx_effect_krw")
    cross_effect = _first_number(current or {}, "cross_effect_krw") or 0.0
    if position_status == "common" and price_effect is None:
        price_effect = _fallback_price_effect(previous_value, current or {})
    if position_status != "common":
        price_effect = 0.0
        fx_effect = 0.0
        cross_effect = 0.0
    status = "success" if price_effect is not None and fx_effect is not None else "partial"
    explained = (price_effect or 0.0) + (fx_effect or 0.0) + cross_effect
    holding_flow = value_delta - explained
    dominant = _dominant_effect(
        {
            "price": price_effect or 0.0,
            "fx": fx_effect or 0.0,
            "flow": holding_flow,
        }
    )
    row = current or previous or {}
    return {
        "symbol": symbol,
        "name": _first_text(row, "name", "symbolName", "stockName") or symbol,
        "currency": _first_text(row, "currency", "ccy") or "-",
        "position_status": position_status,
        "previous_value_krw": _round(previous_value, 2),
        "current_value_krw": _round(current_value, 2),
        "value_delta_krw": _round(value_delta, 2),
        "price_effect_krw": _round(price_effect, 2) if price_effect is not None else None,
        "fx_effect_krw": _round(fx_effect, 2) if fx_effect is not None else None,
        "cross_effect_krw": _round(cross_effect, 2),
        "holding_flow_krw": _round(holding_flow, 2),
        "dominant_effect": dominant,
        "status": status,
        "source": "portfolio snapshots · fx impact rows",
    }


def _holding_map(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> dict[str, Mapping[str, Any]]:
    rows = _holding_rows(payload)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _first_text(row, "symbol", "ticker", "stockCode", "code")
        if not symbol:
            continue
        existing = result.get(symbol, {})
        market_value = (_first_number(existing, "market_value_krw") or 0.0) + (
            _first_number(row, "market_value_krw", "value_krw") or 0.0
        )
        merged = {**existing, **dict(row)}
        merged["market_value_krw"] = market_value
        result[symbol] = merged
    return result


def _holding_rows(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        if _first_text(payload, "symbol", "ticker", "stockCode", "code"):
            return [payload]
        for key in ("holdings", "positions", "items", "data"):
            nested = payload.get(key)
            rows = _holding_rows(nested)  # type: ignore[arg-type]
            if rows:
                return rows
        result = payload.get("result")
        rows = _holding_rows(result)  # type: ignore[arg-type]
        if rows:
            return rows
        return []
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [item for item in payload if isinstance(item, Mapping)]
    return []


def _summary(payload: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        summary = payload.get("summary")
        return summary if isinstance(summary, Mapping) else payload
    return {}


def _portfolio_market_value(
    holdings: Mapping[str, Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> float:
    from_summary = _first_number(
        summary,
        "total_market_value_krw",
        "total_market_value",
        "market_value_krw",
    )
    if from_summary is not None:
        return from_summary
    return sum(_first_number(row, "market_value_krw", "value_krw") or 0.0 for row in holdings.values())


def _cash_value(summary: Mapping[str, Any]) -> float | None:
    return _first_number(
        summary,
        "cash_available_krw",
        "cash_available",
        "cash_balance_krw",
        "cash",
    )


def _fallback_price_effect(previous_value: float, row: Mapping[str, Any]) -> float | None:
    asset_return = _first_number(row, "asset_return_pct", "day_change_pct")
    if asset_return is None:
        return None
    return previous_value * asset_return


def _dominant_effect(values: Mapping[str, float]) -> str:
    if not values:
        return "none"
    key, value = max(values.items(), key=lambda item: abs(item[1]))
    return key if abs(value) > 0 else "none"


def _first_text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text.upper() if key in {"symbol", "ticker", "stockCode", "code"} else text
    return ""


def _first_number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)
