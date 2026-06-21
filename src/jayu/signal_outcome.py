from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_json, stable_hash


DEFAULT_HORIZONS = (1, 5, 20)

DECISION_GROUP_LABELS = {
    "buy_candidate": "매수 후보",
    "blocked_buy": "차단된 매수",
    "sell_candidate": "매도 후보",
    "hold": "관망",
}

DECISION_GROUP_ORDER = {
    "buy_candidate": 0,
    "blocked_buy": 1,
    "sell_candidate": 2,
    "hold": 3,
}


def evaluate_signal_outcomes(
    signals: Mapping[str, Mapping[str, Any]],
    price_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    rows = [
        _evaluate_signal(ticker, signal, price_history, horizons)
        for ticker, signal in signals.items()
        if isinstance(signal, Mapping)
    ]
    return _build_report(rows, horizons, scope="latest")


def write_signal_outcome_report(
    signals: Mapping[str, Mapping[str, Any]],
    price_history: Mapping[str, Sequence[Mapping[str, Any]]],
    output_path: Path,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    report = evaluate_signal_outcomes(signals, price_history, horizons=horizons)
    existing = read_json(output_path, default={})
    existing_history = (
        existing.get("history_rows", [])
        if isinstance(existing, Mapping) and isinstance(existing.get("history_rows"), list)
        else []
    )
    history_rows = _merge_history(existing_history, report["rows"], horizons)
    report["history_rows"] = history_rows
    report["history_signal_count"] = len(history_rows)
    report["cumulative"] = _build_report(history_rows, horizons, scope="cumulative")
    atomic_write_json(output_path, report)
    return report


def _evaluate_signal(
    ticker: str,
    signal: Mapping[str, Any],
    price_history: Mapping[str, Sequence[Mapping[str, Any]]],
    horizons: Sequence[int],
) -> dict[str, Any]:
    normalized_ticker = str(signal.get("ticker") or ticker).upper()
    action = _action(signal)
    decision_group = _decision_group(signal, action)
    strategy = _strategy(signal)
    signal_date = _date_key(signal.get("signal_date") or signal.get("date") or signal.get("generated_at"))
    prices = _price_rows(price_history.get(normalized_ticker) or price_history.get(ticker) or [])
    empty_returns = {f"{horizon}d": None for horizon in horizons}
    signal_id = stable_hash(
        {
            "ticker": normalized_ticker,
            "signal_date": signal_date,
            "action": action,
            "decision_group": decision_group,
            "strategy": strategy,
        }
    )
    base_row: dict[str, Any] = {
        "signal_id": signal_id,
        "ticker": normalized_ticker,
        "signal_date": signal_date or None,
        "action": action,
        "decision_group": decision_group,
        "decision_group_label": DECISION_GROUP_LABELS.get(decision_group, decision_group),
        "strategy": strategy,
        "eligible": signal.get("eligible") is True,
        "blocked": _is_blocked_buy(signal, action),
        "returns": empty_returns,
        "horizon_status": "pending",
    }
    if len(prices) < 2:
        return {**base_row, "error": "not_enough_prices"}

    start_index = _start_index(prices, signal_date)
    if start_index is None:
        return {**base_row, "error": "signal_date_not_in_price_history"}

    start_price = prices[start_index]["close"]
    returns: dict[str, float | None] = {}
    for horizon in horizons:
        key = f"{horizon}d"
        end_index = start_index + int(horizon)
        if start_price <= 0 or end_index >= len(prices):
            returns[key] = None
            continue
        end_price = prices[end_index]["close"]
        returns[key] = end_price / start_price - 1 if end_price > 0 else None

    available = sum(value is not None for value in returns.values())
    if available == len(returns):
        horizon_status = "completed"
    elif available:
        horizon_status = "partial"
    else:
        horizon_status = "pending"
    row = {
        **base_row,
        "start_date": prices[start_index]["date"],
        "start_price": start_price,
        "returns": returns,
        "horizon_status": horizon_status,
    }
    if available:
        return row
    return {**row, "error": "awaiting_future_prices"}


def _build_report(
    rows: Sequence[Mapping[str, Any]],
    horizons: Sequence[int],
    *,
    scope: str,
) -> dict[str, Any]:
    signal_count = len(rows)
    evaluated_count = sum(_has_return(row) for row in rows)
    pending_count = signal_count - evaluated_count
    if not signal_count:
        status = "not_evaluated"
    elif not evaluated_count:
        status = "pending"
    elif pending_count:
        status = "partial"
    else:
        status = "success"
    aggregate = _horizon_map(rows, horizons)
    by_decision_group = _group_summaries(rows, horizons, "decision_group", DECISION_GROUP_LABELS)
    by_strategy = _group_summaries(rows, horizons, "strategy", {})
    blocked_avoidance = _blocked_avoidance(rows, horizons)
    return {
        "schema_version": 1,
        "status": status,
        "scope": scope,
        "basis": "gross_close_to_close_no_fees_spread_slippage",
        "horizons": list(horizons),
        "summary": {
            "status": status,
            "signal_count": signal_count,
            "evaluated_count": evaluated_count,
            "pending_count": pending_count,
            "buy_candidate_count": sum(
                row.get("decision_group") == "buy_candidate" for row in rows
            ),
            "blocked_buy_count": sum(row.get("decision_group") == "blocked_buy" for row in rows),
            "hold_count": sum(row.get("decision_group") == "hold" for row in rows),
            "sell_candidate_count": sum(
                row.get("decision_group") == "sell_candidate" for row in rows
            ),
        },
        "aggregate": aggregate,
        "by_decision_group": by_decision_group,
        "by_strategy": by_strategy,
        "blocked_avoidance": blocked_avoidance,
        "rows": [dict(row) for row in rows],
        "source": "signals JSON · price history JSON · signal_outcome.py",
    }


def _group_summaries(
    rows: Sequence[Mapping[str, Any]],
    horizons: Sequence[int],
    group_key: str,
    labels: Mapping[str, str],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(group_key) or "unknown")].append(row)

    summaries = [
        {
            "key": key,
            "label": labels.get(key, key),
            "signal_count": len(items),
            "evaluated_count": sum(_has_return(item) for item in items),
            "horizons": _horizon_map(items, horizons),
        }
        for key, items in grouped.items()
    ]
    if group_key == "decision_group":
        return sorted(
            summaries,
            key=lambda item: (DECISION_GROUP_ORDER.get(str(item["key"]), 99), str(item["key"])),
        )
    return sorted(summaries, key=lambda item: (-int(item["signal_count"]), str(item["key"])))


def _horizon_map(
    rows: Sequence[Mapping[str, Any]],
    horizons: Sequence[int],
) -> dict[str, dict[str, Any]]:
    return {f"{horizon}d": _horizon_stats(rows, f"{horizon}d") for horizon in horizons}


def _horizon_stats(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    values = [
        float(row["returns"][key])
        for row in rows
        if isinstance(row.get("returns"), Mapping) and row["returns"].get(key) is not None
    ]
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    return {
        "sample_count": len(values),
        "avg_return": _round(sum(values) / len(values)) if values else None,
        "hit_rate": _round(wins / len(values), digits=4) if values else None,
        "win_count": wins,
        "loss_count": losses,
        "flat_count": len(values) - wins - losses,
        "max_gain": _round(max(values)) if values else None,
        "max_loss": _round(min(values)) if values else None,
    }


def _blocked_avoidance(
    rows: Sequence[Mapping[str, Any]],
    horizons: Sequence[int],
) -> dict[str, dict[str, Any]]:
    blocked_rows = [row for row in rows if row.get("decision_group") == "blocked_buy"]
    summary: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        key = f"{horizon}d"
        values = [
            float(row["returns"][key])
            for row in blocked_rows
            if isinstance(row.get("returns"), Mapping) and row["returns"].get(key) is not None
        ]
        avoided_losses = [-value for value in values if value < 0]
        missed_gains = [value for value in values if value > 0]
        summary[key] = {
            "blocked_count": len(blocked_rows),
            "sample_count": len(values),
            "avoided_loss_count": len(avoided_losses),
            "avg_avoided_loss": _round(sum(avoided_losses) / len(avoided_losses))
            if avoided_losses
            else None,
            "missed_gain_count": len(missed_gains),
            "avg_missed_gain": _round(sum(missed_gains) / len(missed_gains))
            if missed_gains
            else None,
            "worst_blocked_return": _round(min(values)) if values else None,
        }
    return summary


def _merge_history(
    existing: Sequence[Mapping[str, Any]],
    latest: Sequence[Mapping[str, Any]],
    horizons: Sequence[int],
) -> list[dict[str, Any]]:
    merged = {
        str(row.get("signal_id")): dict(row)
        for row in existing
        if isinstance(row, Mapping) and isinstance(row.get("signal_id"), str)
    }
    horizon_keys = {f"{horizon}d" for horizon in horizons}
    for row in latest:
        signal_id = row.get("signal_id")
        if not isinstance(signal_id, str):
            continue
        previous = merged.get(signal_id, {})
        previous_returns = previous.get("returns") if isinstance(previous, Mapping) else {}
        latest_returns = row.get("returns")
        previous_map = previous_returns if isinstance(previous_returns, Mapping) else {}
        latest_map = latest_returns if isinstance(latest_returns, Mapping) else {}
        combined_returns = {
            key: latest_map.get(key) if latest_map.get(key) is not None else previous_map.get(key)
            for key in horizon_keys | set(previous_map) | set(latest_map)
        }
        merged_row = {**previous, **dict(row), "returns": combined_returns}
        if any(value is not None for value in combined_returns.values()):
            merged_row.pop("error", None)
            merged_row["horizon_status"] = (
                "completed"
                if all(combined_returns.get(key) is not None for key in horizon_keys)
                else "partial"
            )
        merged[signal_id] = merged_row
    return sorted(
        merged.values(),
        key=lambda row: (str(row.get("signal_date") or ""), str(row.get("ticker") or "")),
    )


def _price_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prices = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        date = _date_key(row.get("date") or row.get("timestamp") or row.get("Datetime"))
        close = _float_value(
            row.get("close")
            if row.get("close") is not None
            else row.get("Close")
            if row.get("Close") is not None
            else row.get("adj_close")
        )
        if date and close is not None:
            prices.append({"date": date, "close": close})
    return sorted(prices, key=lambda item: item["date"])


def _start_index(prices: Sequence[Mapping[str, Any]], signal_date: str) -> int | None:
    if not signal_date:
        return 0
    return next(
        (
            index
            for index, row in enumerate(prices)
            if str(row.get("date") or "") >= signal_date
        ),
        None,
    )


def _decision_group(signal: Mapping[str, Any], action: str) -> str:
    signal_text = str(signal.get("signal") or "")
    if action in {"buy", "entry"} or "매수" in signal_text:
        return "blocked_buy" if _is_blocked_buy(signal, action) else "buy_candidate"
    if action in {"sell", "exit"} or "매도" in signal_text:
        return "sell_candidate"
    return "hold"


def _is_blocked_buy(signal: Mapping[str, Any], action: str) -> bool:
    if action not in {"buy", "entry"} and "매수" not in str(signal.get("signal") or ""):
        return False
    risk = signal.get("risk")
    risk_blocked = (
        isinstance(risk, Mapping)
        and (
            risk.get("blocked") is True
            or str(risk.get("status") or "").lower() in {"blocked", "failed"}
            or bool(risk.get("violation_details"))
        )
    )
    return signal.get("blocked") is True or signal.get("eligible") is not True or risk_blocked


def _action(signal: Mapping[str, Any]) -> str:
    action = str(signal.get("action") or signal.get("signal") or "hold").strip().lower()
    return action or "hold"


def _strategy(signal: Mapping[str, Any]) -> str:
    for key in ("strategy_mode", "strategy", "regime", "portfolio_type"):
        value = signal.get(key)
        if value:
            return str(value)
    return "unknown"


def _date_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value)[:10]


def _float_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_return(row: Mapping[str, Any]) -> bool:
    returns = row.get("returns")
    return isinstance(returns, Mapping) and any(value is not None for value in returns.values())


def _round(value: float, *, digits: int = 6) -> float:
    return round(float(value), digits)
