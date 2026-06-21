from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import atomic_write_json

SCHEMA_VERSION = 1
DEFAULT_SOURCE = (
    "order_plan.json · holdings JSON · today_signals.json · risk settings · "
    "allocation_simulator.py"
)


def build_allocation_preview_report(
    order_plan: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    holdings: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    *,
    signals: Mapping[str, Any] | None = None,
    cash_krw: float | None = None,
    settings: Any | None = None,
    fx_rates: Mapping[str, float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Preview portfolio allocation after applying manual order-plan rows."""
    timestamp = (now or datetime.now(UTC)).isoformat()
    limits = _risk_limits(settings)
    signal_map = _signal_map(signals)
    rates = _fx_rates(fx_rates)
    holdings_before = _normalize_holdings(holdings, signal_map=signal_map, fx_rates=rates)
    orders = _normalize_orders(order_plan, signal_map=signal_map, fx_rates=rates)
    if not orders:
        orders = _orders_from_signals(
            signal_map,
            account_value_krw=_portfolio_value(holdings_before) + max(cash_krw or 0.0, 0.0),
        )

    invested_before = _portfolio_value(holdings_before)
    cash_known = cash_krw is not None
    before_cash = float(cash_krw or 0.0)
    before_account_value = invested_before + before_cash

    holdings_after = {ticker: dict(row) for ticker, row in holdings_before.items()}
    applied_orders: list[dict[str, Any]] = []
    skipped_orders: list[dict[str, Any]] = []
    buy_cash = 0.0
    sell_cash = 0.0
    cash_delta = 0.0

    for order in orders:
        issue = order.get("issue")
        if issue:
            skipped_orders.append(order)
            continue
        ticker = str(order["ticker"])
        side = str(order["side"])
        cash = float(order["cash_krw"])
        row = holdings_after.get(
            ticker,
            {
                "ticker": ticker,
                "name": order.get("name") or ticker,
                "sector": order.get("sector") or "UNKNOWN",
                "before_value_krw": 0.0,
                "after_value_krw": 0.0,
            },
        )
        row["sector"] = order.get("sector") or row.get("sector") or "UNKNOWN"
        before_value = float(row.get("after_value_krw") or row.get("before_value_krw") or 0.0)
        if side == "buy":
            row["after_value_krw"] = before_value + cash
            buy_cash += cash
            cash_delta -= cash
        elif side == "sell":
            applied_cash = min(cash, before_value) if before_value > 0 else cash
            row["after_value_krw"] = max(0.0, before_value - applied_cash)
            sell_cash += applied_cash
            cash_delta += applied_cash
            if before_value <= 0:
                order = {
                    **order,
                    "warning": "SELL_WITHOUT_HOLDING",
                    "message": "보유 평가금액 없이 매도 주문 금액이 입력되었습니다.",
                }
        holdings_after[ticker] = row
        applied_orders.append(order)

    after_cash = before_cash + cash_delta
    invested_after = _portfolio_value(holdings_after)
    after_account_value = invested_after + after_cash if cash_known else invested_after
    if after_account_value <= 0:
        after_account_value = 0.0

    holding_rows = _holding_delta_rows(
        holdings_before,
        holdings_after,
        before_account_value=before_account_value,
        after_account_value=after_account_value,
        max_single_position_pct=limits["max_single_position_pct"],
    )
    sector_rows = _sector_delta_rows(
        holdings_before,
        holdings_after,
        before_account_value=before_account_value,
        after_account_value=after_account_value,
        max_sector_pct=limits["max_sector_exposure"],
    )
    limit_checks = _limit_checks(
        holding_rows,
        sector_rows,
        after_cash=after_cash,
        after_account_value=after_account_value,
        cash_known=cash_known,
        limits=limits,
    )

    blocked_count = sum(1 for item in limit_checks if item["status"] == "blocked")
    warning_count = sum(1 for item in limit_checks if item["status"] == "warning")
    if not holdings_before and not orders:
        status = "not_evaluated"
    elif blocked_count or skipped_orders:
        status = "blocked"
    elif warning_count or (orders and not cash_known):
        status = "warning"
    else:
        status = "success"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamp,
        "status": status,
        "summary": {
            "holding_count_before": len(holdings_before),
            "holding_count_after": sum(1 for row in holding_rows if row["after_value_krw"] > 0),
            "order_count": len(orders),
            "applied_order_count": len(applied_orders),
            "skipped_order_count": len(skipped_orders),
            "before_account_value_krw": _round(before_account_value, 2),
            "after_account_value_krw": _round(after_account_value, 2),
            "before_cash_krw": _round(before_cash, 2) if cash_known else None,
            "after_cash_krw": _round(after_cash, 2) if cash_known else None,
            "cash_pct_after": _ratio(after_cash, after_account_value) if cash_known else None,
            "invested_pct_after": _ratio(invested_after, after_account_value),
            "buy_cash_krw": _round(buy_cash, 2),
            "sell_cash_krw": _round(sell_cash, 2),
            "max_position_breach_count": sum(
                1 for row in holding_rows if row["status"] == "blocked"
            ),
            "sector_breach_count": sum(1 for row in sector_rows if row["status"] == "blocked"),
            "cash_known": cash_known,
            "source": DEFAULT_SOURCE,
        },
        "orders": applied_orders,
        "skipped_orders": skipped_orders,
        "holdings": holding_rows,
        "sector_totals": sector_rows,
        "limit_checks": limit_checks,
        "limits": limits,
        "source": DEFAULT_SOURCE,
    }


def write_allocation_preview_report(
    order_plan: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    holdings: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    output_path: Path,
    *,
    signals: Mapping[str, Any] | None = None,
    cash_krw: float | None = None,
    settings: Any | None = None,
    fx_rates: Mapping[str, float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = build_allocation_preview_report(
        order_plan,
        holdings,
        signals=signals,
        cash_krw=cash_krw,
        settings=settings,
        fx_rates=fx_rates,
        now=now,
    )
    atomic_write_json(output_path, report)
    return report


def empty_allocation_preview() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "not_evaluated",
        "summary": {
            "holding_count_before": 0,
            "holding_count_after": 0,
            "order_count": 0,
            "applied_order_count": 0,
            "skipped_order_count": 0,
            "before_account_value_krw": 0.0,
            "after_account_value_krw": 0.0,
            "before_cash_krw": None,
            "after_cash_krw": None,
            "cash_pct_after": None,
            "invested_pct_after": None,
            "buy_cash_krw": 0.0,
            "sell_cash_krw": 0.0,
            "max_position_breach_count": 0,
            "sector_breach_count": 0,
            "cash_known": False,
            "source": "state/allocation_preview.json",
        },
        "orders": [],
        "skipped_orders": [],
        "holdings": [],
        "sector_totals": [],
        "limit_checks": [],
        "source": "state/allocation_preview.json",
    }


def _normalize_holdings(
    holdings: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    *,
    signal_map: Mapping[str, Mapping[str, Any]],
    fx_rates: Mapping[str, float],
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for row in _rows_from_payload(holdings):
        ticker = _first_text(row, "ticker", "symbol", "stockCode", "code")
        if not ticker:
            continue
        signal = signal_map.get(ticker, {})
        market_value = _holding_value_krw(row, fx_rates)
        if market_value is None:
            continue
        current = normalized.get(
            ticker,
            {
                "ticker": ticker,
                "name": _first_text(row, "name", "symbolName", "stockName") or ticker,
                "sector": _first_text(row, "sector", "sectorName")
                or _first_text(signal, "sector", "industry")
                or "UNKNOWN",
                "before_value_krw": 0.0,
                "after_value_krw": 0.0,
            },
        )
        current["before_value_krw"] = float(current["before_value_krw"]) + market_value
        current["after_value_krw"] = float(current["after_value_krw"]) + market_value
        normalized[ticker] = current
    return normalized


def _normalize_orders(
    order_plan: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    *,
    signal_map: Mapping[str, Mapping[str, Any]],
    fx_rates: Mapping[str, float],
) -> list[dict[str, Any]]:
    rows = _order_rows(order_plan)
    orders: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        ticker = _first_text(row, "ticker", "symbol", "stockCode", "code")
        side = _side(row)
        signal = signal_map.get(ticker, {})
        if not ticker or side is None:
            continue
        cash_krw, cash_source = _order_cash_krw(row, fx_rates)
        normalized = {
            "index": index,
            "ticker": ticker,
            "side": side,
            "action": side.upper(),
            "name": _first_text(row, "name", "symbolName", "stockName") or ticker,
            "sector": _first_text(row, "sector", "sectorName")
            or _first_text(signal, "sector", "industry")
            or "UNKNOWN",
            "currency": _first_text(row, "currency", "ccy") or "KRW",
            "quantity": _first_number(row, "quantity", "estimated_quantity", "est_quantity"),
            "price": _first_number(row, "price", "decision_price", "entry_price"),
            "approved_pct": _first_number(
                row,
                "approved_pct",
                "approved_position_pct",
                "target_position_pct",
            ),
            "cash_krw": _round(cash_krw, 2) if cash_krw is not None else None,
            "cash_source": cash_source,
            "source": "order_plan.json · today_signals.json",
        }
        if cash_krw is None or cash_krw <= 0:
            normalized["issue"] = "MISSING_ORDER_CASH_KRW"
            normalized["message"] = (
                "estimated_cash_krw, KRW 금액, 또는 FX 환산 가능한 주문 금액이 없습니다."
            )
        orders.append(normalized)
    return orders


def _orders_from_signals(
    signals: Mapping[str, Mapping[str, Any]],
    *,
    account_value_krw: float,
) -> list[dict[str, Any]]:
    if account_value_krw <= 0:
        return []
    rows: list[dict[str, Any]] = []
    for ticker, signal in sorted(signals.items()):
        if not _is_buy_signal(signal):
            continue
        approved_pct = _first_number(
            signal,
            "approved_position_pct",
            "approved_pct",
            "target_position_pct",
        )
        if approved_pct is None or approved_pct <= 0:
            continue
        rows.append(
            {
                "index": len(rows) + 1,
                "ticker": ticker,
                "side": "buy",
                "action": "BUY",
                "name": _first_text(signal, "name") or ticker,
                "sector": _first_text(signal, "sector", "industry") or "UNKNOWN",
                "currency": "KRW",
                "quantity": None,
                "price": _first_number(signal, "entry_price", "price"),
                "approved_pct": approved_pct,
                "cash_krw": _round(account_value_krw * approved_pct, 2),
                "cash_source": "today_signals.json approved_position_pct",
                "source": "today_signals.json · derived allocation preview",
            }
        )
    return rows


def _limit_checks(
    holdings: Sequence[Mapping[str, Any]],
    sectors: Sequence[Mapping[str, Any]],
    *,
    after_cash: float,
    after_account_value: float,
    cash_known: bool,
    limits: Mapping[str, float],
) -> list[dict[str, Any]]:
    checks = [
        {
            "id": "cash_floor",
            "label": "최소 현금 비중",
            "observed": _ratio(after_cash, after_account_value) if cash_known else None,
            "limit": limits["min_cash_pct"],
            "status": "not_evaluated",
            "source": "risk settings · cash_krw input",
        },
        {
            "id": "single_position",
            "label": "단일 종목 비중",
            "observed": max((float(row["after_weight"]) for row in holdings), default=0.0),
            "limit": limits["max_single_position_pct"],
            "status": "success",
            "source": "holdings JSON · order_plan.json · risk settings",
        },
        {
            "id": "sector_exposure",
            "label": "섹터 비중",
            "observed": max((float(row["after_weight"]) for row in sectors), default=0.0),
            "limit": limits["max_sector_exposure"],
            "status": "success",
            "source": "holdings JSON · order_plan.json · risk settings",
        },
    ]
    if cash_known:
        checks[0]["status"] = (
            "blocked" if float(checks[0]["observed"] or 0.0) < limits["min_cash_pct"] else "success"
        )
    for check in checks[1:]:
        check["status"] = (
            "blocked" if float(check["observed"] or 0.0) > float(check["limit"]) else "success"
        )
    if not cash_known:
        checks[0]["message"] = "cash_krw가 없어 주문 후 현금 비중은 미평가입니다."
    return checks


def _holding_delta_rows(
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
    *,
    before_account_value: float,
    after_account_value: float,
    max_single_position_pct: float,
) -> list[dict[str, Any]]:
    tickers = set(before) | set(after)
    rows = []
    for ticker in sorted(tickers):
        before_row = before.get(ticker, {})
        after_row = after.get(ticker, before_row)
        before_value = float(before_row.get("before_value_krw") or 0.0)
        after_value = float(after_row.get("after_value_krw") or 0.0)
        before_weight = _ratio(before_value, before_account_value)
        after_weight = _ratio(after_value, after_account_value)
        rows.append(
            {
                "ticker": ticker,
                "name": after_row.get("name") or before_row.get("name") or ticker,
                "sector": after_row.get("sector") or before_row.get("sector") or "UNKNOWN",
                "before_value_krw": _round(before_value, 2),
                "after_value_krw": _round(after_value, 2),
                "before_weight": before_weight,
                "after_weight": after_weight,
                "delta_weight": _round(after_weight - before_weight, 6),
                "limit": _round(max_single_position_pct, 6),
                "status": "blocked" if after_weight > max_single_position_pct else "success",
                "source": "holdings JSON · order_plan.json",
            }
        )
    return sorted(rows, key=lambda row: abs(float(row["delta_weight"])), reverse=True)


def _sector_delta_rows(
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
    *,
    before_account_value: float,
    after_account_value: float,
    max_sector_pct: float,
) -> list[dict[str, Any]]:
    before_totals = _sector_totals(before)
    after_totals = _sector_totals(after)
    sectors = set(before_totals) | set(after_totals)
    rows = []
    for sector in sorted(sectors):
        before_weight = _ratio(before_totals.get(sector, 0.0), before_account_value)
        after_weight = _ratio(after_totals.get(sector, 0.0), after_account_value)
        rows.append(
            {
                "sector": sector,
                "before_weight": before_weight,
                "after_weight": after_weight,
                "delta_weight": _round(after_weight - before_weight, 6),
                "limit": _round(max_sector_pct, 6),
                "status": "blocked" if after_weight > max_sector_pct else "success",
                "source": "holdings JSON sector · order_plan.json · risk settings",
            }
        )
    return sorted(rows, key=lambda row: float(row["after_weight"]), reverse=True)


def _sector_totals(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows.values():
        sector = str(row.get("sector") or "UNKNOWN")
        totals[sector] = totals.get(sector, 0.0) + float(row.get("after_value_krw") or 0.0)
    return totals


def _order_cash_krw(row: Mapping[str, Any], fx_rates: Mapping[str, float]) -> tuple[float | None, str]:
    explicit = _first_number(
        row,
        "estimated_cash_krw",
        "target_cash_krw",
        "cash_krw",
        "amount_krw",
        "order_cash_krw",
    )
    if explicit is not None:
        return explicit, "estimated_cash_krw"
    amount = _first_number(row, "estimated_cash", "target_cash", "cash", "amount", "order_cash")
    currency = (_first_text(row, "currency", "ccy") or "KRW").upper()
    rate = fx_rates.get(currency)
    if amount is not None and rate is not None:
        return amount * rate, f"estimated_cash {currency} × FX"
    quantity = _first_number(row, "quantity", "estimated_quantity", "est_quantity")
    price = _first_number(row, "price", "decision_price", "entry_price")
    if quantity is not None and price is not None and rate is not None:
        return quantity * price * rate, f"quantity × price {currency} × FX"
    return None, "missing"


def _holding_value_krw(row: Mapping[str, Any], fx_rates: Mapping[str, float]) -> float | None:
    explicit = _first_number(
        row,
        "market_value_krw",
        "marketValueKrw",
        "evaluation_amount_krw",
        "evaluationAmountKrw",
        "value_krw",
    )
    if explicit is not None:
        return explicit
    value = _first_number(
        row,
        "market_value",
        "marketValue",
        "evaluation_amount",
        "evaluationAmount",
        "value",
    )
    if value is None:
        quantity = _first_number(row, "quantity", "qty")
        price = _first_number(row, "price", "currentPrice", "current_price")
        if quantity is not None and price is not None:
            value = quantity * price
    if value is None:
        return None
    currency = (_first_text(row, "currency", "ccy") or "KRW").upper()
    rate = fx_rates.get(currency)
    return value * rate if rate is not None else None


def _rows_from_payload(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        if _first_text(payload, "ticker", "symbol", "stockCode", "code"):
            return [payload]
        for key in ("holdings", "positions", "items", "data"):
            nested = payload.get(key)
            rows = _rows_from_payload(nested)  # type: ignore[arg-type]
            if rows:
                return rows
        result = payload.get("result")
        rows = _rows_from_payload(result)  # type: ignore[arg-type]
        if rows:
            return rows
        return []
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [item for item in payload if isinstance(item, Mapping)]
    return []


def _order_rows(
    order_plan: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    if order_plan is None:
        return []
    if isinstance(order_plan, Mapping):
        orders = order_plan.get("orders")
        if isinstance(orders, Sequence) and not isinstance(orders, (str, bytes, bytearray)):
            return [item for item in orders if isinstance(item, Mapping)]
        if _first_text(order_plan, "ticker", "symbol", "stockCode", "code"):
            return [order_plan]
        return []
    if isinstance(order_plan, Sequence) and not isinstance(order_plan, (str, bytes, bytearray)):
        return [item for item in order_plan if isinstance(item, Mapping)]
    return []


def _signal_map(signals: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not isinstance(signals, Mapping):
        return {}
    result = {}
    for ticker, signal in signals.items():
        if isinstance(signal, Mapping):
            result[str(ticker).upper()] = signal
    return result


def _fx_rates(rates: Mapping[str, float] | None) -> dict[str, float]:
    return {"KRW": 1.0, **{str(key).upper(): float(value) for key, value in (rates or {}).items()}}


def _risk_limits(settings: Any | None) -> dict[str, float]:
    risk = getattr(settings, "risk", settings)
    return {
        "max_single_position_pct": _policy_value(risk, "max_single_position_pct", 0.10),
        "max_sector_exposure": _policy_value(risk, "max_sector_exposure", 0.50),
        "min_cash_pct": _policy_value(risk, "min_cash_pct", 0.15),
        "max_invested_pct": _policy_value(risk, "max_invested_pct", 0.85),
    }


def _policy_value(policy: Any, key: str, default: float) -> float:
    if isinstance(policy, Mapping):
        value = policy.get(key, default)
    else:
        value = getattr(policy, key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _portfolio_value(rows: Mapping[str, Mapping[str, Any]]) -> float:
    return sum(float(row.get("after_value_krw") or 0.0) for row in rows.values())


def _side(row: Mapping[str, Any]) -> str | None:
    raw = str(row.get("side") or row.get("action") or "").strip().lower()
    if raw in {"buy", "매수"}:
        return "buy"
    if raw in {"sell", "매도"}:
        return "sell"
    return None


def _is_buy_signal(signal: Mapping[str, Any]) -> bool:
    action = str(signal.get("action") or signal.get("signal") or "").lower()
    eligible = bool(signal.get("eligible", True))
    return eligible and ("buy" in action or "매수" in action)


def _first_text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text.upper() if key in {"ticker", "symbol", "stockCode", "code"} else text
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


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return _round(numerator / denominator, 6)


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)
