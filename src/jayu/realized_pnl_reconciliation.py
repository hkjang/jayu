from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .order_history_utils import (
    KRW_PER_USD_FALLBACK,
    commission,
    currency,
    filled_quantity,
    first_number,
    first_text,
    is_filled,
    order_rows,
    price,
    quantity as order_quantity,
    side,
    symbol,
    to_float,
)
from .trade_history_analytics import build_trade_history_analytics


QTY_TOLERANCE = 1e-4
COST_TOLERANCE_KRW = 1000.0


def reconcile_realized_pnl(
    orders_payload: Any,
    tax_lots: Any | None = None,
    holdings: Any | None = None,
    *,
    usd_krw: float = KRW_PER_USD_FALLBACK,
) -> dict[str, Any]:
    """Compare order-derived FIFO realized P/L with local lot and holding continuity.

    The current local tax-lot ledger primarily stores open lots, so realized P/L can
    only be directly compared when realized-pnl fields are present. Otherwise this
    report reconciles the open-position continuity around the order-derived FIFO
    result.
    """
    analytics = build_trade_history_analytics(orders_payload, usd_krw=usd_krw)
    order_positions = _open_positions_from_orders(orders_payload, usd_krw=usd_krw)
    tax_lot_positions, tax_lot_realized_pnl_krw = _positions_from_tax_lots(
        tax_lots,
        usd_krw=usd_krw,
    )
    holding_positions = _positions_from_holdings(holdings, usd_krw=usd_krw)

    symbols = sorted(set(order_positions) | set(tax_lot_positions) | set(holding_positions))
    discrepancies = []
    for sym in symbols:
        order_pos = order_positions.get(sym, _empty_position(sym))
        tax_pos = tax_lot_positions.get(sym, _empty_position(sym))
        holding_pos = holding_positions.get(sym, _empty_position(sym))
        issue_codes: list[str] = []
        qty_diffs = {
            "order_vs_tax_lot": _round_float(order_pos["quantity"] - tax_pos["quantity"], 6),
            "tax_lot_vs_holding": _round_float(tax_pos["quantity"] - holding_pos["quantity"], 6),
            "order_vs_holding": _round_float(order_pos["quantity"] - holding_pos["quantity"], 6),
        }
        cost_diff_order_vs_tax = _cost_diff(order_pos, tax_pos)
        cost_diff_tax_vs_holding = _cost_diff(tax_pos, holding_pos)

        if (order_positions or tax_lot_positions) and abs(qty_diffs["order_vs_tax_lot"]) > QTY_TOLERANCE:
            issue_codes.append("order_tax_lot_quantity_mismatch")
        if (tax_lot_positions or holding_positions) and abs(qty_diffs["tax_lot_vs_holding"]) > QTY_TOLERANCE:
            issue_codes.append("tax_lot_holding_quantity_mismatch")
        if order_positions and holding_positions and abs(qty_diffs["order_vs_holding"]) > QTY_TOLERANCE:
            issue_codes.append("order_holding_quantity_mismatch")
        if cost_diff_order_vs_tax is not None and abs(cost_diff_order_vs_tax) > COST_TOLERANCE_KRW:
            issue_codes.append("order_tax_lot_cost_basis_mismatch")
        if cost_diff_tax_vs_holding is not None and abs(cost_diff_tax_vs_holding) > COST_TOLERANCE_KRW:
            issue_codes.append("tax_lot_holding_cost_basis_mismatch")
        if order_pos.get("unmatched_sell_quantity", 0.0) > QTY_TOLERANCE:
            issue_codes.append("order_history_has_unmatched_sell")

        if issue_codes:
            max_qty_diff = max(abs(value) for value in qty_diffs.values())
            if order_positions and not tax_lot_positions:
                severity = "warning"
            else:
                severity = "failed" if max_qty_diff > 1.0 else "warning"
            discrepancies.append(
                {
                    "symbol": sym,
                    "severity": severity,
                    "issue_codes": issue_codes,
                    "order_quantity": _round_float(order_pos["quantity"], 6),
                    "tax_lot_quantity": _round_float(tax_pos["quantity"], 6),
                    "holding_quantity": _round_float(holding_pos["quantity"], 6),
                    "quantity_diff_order_vs_tax_lot": qty_diffs["order_vs_tax_lot"],
                    "quantity_diff_tax_lot_vs_holding": qty_diffs["tax_lot_vs_holding"],
                    "quantity_diff_order_vs_holding": qty_diffs["order_vs_holding"],
                    "order_cost_basis_krw": _round_optional(order_pos.get("cost_basis_krw"), 2),
                    "tax_lot_cost_basis_krw": _round_optional(tax_pos.get("cost_basis_krw"), 2),
                    "holding_cost_basis_krw": _round_optional(holding_pos.get("cost_basis_krw"), 2),
                    "cost_diff_order_vs_tax_lot_krw": _round_optional(cost_diff_order_vs_tax, 2),
                    "cost_diff_tax_lot_vs_holding_krw": _round_optional(cost_diff_tax_vs_holding, 2),
                    "unmatched_sell_quantity": _round_float(order_pos.get("unmatched_sell_quantity", 0.0), 6),
                }
            )

    order_realized = (analytics.get("summary") or {}).get("realized_pnl_krw")
    realized_diff = (
        float(order_realized) - tax_lot_realized_pnl_krw
        if order_realized is not None and tax_lot_realized_pnl_krw is not None
        else None
    )
    failed_count = sum(1 for item in discrepancies if item["severity"] == "failed")
    if not symbols and analytics.get("status") == "not_evaluated":
        status = "not_evaluated"
    elif failed_count:
        status = "failed"
    elif discrepancies or (order_positions and not tax_lot_positions):
        status = "warning"
    else:
        status = "success"

    return {
        "status": status,
        "summary": {
            "order_realized_pnl_krw": _round_optional(order_realized, 2),
            "tax_lot_realized_pnl_krw": _round_optional(tax_lot_realized_pnl_krw, 2),
            "realized_pnl_diff_krw": _round_optional(realized_diff, 2),
            "order_open_symbol_count": len(order_positions),
            "tax_lot_open_symbol_count": len(tax_lot_positions),
            "holding_symbol_count": len(holding_positions),
            "position_discrepancy_count": len(discrepancies),
            "failed_discrepancy_count": failed_count,
            "order_open_cost_basis_krw": _round_float(
                sum(float(item.get("cost_basis_krw") or 0.0) for item in order_positions.values()),
                2,
            ),
            "tax_lot_open_cost_basis_krw": _round_float(
                sum(float(item.get("cost_basis_krw") or 0.0) for item in tax_lot_positions.values()),
                2,
            ),
            "holding_cost_basis_krw": _round_float(
                sum(float(item.get("cost_basis_krw") or 0.0) for item in holding_positions.values()),
                2,
            ),
        },
        "position_discrepancies": discrepancies,
        "order_positions": [_round_position(item) for item in order_positions.values()],
        "tax_lot_positions": [_round_position(item) for item in tax_lot_positions.values()],
        "holding_positions": [_round_position(item) for item in holding_positions.values()],
        "realized_pnl": analytics.get("summary", {}),
        "source": "state/toss_orders.json · state/tax_lot_ledger.json · Toss holdings",
        "assumptions": {
            "usd_krw": usd_krw,
            "order_method": "filled orders are replayed by symbol-level FIFO",
            "tax_lot_method": "remaining_quantity from local tax lot ledger",
            "realized_pnl_note": "direct tax-lot realized P/L diff is available only when realized_pnl fields exist",
        },
    }


def _open_positions_from_orders(payload: Any, *, usd_krw: float) -> dict[str, dict[str, Any]]:
    rows = sorted(
        [row for row in order_rows(payload) if is_filled(row)],
        key=lambda row: str(row.get("orderedAt") or row.get("ordered_at") or ""),
    )
    lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    net_quantities: dict[str, float] = defaultdict(float)
    unmatched_sells: dict[str, float] = defaultdict(float)
    currencies: dict[str, str] = {}

    for row in rows:
        sym = symbol(row)
        if not sym:
            continue
        sd = side(row)
        qty = filled_quantity(row) or order_quantity(row) or 0.0
        px = price(row) or 0.0
        if qty <= 0 or px <= 0:
            continue
        cur = currency(row)
        currencies.setdefault(sym, cur)
        if sd == "BUY":
            net_quantities[sym] += qty
            cost_basis = _to_krw(qty * px, cur, usd_krw) + _to_krw(commission(row), cur, usd_krw)
            lots[sym].append({"quantity": qty, "cost_basis_krw": cost_basis})
        elif sd == "SELL":
            net_quantities[sym] -= qty
            remaining = qty
            while remaining > QTY_TOLERANCE and lots[sym]:
                lot = lots[sym][0]
                lot_qty = float(lot["quantity"])
                take = min(remaining, lot_qty)
                ratio = take / lot_qty if lot_qty else 0.0
                lot["quantity"] = lot_qty - take
                lot["cost_basis_krw"] = float(lot["cost_basis_krw"]) * (1.0 - ratio)
                remaining -= take
                if lot["quantity"] <= QTY_TOLERANCE:
                    lots[sym].pop(0)
            if remaining > QTY_TOLERANCE:
                unmatched_sells[sym] += remaining

    positions = {}
    for sym in sorted(set(net_quantities) | set(lots) | set(unmatched_sells)):
        qty = net_quantities.get(sym, 0.0)
        cost_basis = sum(float(lot.get("cost_basis_krw") or 0.0) for lot in lots.get(sym, []))
        unmatched_qty = unmatched_sells.get(sym, 0.0)
        if abs(qty) <= QTY_TOLERANCE and cost_basis <= COST_TOLERANCE_KRW and unmatched_qty <= QTY_TOLERANCE:
            continue
        positions[sym] = {
            "symbol": sym,
            "quantity": qty,
            "cost_basis_krw": cost_basis,
            "average_cost_krw": cost_basis / qty if qty > QTY_TOLERANCE else None,
            "currency": currencies.get(sym, ""),
            "unmatched_sell_quantity": unmatched_qty,
        }
    return positions


def _positions_from_tax_lots(payload: Any, *, usd_krw: float) -> tuple[dict[str, dict[str, Any]], float | None]:
    rows = _generic_rows(payload)
    positions: dict[str, dict[str, Any]] = {}
    realized_total = 0.0
    has_realized = False
    for lot in rows:
        realized_value = first_number(lot, "realized_pnl_krw", "realizedPnlKrw", "realized_pnl")
        if realized_value is not None:
            realized_total += realized_value
            has_realized = True
        sold_details = lot.get("sold_details")
        if isinstance(sold_details, Sequence) and not isinstance(sold_details, (str, bytes, bytearray)):
            for detail in sold_details:
                if isinstance(detail, Mapping):
                    detail_realized = first_number(detail, "realized_pnl_krw", "realized_pnl")
                    if detail_realized is not None:
                        realized_total += detail_realized
                        has_realized = True

        sym = first_text(lot, "ticker", "symbol", "stockCode", "stock_code").upper()
        if not sym:
            continue
        remaining_qty = first_number(lot, "remaining_quantity", "remainingQuantity", "remaining_qty")
        qty = remaining_qty if remaining_qty is not None else first_number(lot, "quantity", "qty")
        if qty is None or qty <= QTY_TOLERANCE:
            continue
        cur = first_text(lot, "currency", default="KRW").upper()
        unit_price = first_number(lot, "unit_price", "unitPrice", "average_price", "avg_price", "price")
        fx_rate = first_number(lot, "fx_rate", "fxRate", "exchange_rate", "usd_krw") or (
            usd_krw if cur == "USD" else 1.0
        )
        cost_basis = first_number(lot, "remaining_cost_basis_krw", "cost_basis_krw", "total_cost_krw")
        if cost_basis is None and unit_price is not None:
            original_qty = first_number(lot, "quantity", "original_quantity", "originalQuantity") or qty
            commission_krw = _to_krw(first_number(lot, "commission", "fee") or 0.0, cur, usd_krw)
            cost_basis = qty * unit_price * fx_rate
            if original_qty > 0:
                cost_basis += commission_krw * (qty / original_qty)
        bucket = positions.setdefault(
            sym,
            {"symbol": sym, "quantity": 0.0, "cost_basis_krw": 0.0, "currency": cur},
        )
        bucket["quantity"] += qty
        bucket["cost_basis_krw"] += cost_basis or 0.0
    for position in positions.values():
        qty = float(position["quantity"])
        position["average_cost_krw"] = position["cost_basis_krw"] / qty if qty > QTY_TOLERANCE else None
    return positions, realized_total if has_realized else None


def _positions_from_holdings(payload: Any, *, usd_krw: float) -> dict[str, dict[str, Any]]:
    rows = _generic_rows(payload)
    positions: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = first_text(row, "symbol", "ticker", "stockCode", "stock_code").upper()
        if not sym:
            continue
        qty = first_number(
            row,
            "quantity",
            "qty",
            "holding_quantity",
            "holdingQuantity",
            "balance_quantity",
            "balanceQuantity",
        )
        if qty is None or qty <= QTY_TOLERANCE:
            continue
        cur = first_text(row, "currency", default="KRW").upper()
        average_price = first_number(
            row,
            "average_price_krw",
            "avg_cost_krw",
            "avg_price_krw",
            "averagePriceKrw",
        )
        cost_basis = first_number(row, "cost_basis_krw", "purchase_amount_krw", "total_cost_krw")
        if average_price is None:
            average_native = first_number(
                row,
                "average_price",
                "averagePrice",
                "avg_cost",
                "avg_price",
                "average_purchase_price",
            )
            if average_native is not None:
                average_price = _to_krw(average_native, cur, usd_krw)
        if cost_basis is None and average_price is not None:
            cost_basis = qty * average_price
        market_value = first_number(row, "market_value_krw", "marketValueKrw", "evaluation_amount_krw")
        bucket = positions.setdefault(
            sym,
            {
                "symbol": sym,
                "quantity": 0.0,
                "cost_basis_krw": 0.0,
                "market_value_krw": 0.0,
                "currency": cur,
            },
        )
        bucket["quantity"] += qty
        bucket["cost_basis_krw"] += cost_basis or 0.0
        bucket["market_value_krw"] += market_value or 0.0
    for position in positions.values():
        qty = float(position["quantity"])
        position["average_cost_krw"] = position["cost_basis_krw"] / qty if qty > QTY_TOLERANCE else None
    return positions


def _generic_rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        for key in ("holdings", "lots", "positions", "items", "data", "result"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return [dict(item) for item in value if isinstance(item, Mapping)]
            if isinstance(value, Mapping):
                nested = _generic_rows(value)
                if nested:
                    return nested
        if any(key in payload for key in ("symbol", "ticker", "stockCode", "quantity")):
            return [dict(payload)]
        return []
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    return []


def _empty_position(sym: str) -> dict[str, Any]:
    return {
        "symbol": sym,
        "quantity": 0.0,
        "cost_basis_krw": None,
        "average_cost_krw": None,
        "market_value_krw": None,
        "currency": "",
    }


def _cost_diff(left: Mapping[str, Any], right: Mapping[str, Any]) -> float | None:
    left_cost = to_float(left.get("cost_basis_krw"))
    right_cost = to_float(right.get("cost_basis_krw"))
    if left_cost is None or right_cost is None:
        return None
    if left_cost == 0 and right_cost == 0:
        return 0.0
    return left_cost - right_cost


def _to_krw(value: float, cur: str, usd_krw: float) -> float:
    return value * usd_krw if cur.upper() == "USD" else value


def _round_float(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _round_optional(value: Any, digits: int = 2) -> float | None:
    num = to_float(value)
    return round(num, digits) if num is not None else None


def _round_position(position: Mapping[str, Any]) -> dict[str, Any]:
    rounded = dict(position)
    for key in (
        "quantity",
        "cost_basis_krw",
        "average_cost_krw",
        "market_value_krw",
        "unmatched_sell_quantity",
    ):
        if key in rounded:
            rounded[key] = _round_optional(rounded[key], 6 if key.endswith("quantity") else 2)
    return rounded
