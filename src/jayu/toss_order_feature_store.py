from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .order_history_utils import (
    KRW_PER_USD_FALLBACK,
    amount_krw,
    commission,
    currency,
    filled_quantity,
    is_filled,
    order_id,
    order_rows,
    parse_ordered_at,
    price,
    quantity,
    side,
    symbol,
    tax,
)


@dataclass
class OpenLot:
    symbol: str
    currency: str
    portfolio_type: str
    quantity: float
    unit_price: float
    ordered_at: Any
    commission_per_share: float


def build_toss_order_feature_store(
    orders_payload: Any,
    *,
    usd_krw: float = KRW_PER_USD_FALLBACK,
    portfolio_mapping: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = sorted(
        [row for row in order_rows(orders_payload) if is_filled(row)],
        key=lambda row: str(row.get("orderedAt") or row.get("ordered_at") or ""),
    )
    order_features: list[dict[str, Any]] = []
    trade_rounds: list[dict[str, Any]] = []
    open_lots: dict[str, list[OpenLot]] = defaultdict(list)
    by_symbol: dict[str, dict[str, Any]] = defaultdict(_symbol_bucket)
    by_month: dict[str, dict[str, Any]] = defaultdict(_period_bucket)
    by_portfolio_type: dict[str, dict[str, Any]] = defaultdict(_portfolio_bucket)

    for row in rows:
        sym = symbol(row)
        sd = side(row)
        px = price(row)
        qty = filled_quantity(row) or quantity(row)
        if not sym or sd not in {"BUY", "SELL"} or px is None or qty is None or px <= 0 or qty <= 0:
            continue

        cur = currency(row)
        dt = parse_ordered_at(row.get("orderedAt") or row.get("ordered_at"))
        month = f"{dt.year:04d}-{dt.month:02d}" if dt else "UNKNOWN"
        ptype = _portfolio_type_for(sym, portfolio_mapping)
        amount = amount_krw(row, usd_krw=usd_krw) or _to_krw(qty * px, cur, usd_krw)
        comm_krw = _to_krw(commission(row), cur, usd_krw)
        tax_krw = _to_krw(tax(row), cur, usd_krw)
        feature = {
            "order_id": order_id(row),
            "symbol": sym,
            "side": sd,
            "status": row.get("status") or row.get("orderStatus") or row.get("historyStatus"),
            "ordered_at": dt.isoformat() if dt else None,
            "month": month,
            "currency": cur,
            "quantity": _round(qty, 6),
            "price": _round(px, 6),
            "amount_krw": _round(amount, 2),
            "commission_krw": _round(comm_krw, 2),
            "tax_krw": _round(tax_krw, 2),
            "portfolio_type": ptype,
        }
        order_features.append(feature)

        for bucket in (by_symbol[sym], by_month[month], by_portfolio_type[ptype]):
            _add_order(bucket, sd, amount, comm_krw, tax_krw)
        by_symbol[sym]["symbol"] = sym
        by_symbol[sym]["portfolio_type"] = ptype
        by_month[month]["period"] = month
        by_portfolio_type[ptype]["portfolio_type"] = ptype

        if sd == "BUY":
            open_lots[sym].append(
                OpenLot(
                    symbol=sym,
                    currency=cur,
                    portfolio_type=ptype,
                    quantity=qty,
                    unit_price=px,
                    ordered_at=dt,
                    commission_per_share=commission(row) / qty if qty else 0.0,
                )
            )
            continue

        matched = _match_sell(
            open_lots[sym],
            row=row,
            sell_quantity=qty,
            sell_price=px,
            sell_commission_krw=comm_krw,
            sell_tax_krw=tax_krw,
            usd_krw=usd_krw,
        )
        trade_rounds.extend(matched)
        for trade in matched:
            _add_round(by_symbol[trade["symbol"]], trade)
            _add_round(by_month[month], trade)
            _add_round(by_portfolio_type[trade["portfolio_type"]], trade)

    by_symbol_rows = [_finalize_bucket(item) for item in by_symbol.values()]
    by_month_rows = [_finalize_bucket(item) for item in by_month.values()]
    by_portfolio_rows = [_finalize_bucket(item) for item in by_portfolio_type.values()]
    summary = _finalize_bucket(_summary_bucket(order_features, trade_rounds))

    return {
        "status": "success" if order_features else "not_evaluated",
        "summary": summary,
        "orders": order_features,
        "trade_rounds": [_round_trade(item) for item in trade_rounds],
        "by_symbol": sorted(by_symbol_rows, key=lambda item: abs(item.get("realized_pnl_krw") or 0.0), reverse=True),
        "by_month": sorted(by_month_rows, key=lambda item: item.get("period") or "")[-72:],
        "by_portfolio_type": sorted(by_portfolio_rows, key=lambda item: item.get("portfolio_type") or ""),
        "open_lots": _open_lot_rows(open_lots),
        "source": "state/toss_orders.json - Toss Order History getOrders - toss_order_feature_store.py",
        "assumptions": {
            "usd_krw": usd_krw,
            "realized_pnl_method": "symbol-level FIFO using filled orders",
            "portfolio_type_method": "configs/portfolio_mapping.json ticker metadata when available",
        },
    }


def _match_sell(
    lots: list[OpenLot],
    *,
    row: Mapping[str, Any],
    sell_quantity: float,
    sell_price: float,
    sell_commission_krw: float,
    sell_tax_krw: float,
    usd_krw: float,
) -> list[dict[str, Any]]:
    sell_dt = parse_ordered_at(row.get("orderedAt") or row.get("ordered_at"))
    sell_cur = currency(row)
    remaining = sell_quantity
    realized = []
    while remaining > 1e-9 and lots:
        lot = lots[0]
        matched_qty = min(remaining, lot.quantity)
        buy_value_krw = _to_krw(matched_qty * lot.unit_price, lot.currency, usd_krw)
        sell_value_krw = _to_krw(matched_qty * sell_price, sell_cur, usd_krw)
        sell_cost_alloc = (sell_commission_krw + sell_tax_krw) * (matched_qty / sell_quantity)
        buy_cost_alloc = _to_krw(lot.commission_per_share * matched_qty, lot.currency, usd_krw)
        realized_pnl = sell_value_krw - buy_value_krw - sell_cost_alloc - buy_cost_alloc
        holding_days = (sell_dt - lot.ordered_at).days if sell_dt and lot.ordered_at else None
        denominator = buy_value_krw + buy_cost_alloc
        realized.append(
            {
                "order_id": order_id(row),
                "symbol": lot.symbol,
                "portfolio_type": lot.portfolio_type,
                "quantity": matched_qty,
                "buy_at": lot.ordered_at.isoformat() if lot.ordered_at else None,
                "sell_at": sell_dt.isoformat() if sell_dt else None,
                "buy_price": lot.unit_price,
                "sell_price": sell_price,
                "buy_value_krw": buy_value_krw,
                "sell_value_krw": sell_value_krw,
                "fees_krw": buy_cost_alloc + sell_cost_alloc,
                "realized_pnl_krw": realized_pnl,
                "return_pct": (realized_pnl / denominator * 100.0) if denominator > 0 else None,
                "holding_days": holding_days,
            }
        )
        lot.quantity -= matched_qty
        remaining -= matched_qty
        if lot.quantity <= 1e-9:
            lots.pop(0)
    return realized


def _portfolio_type_for(symbol_value: str, mapping: Mapping[str, Any] | None) -> str:
    sym = symbol_value.upper()
    if not mapping:
        return "unclassified"
    tickers = mapping.get("tickers") if isinstance(mapping.get("tickers"), Mapping) else mapping
    if isinstance(tickers, Mapping):
        direct = tickers.get(sym) or tickers.get(sym.replace(".KS", ""))
        if isinstance(direct, str):
            return direct
        if isinstance(direct, Mapping):
            types = direct.get("portfolio_types") or direct.get("portfolio_type")
            if isinstance(types, list) and types:
                return str(types[0])
            if isinstance(types, str):
                return types
        for portfolio_type, value in tickers.items():
            if isinstance(value, list) and sym in {str(item).upper() for item in value}:
                return str(portfolio_type)
            if isinstance(value, Mapping):
                symbols = value.get("symbols") or value.get("tickers")
                if isinstance(symbols, list) and sym in {str(item).upper() for item in symbols}:
                    return str(portfolio_type)
    return "unclassified"


def _symbol_bucket() -> dict[str, Any]:
    bucket = _period_bucket()
    bucket.update({"symbol": "", "portfolio_type": "unclassified"})
    return bucket


def _period_bucket() -> dict[str, Any]:
    return {
        "period": "",
        "trade_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "buy_amount_krw": 0.0,
        "sell_amount_krw": 0.0,
        "commission_krw": 0.0,
        "tax_krw": 0.0,
        "realized_pnl_krw": 0.0,
        "round_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "return_pct_total": 0.0,
        "return_pct_count": 0,
        "holding_days_total": 0.0,
        "holding_days_count": 0,
    }


def _portfolio_bucket() -> dict[str, Any]:
    bucket = _period_bucket()
    bucket.update({"portfolio_type": ""})
    return bucket


def _summary_bucket(order_features: list[dict[str, Any]], trade_rounds: list[dict[str, Any]]) -> dict[str, Any]:
    bucket = _period_bucket()
    bucket["period"] = "all"
    for row in order_features:
        side_value = str(row.get("side") or "")
        _add_order(
            bucket,
            side_value,
            float(row.get("amount_krw") or 0.0),
            float(row.get("commission_krw") or 0.0),
            float(row.get("tax_krw") or 0.0),
        )
    for trade in trade_rounds:
        _add_round(bucket, trade)
    return bucket


def _add_order(bucket: dict[str, Any], side_value: str, amount: float, comm_krw: float, tax_krw: float) -> None:
    bucket["trade_count"] += 1
    bucket["commission_krw"] += comm_krw
    bucket["tax_krw"] += tax_krw
    if side_value == "BUY":
        bucket["buy_count"] += 1
        bucket["buy_amount_krw"] += amount
    elif side_value == "SELL":
        bucket["sell_count"] += 1
        bucket["sell_amount_krw"] += amount


def _add_round(bucket: dict[str, Any], trade: Mapping[str, Any]) -> None:
    pnl = float(trade.get("realized_pnl_krw") or 0.0)
    bucket["round_count"] += 1
    bucket["realized_pnl_krw"] += pnl
    bucket["win_count"] += 1 if pnl > 0 else 0
    bucket["loss_count"] += 1 if pnl < 0 else 0
    return_pct = trade.get("return_pct")
    if return_pct is not None:
        bucket["return_pct_total"] += float(return_pct)
        bucket["return_pct_count"] += 1
    holding_days = trade.get("holding_days")
    if holding_days is not None:
        bucket["holding_days_total"] += float(holding_days)
        bucket["holding_days_count"] += 1


def _finalize_bucket(bucket: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(bucket)
    round_count = int(row.get("round_count") or 0)
    return_pct_count = int(row.get("return_pct_count") or 0)
    holding_days_count = int(row.get("holding_days_count") or 0)
    row["win_rate_pct"] = _round(row.get("win_count", 0) / round_count * 100.0, 2) if round_count else None
    row["avg_return_pct"] = _round(row.get("return_pct_total", 0.0) / return_pct_count, 2) if return_pct_count else None
    row["avg_holding_days"] = _round(row.get("holding_days_total", 0.0) / holding_days_count, 1) if holding_days_count else None
    fee_base = max(float(row.get("buy_amount_krw") or 0.0) + float(row.get("sell_amount_krw") or 0.0), 1.0)
    row["fee_bps"] = _round((float(row.get("commission_krw") or 0.0) + float(row.get("tax_krw") or 0.0)) / fee_base * 10000.0, 2)
    for key in ("return_pct_total", "return_pct_count", "holding_days_total", "holding_days_count"):
        row.pop(key, None)
    return {key: _round(value, 2) if isinstance(value, float) else value for key, value in row.items()}


def _open_lot_rows(open_lots: Mapping[str, list[OpenLot]]) -> list[dict[str, Any]]:
    rows = []
    for sym, lots in open_lots.items():
        quantity_sum = sum(lot.quantity for lot in lots)
        if quantity_sum <= 1e-9:
            continue
        rows.append(
            {
                "symbol": sym,
                "quantity": _round(quantity_sum, 6),
                "lot_count": len(lots),
                "portfolio_type": lots[0].portfolio_type if lots else "unclassified",
            }
        )
    return sorted(rows, key=lambda item: item["symbol"])


def _round_trade(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _round(value, 2) if isinstance(value, float) else value for key, value in row.items()}


def _round(value: Any, digits: int) -> Any:
    return round(value, digits) if isinstance(value, float) else value


def _to_krw(value: float, cur: str, usd_krw: float) -> float:
    return value * usd_krw if cur == "USD" else value
