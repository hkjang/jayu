from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_json, stable_hash


STOCK_LIFECYCLE_STATES = {
    "watch": "관심",
    "candidate": "후보",
    "holding": "보유",
    "caution": "경고",
    "reduce": "축소",
    "excluded": "제외",
}

STATE_ORDER = {
    "caution": 0,
    "reduce": 1,
    "candidate": 2,
    "holding": 3,
    "watch": 4,
    "excluded": 5,
}


def build_stock_lifecycle_report(
    signals: Mapping[str, Mapping[str, Any]],
    holdings: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    *,
    previous: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = now or datetime.now(UTC)
    previous_map = _previous_state_map(previous or {})
    holding_map = _holding_map(holdings)
    signal_map = {str(ticker).upper(): signal for ticker, signal in signals.items()}
    tickers = sorted(set(signal_map) | set(holding_map) | set(previous_map))
    items: list[dict[str, Any]] = []
    transitions = _previous_history(previous or {})
    for ticker in tickers:
        signal = signal_map.get(ticker, {})
        holding = holding_map.get(ticker, {})
        previous_state = previous_map.get(ticker, {})
        item = _lifecycle_item(ticker, signal, holding, previous_state, reference)
        items.append(item)
        if item["previous_status"] and item["previous_status"] != item["status"]:
            transitions.append(_transition_row(item, reference))

    items.sort(key=lambda item: (STATE_ORDER.get(str(item.get("status")), 99), str(item["ticker"])))
    status_counts = {state: 0 for state in STOCK_LIFECYCLE_STATES}
    for item in items:
        status_counts[str(item["status"])] = status_counts.get(str(item["status"]), 0) + 1
    return {
        "schema_version": 1,
        "status": "success" if items else "not_evaluated",
        "updated_at": reference.isoformat(),
        "summary": {
            "ticker_count": len(items),
            "transition_count": len(transitions),
            "status_counts": status_counts,
            "action_required_count": status_counts.get("caution", 0) + status_counts.get("reduce", 0),
        },
        "items": items,
        "history": transitions[-200:],
        "states": {item["ticker"]: item for item in items},
        "source": "signals JSON · holdings JSON · stock_lifecycle.py",
    }


def write_stock_lifecycle_report(
    signals: Mapping[str, Mapping[str, Any]],
    holdings: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    output_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    previous = read_json(output_path, default={})
    report = build_stock_lifecycle_report(
        signals,
        holdings,
        previous=previous if isinstance(previous, Mapping) else {},
        now=now,
    )
    atomic_write_json(output_path, report)
    return report


def _lifecycle_item(
    ticker: str,
    signal: Mapping[str, Any],
    holding: Mapping[str, Any],
    previous_state: Mapping[str, Any],
    reference: datetime,
) -> dict[str, Any]:
    status, reason = _derive_status(signal, holding, previous_state)
    previous_status = str(previous_state.get("status") or "")
    transitioned_at = (
        str(previous_state.get("transitioned_at") or previous_state.get("updated_at") or "")
        if previous_status == status
        else reference.isoformat()
    )
    risk_codes = _risk_codes(signal)
    action = str(signal.get("action") or signal.get("signal") or "hold")
    item = {
        "ticker": ticker,
        "status": status,
        "status_label": STOCK_LIFECYCLE_STATES.get(status, status),
        "previous_status": previous_status or None,
        "previous_status_label": STOCK_LIFECYCLE_STATES.get(previous_status, previous_status)
        if previous_status
        else None,
        "transitioned_at": transitioned_at or reference.isoformat(),
        "days_in_status": _days_since(transitioned_at, reference),
        "transition_reason": reason,
        "related_signal": action,
        "related_risk_codes": risk_codes,
        "holding": bool(holding),
        "market_value_krw": _float_or_none(holding.get("market_value_krw")),
        "quantity": _float_or_none(holding.get("quantity")),
        "recommended_action": _recommended_action(status, risk_codes),
        "source": "signals JSON · holdings JSON · previous stock_lifecycle.json",
    }
    item["lifecycle_id"] = stable_hash(
        {
            "ticker": ticker,
            "status": status,
            "transitioned_at": item["transitioned_at"],
        }
    )[:12]
    return item


def _derive_status(
    signal: Mapping[str, Any],
    holding: Mapping[str, Any],
    previous_state: Mapping[str, Any],
) -> tuple[str, str]:
    action = str(signal.get("action") or signal.get("signal") or "").lower()
    signal_text = str(signal.get("signal") or "")
    holding_exists = bool(holding)
    risk_codes = _risk_codes(signal)
    blocked = _blocked(signal)
    buy_like = action in {"buy", "entry", "buy_candidate", "weak_buy"} or "매수" in signal_text
    sell_like = action in {"sell", "exit", "reduce", "sell_candidate", "weak_sell"} or "매도" in signal_text
    if signal.get("excluded") is True or action == "excluded":
        return "excluded", "신호 또는 수동 설정에서 제외 상태로 표시되었습니다."
    if previous_state.get("status") == "excluded" and not buy_like and not holding_exists:
        return "excluded", "이전 제외 상태가 유지되었습니다."
    if holding_exists and sell_like:
        return "reduce", "보유 종목에 매도 또는 축소 신호가 발생했습니다."
    if blocked or risk_codes:
        reason = ", ".join(risk_codes[:3]) if risk_codes else "risk gate blocked"
        return "caution", f"리스크 또는 검증 사유로 점검이 필요합니다: {reason}"
    if buy_like and signal.get("eligible") is True:
        return "candidate", "운영 가능한 매수 후보로 분류되었습니다."
    if holding_exists:
        return "holding", "계좌 또는 보유 목록에서 현재 보유가 확인되었습니다."
    if sell_like:
        return "reduce", "매도 또는 축소 검토 신호가 발생했습니다."
    return "watch", "관심 또는 관망 상태로 추적합니다."


def _transition_row(item: Mapping[str, Any], reference: datetime) -> dict[str, Any]:
    return {
        "ticker": item.get("ticker"),
        "from_status": item.get("previous_status"),
        "from_label": item.get("previous_status_label"),
        "to_status": item.get("status"),
        "to_label": item.get("status_label"),
        "transitioned_at": item.get("transitioned_at") or reference.isoformat(),
        "reason": item.get("transition_reason"),
        "related_signal": item.get("related_signal"),
        "related_risk_codes": item.get("related_risk_codes", []),
    }


def _previous_state_map(previous: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    states = previous.get("states")
    if isinstance(states, Mapping):
        return {str(ticker).upper(): state for ticker, state in states.items() if isinstance(state, Mapping)}
    items = previous.get("items")
    if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
        return {
            str(item.get("ticker") or "").upper(): item
            for item in items
            if isinstance(item, Mapping) and item.get("ticker")
        }
    return {}


def _previous_history(previous: Mapping[str, Any]) -> list[dict[str, Any]]:
    history = previous.get("history")
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in history if isinstance(item, Mapping)]


def _holding_map(
    holdings: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> dict[str, Mapping[str, Any]]:
    rows = _holding_rows(holdings)
    mapped: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        ticker = _first_text(row, "symbol", "ticker", "stockCode", "stock_code", "code")
        if ticker:
            mapped[ticker.upper()] = row
    return mapped


def _holding_rows(
    holdings: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    if holdings is None:
        return []
    if isinstance(holdings, Mapping):
        for key in ("holdings", "positions", "result", "items", "data"):
            value = holdings.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
            if isinstance(value, Mapping):
                nested = _holding_rows(value)
                if nested:
                    return nested
        return [holdings] if _first_text(holdings, "symbol", "ticker", "stockCode") else []
    if isinstance(holdings, Sequence) and not isinstance(holdings, (str, bytes, bytearray)):
        return [item for item in holdings if isinstance(item, Mapping)]
    return []


def _risk_codes(signal: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    for key in ("reason_codes", "failed_codes", "warning_codes"):
        value = signal.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            codes.extend(str(item) for item in value if item)
    failed = signal.get("failed")
    if isinstance(failed, Sequence) and not isinstance(failed, (str, bytes, bytearray)):
        for item in failed:
            if isinstance(item, Mapping) and item.get("code"):
                codes.append(str(item["code"]))
    risk = signal.get("risk")
    if isinstance(risk, Mapping):
        details = risk.get("violation_details") or risk.get("failed")
        if isinstance(details, Sequence) and not isinstance(details, (str, bytes, bytearray)):
            for item in details:
                if isinstance(item, Mapping) and item.get("code"):
                    codes.append(str(item["code"]))
    return list(dict.fromkeys(codes))


def _blocked(signal: Mapping[str, Any]) -> bool:
    risk = signal.get("risk")
    risk_blocked = isinstance(risk, Mapping) and (
        risk.get("blocked") is True
        or str(risk.get("status") or "").lower() in {"blocked", "failed"}
        or bool(risk.get("violation_details"))
    )
    return signal.get("blocked") is True or (
        str(signal.get("action") or "").lower() == "buy" and signal.get("eligible") is not True
    ) or risk_blocked


def _recommended_action(status: str, risk_codes: Sequence[str]) -> str:
    if status == "candidate":
        return "OrderIntent 전 현금, 수량, 매수 유의사항을 확인하세요."
    if status == "caution":
        return f"리스크 코드 {', '.join(risk_codes[:3]) or '없음'}를 먼저 해소하세요."
    if status == "reduce":
        return "보유 비중, 손익률, 매도 가능 수량을 확인하세요."
    if status == "excluded":
        return "제외 사유가 해소될 때까지 자동 후보에서 제외하세요."
    if status == "holding":
        return "보유 조건과 매도 조건을 정기 점검하세요."
    return "관심 목록에서 다음 신호 변화를 관찰하세요."


def _days_since(value: str, reference: datetime) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max((reference - parsed.astimezone(reference.tzinfo or UTC)).days, 0)


def _first_text(row: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
