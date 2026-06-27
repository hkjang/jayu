import csv
import json
from pathlib import Path
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
from .toss_security_master import TossSecurityMaster

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
    security_master: dict[str, dict[str, Any]] | None = None,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    # Load security master if not provided
    if security_master is None:
        if project_root:
            security_master = TossSecurityMaster(project_root).get_security_master()
        else:
            security_master = {}

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
    by_market: dict[str, dict[str, Any]] = defaultdict(_market_bucket)
    by_currency_bucket: dict[str, dict[str, Any]] = defaultdict(_currency_bucket)
    by_security_type: dict[str, dict[str, Any]] = defaultdict(_security_type_bucket)

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
        
        # Resolve metadata
        sec_info = security_master.get(sym) or {}
        market = str(sec_info.get("market") or "UNKNOWN").upper()
        sec_type = str(sec_info.get("security_type") or "STOCK").upper()
        leverage = float(sec_info.get("leverage_factor") or 1.0)
        
        if leverage > 1.0:
            sec_type_label = f"LEVERAGED {sec_type} ({leverage}x)"
        else:
            sec_type_label = sec_type

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
            "market": market,
            "security_type": sec_type_label,
        }
        order_features.append(feature)

        buckets = (
            by_symbol[sym],
            by_month[month],
            by_portfolio_type[ptype],
            by_market[market],
            by_currency_bucket[cur],
            by_security_type[sec_type_label]
        )
        for bucket in buckets:
            _add_order(bucket, sd, amount, comm_krw, tax_krw)
            
        by_symbol[sym]["symbol"] = sym
        by_symbol[sym]["portfolio_type"] = ptype
        by_month[month]["period"] = month
        by_portfolio_type[ptype]["portfolio_type"] = ptype
        by_market[market]["market"] = market
        by_currency_bucket[cur]["currency"] = cur
        by_security_type[sec_type_label]["security_type"] = sec_type_label

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
            trade_buckets = (
                by_symbol[trade["symbol"]],
                by_month[month],
                by_portfolio_type[trade["portfolio_type"]],
                by_market[market],
                by_currency_bucket[cur],
                by_security_type[sec_type_label]
            )
            for bucket in trade_buckets:
                _add_round(bucket, trade)

    by_symbol_rows = [_finalize_bucket(item) for item in by_symbol.values()]
    by_month_rows = [_finalize_bucket(item) for item in by_month.values()]
    by_portfolio_rows = [_finalize_bucket(item) for item in by_portfolio_type.values()]
    by_market_rows = [_finalize_bucket(item) for item in by_market.values()]
    by_currency_rows = [_finalize_bucket(item) for item in by_currency_bucket.values()]
    by_security_type_rows = [_finalize_bucket(item) for item in by_security_type.values()]
    
    summary = _finalize_bucket(_summary_bucket(order_features, trade_rounds))

    return {
        "status": "success" if order_features else "not_evaluated",
        "summary": summary,
        "orders": order_features,
        "trade_rounds": [_round_trade(item) for item in trade_rounds],
        "by_symbol": sorted(by_symbol_rows, key=lambda item: abs(item.get("realized_pnl_krw") or 0.0), reverse=True),
        "by_month": sorted(by_month_rows, key=lambda item: item.get("period") or "")[-72:],
        "by_portfolio_type": sorted(by_portfolio_rows, key=lambda item: item.get("portfolio_type") or ""),
        "by_market": sorted(by_market_rows, key=lambda item: abs(item.get("realized_pnl_krw") or 0.0), reverse=True),
        "by_currency": sorted(by_currency_rows, key=lambda item: abs(item.get("realized_pnl_krw") or 0.0), reverse=True),
        "by_security_type": sorted(by_security_type_rows, key=lambda item: abs(item.get("realized_pnl_krw") or 0.0), reverse=True),
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
        if direct:
            if direct.get("type"):
                return direct["type"]
            pts = direct.get("portfolio_types") or direct.get("portfolio_type")
            if pts:
                if isinstance(pts, list) and pts:
                    return pts[0]
                return str(pts)
    return "unclassified"

def _symbol_bucket() -> dict[str, Any]:
    return {"symbol": "", "portfolio_type": "", **_base_bucket()}

def _period_bucket() -> dict[str, Any]:
    return {"period": "", **_base_bucket()}

def _portfolio_bucket() -> dict[str, Any]:
    return {"portfolio_type": "", **_base_bucket()}

def _market_bucket() -> dict[str, Any]:
    return {"market": "", **_base_bucket()}

def _currency_bucket() -> dict[str, Any]:
    return {"currency": "", **_base_bucket()}

def _security_type_bucket() -> dict[str, Any]:
    return {"security_type": "", **_base_bucket()}

def _base_bucket() -> dict[str, Any]:
    return {
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
        "total_holding_days": 0.0,
        "holding_days_counted": 0,
        "total_return_pct": 0.0,
        "return_pct_counted": 0,
    }

def _summary_bucket(orders: list[dict[str, Any]], rounds: list[dict[str, Any]]) -> dict[str, Any]:
    b = _base_bucket()
    for o in orders:
        _add_order(b, o["side"], o["amount_krw"], o["commission_krw"], o["tax_krw"])
    for r in rounds:
        _add_round(b, r)
    b["period"] = "all"
    return b

def _add_order(b: dict[str, Any], side_val: str, amt: float, comm: float, tax_val: float):
    b["trade_count"] += 1
    b["commission_krw"] += comm
    b["tax_krw"] += tax_val
    if side_val == "BUY":
        b["buy_count"] += 1
        b["buy_amount_krw"] += amt
    elif side_val == "SELL":
        b["sell_count"] += 1
        b["sell_amount_krw"] += amt

def _add_round(b: dict[str, Any], r: dict[str, Any]):
    b["round_count"] += 1
    pnl = r["realized_pnl_krw"]
    ret = r["return_pct"]
    days = r["holding_days"]
    b["realized_pnl_krw"] += pnl
    if pnl > 1e-2:
        b["win_count"] += 1
    else:
        b["loss_count"] += 1
    if ret is not None:
        b["total_return_pct"] += ret
        b["return_pct_counted"] += 1
    if days is not None:
        b["total_holding_days"] += days
        b["holding_days_counted"] += 1

def _finalize_bucket(b: dict[str, Any]) -> dict[str, Any]:
    rounds = b["round_count"]
    wins = b["win_count"]
    losses = b["loss_count"]
    total_rounds = wins + losses
    b["win_rate_pct"] = (wins / total_rounds * 100.0) if total_rounds > 0 else None
    
    ret_cnt = b["return_pct_counted"]
    b["avg_return_pct"] = (b["total_return_pct"] / ret_cnt) if ret_cnt > 0 else None
    
    days_cnt = b["holding_days_counted"]
    b["avg_holding_days"] = (b["total_holding_days"] / days_cnt) if days_cnt > 0 else None
    
    total_vol = b["buy_amount_krw"] + b["sell_amount_krw"]
    total_costs = b["commission_krw"] + b["tax_krw"]
    b["fee_bps"] = (total_costs / total_vol * 10000.0) if total_vol > 0 else 0.0
    
    # Remove aggregation helpers
    for k in [
        "total_holding_days",
        "holding_days_counted",
        "total_return_pct",
        "return_pct_counted",
    ]:
        b.pop(k, None)
        
    # Round floats
    for k in ["buy_amount_krw", "sell_amount_krw", "commission_krw", "tax_krw", "realized_pnl_krw"]:
        b[k] = _round(b[k], 2)
    if b["win_rate_pct"] is not None:
        b["win_rate_pct"] = _round(b["win_rate_pct"], 2)
    if b["avg_return_pct"] is not None:
        b["avg_return_pct"] = _round(b["avg_return_pct"], 2)
    if b["avg_holding_days"] is not None:
        b["avg_holding_days"] = _round(b["avg_holding_days"], 1)
    b["fee_bps"] = _round(b["fee_bps"], 2)
    return b

def _open_lot_rows(open_lots: dict[str, list[OpenLot]]) -> list[dict[str, Any]]:
    res = []
    for sym, lots in open_lots.items():
        if not lots:
            continue
        total_qty = sum(lot.quantity for lot in lots)
        if total_qty > 1e-9:
            res.append(
                {
                    "symbol": sym,
                    "quantity": _round(total_qty, 6),
                    "lot_count": len(lots),
                    "portfolio_type": lots[0].portfolio_type,
                }
            )
    return sorted(res, key=lambda x: x["quantity"], reverse=True)

def _round_trade(trade: dict[str, Any]) -> dict[str, Any]:
    trade["quantity"] = _round(trade["quantity"], 6)
    trade["buy_value_krw"] = _round(trade["buy_value_krw"], 2)
    trade["sell_value_krw"] = _round(trade["sell_value_krw"], 2)
    trade["fees_krw"] = _round(trade["fees_krw"], 2)
    trade["realized_pnl_krw"] = _round(trade["realized_pnl_krw"], 2)
    if trade["return_pct"] is not None:
        trade["return_pct"] = _round(trade["return_pct"], 2)
    return trade

def _to_krw(val: float, cur: str, usd_krw: float) -> float:
    return val * usd_krw if cur.upper() == "USD" else val

def _round(val: float | None, digits: int) -> float | None:
    return round(val, digits) if val is not None else None
