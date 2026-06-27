from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .order_history_utils import (
    KRW_PER_USD_FALLBACK,
    amount_krw,
    commission,
    currency,
    filled_quantity,
    is_filled,
    order_amount,
    order_id,
    order_rows,
    parse_ordered_at,
    price,
    side,
    symbol,
    tax,
)


@dataclass
class Lot:
    symbol: str
    currency: str
    quantity: float
    unit_price: float
    ordered_at: Any
    commission_per_share: float


def build_trade_history_analytics(
    orders_payload: Any,
    *,
    usd_krw: float = KRW_PER_USD_FALLBACK,
) -> dict[str, Any]:
    orders = sorted(
        [row for row in order_rows(orders_payload) if is_filled(row)],
        key=lambda row: str(row.get("orderedAt") or row.get("ordered_at") or ""),
    )
    summary = {
        "trade_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "total_buy_krw": 0.0,
        "total_sell_krw": 0.0,
        "realized_pnl_krw": 0.0,
        "commission_krw": 0.0,
        "tax_krw": 0.0,
        "win_rate_pct": None,
        "avg_holding_days": None,
    }
    by_year: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_month: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_symbol: dict[str, dict[str, Any]] = defaultdict(_symbol_bucket)
    lots: dict[str, list[Lot]] = defaultdict(list)
    matched_trades: list[dict[str, Any]] = []

    for row in orders:
        sym = symbol(row)
        if not sym:
            continue
        sd = side(row)
        cur = currency(row)
        dt = parse_ordered_at(row.get("orderedAt") or row.get("ordered_at"))
        year = str(dt.year) if dt else "UNKNOWN"
        month = f"{dt.year:04d}-{dt.month:02d}" if dt else "UNKNOWN"
        qty = filled_quantity(row)
        px = price(row)
        amount = order_amount(row)
        amount_in_krw = amount_krw(row, usd_krw=usd_krw)
        if qty is None or qty <= 0 or px is None or px <= 0 or amount is None or amount_in_krw is None:
            continue
        cost_krw = _to_krw(commission(row), cur, usd_krw) + _to_krw(tax(row), cur, usd_krw)

        summary["trade_count"] += 1
        summary["commission_krw"] += _to_krw(commission(row), cur, usd_krw)
        summary["tax_krw"] += _to_krw(tax(row), cur, usd_krw)
        for bucket in (by_year[year], by_month[month]):
            bucket["trade_count"] += 1
            bucket["commission_krw"] += _to_krw(commission(row), cur, usd_krw)
            bucket["tax_krw"] += _to_krw(tax(row), cur, usd_krw)
        sym_bucket = by_symbol[sym]
        sym_bucket["symbol"] = sym
        sym_bucket["trade_count"] += 1
        sym_bucket["commission_krw"] += _to_krw(commission(row), cur, usd_krw)
        sym_bucket["tax_krw"] += _to_krw(tax(row), cur, usd_krw)

        if sd == "BUY":
            summary["buy_count"] += 1
            summary["total_buy_krw"] += amount_in_krw
            _add_amount(by_year[year], "buy", amount_in_krw)
            _add_amount(by_month[month], "buy", amount_in_krw)
            _add_amount(sym_bucket, "buy", amount_in_krw)
            lots[sym].append(
                Lot(
                    symbol=sym,
                    currency=cur,
                    quantity=qty,
                    unit_price=px,
                    ordered_at=dt,
                    commission_per_share=(commission(row) / qty) if qty else 0.0,
                )
            )
        elif sd == "SELL":
            summary["sell_count"] += 1
            summary["total_sell_krw"] += amount_in_krw
            _add_amount(by_year[year], "sell", amount_in_krw)
            _add_amount(by_month[month], "sell", amount_in_krw)
            _add_amount(sym_bucket, "sell", amount_in_krw)
            realized = _match_sell(
                lots[sym],
                row=row,
                sell_quantity=qty,
                sell_price=px,
                sell_cost_krw=cost_krw,
                usd_krw=usd_krw,
            )
            if realized:
                matched_trades.extend(realized)
                pnl = sum(item["realized_pnl_krw"] for item in realized)
                holding_days = [item["holding_days"] for item in realized if item["holding_days"] is not None]
                summary["realized_pnl_krw"] += pnl
                by_year[year]["realized_pnl_krw"] += pnl
                by_month[month]["realized_pnl_krw"] += pnl
                sym_bucket["realized_pnl_krw"] += pnl
                if holding_days:
                    sym_bucket["holding_days_total"] += sum(holding_days)
                    sym_bucket["holding_match_count"] += len(holding_days)

    wins = [trade for trade in matched_trades if trade["realized_pnl_krw"] > 0]
    holding_days_all = [trade["holding_days"] for trade in matched_trades if trade["holding_days"] is not None]
    if matched_trades:
        summary["win_rate_pct"] = round(len(wins) / len(matched_trades) * 100, 2)
    if holding_days_all:
        summary["avg_holding_days"] = round(sum(holding_days_all) / len(holding_days_all), 1)

    symbol_rows = []
    for row in by_symbol.values():
        row = dict(row)
        if row["holding_match_count"]:
            row["avg_holding_days"] = round(row["holding_days_total"] / row["holding_match_count"], 1)
        row.pop("holding_days_total", None)
        row.pop("holding_match_count", None)
        symbol_rows.append(_round_bucket(row))

    top_winners = sorted(matched_trades, key=lambda item: item["realized_pnl_krw"], reverse=True)[:5]
    top_losers = sorted(matched_trades, key=lambda item: item["realized_pnl_krw"])[:5]
    return {
        "status": "success" if summary["trade_count"] else "not_evaluated",
        "summary": _round_bucket(summary),
        "by_year": [_round_bucket({"period": key, **value}) for key, value in sorted(by_year.items())],
        "by_month": [_round_bucket({"period": key, **value}) for key, value in sorted(by_month.items())[-24:]],
        "by_symbol": sorted(symbol_rows, key=lambda item: abs(item.get("realized_pnl_krw", 0.0)), reverse=True),
        "top_winners": [_round_bucket(item) for item in top_winners],
        "top_losers": [_round_bucket(item) for item in top_losers],
        "source": "state/toss_orders.json · Toss Order History getOrders · FIFO approximation",
        "assumptions": {
            "usd_krw": usd_krw,
            "realized_pnl_method": "symbol-level FIFO using averageFilledPrice/filledAmount",
            "costs": "commission and tax subtracted when available",
        },
    }


def _bucket() -> dict[str, Any]:
    return {
        "trade_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "buy_amount_krw": 0.0,
        "sell_amount_krw": 0.0,
        "realized_pnl_krw": 0.0,
        "commission_krw": 0.0,
        "tax_krw": 0.0,
    }


def _symbol_bucket() -> dict[str, Any]:
    bucket = _bucket()
    bucket.update({"symbol": "", "holding_days_total": 0.0, "holding_match_count": 0})
    return bucket


def _add_amount(bucket: dict[str, Any], kind: str, amount: float) -> None:
    bucket[f"{kind}_count"] += 1
    bucket[f"{kind}_amount_krw"] += amount


def _match_sell(
    lots: list[Lot],
    *,
    row: dict[str, Any],
    sell_quantity: float,
    sell_price: float,
    sell_cost_krw: float,
    usd_krw: float,
) -> list[dict[str, Any]]:
    remaining = sell_quantity
    realized = []
    sell_dt = parse_ordered_at(row.get("orderedAt") or row.get("ordered_at"))
    sell_cur = currency(row)
    while remaining > 1e-9 and lots:
        lot = lots[0]
        matched_qty = min(remaining, lot.quantity)
        buy_value = matched_qty * lot.unit_price
        sell_value = matched_qty * sell_price
        gross = _to_krw(sell_value - buy_value, sell_cur, usd_krw)
        sell_cost_alloc = sell_cost_krw * (matched_qty / sell_quantity) if sell_quantity else 0.0
        buy_cost_alloc = _to_krw(lot.commission_per_share * matched_qty, lot.currency, usd_krw)
        holding_days = (sell_dt - lot.ordered_at).days if sell_dt and lot.ordered_at else None
        realized.append(
            {
                "order_id": order_id(row),
                "symbol": lot.symbol,
                "quantity": matched_qty,
                "sell_price": sell_price,
                "buy_price": lot.unit_price,
                "realized_pnl_krw": gross - sell_cost_alloc - buy_cost_alloc,
                "holding_days": holding_days,
                "sold_at": sell_dt.isoformat() if sell_dt else None,
            }
        )
        lot.quantity -= matched_qty
        remaining -= matched_qty
        if lot.quantity <= 1e-9:
            lots.pop(0)
    return realized


def _to_krw(value: float, cur: str, usd_krw: float) -> float:
    return value * usd_krw if cur == "USD" else value


def _round_bucket(row: dict[str, Any]) -> dict[str, Any]:
    rounded = {}
    for key, value in row.items():
        rounded[key] = round(value, 2) if isinstance(value, float) else value
    return rounded
