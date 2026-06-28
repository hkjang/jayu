"""Processes Toss order history to calculate realized P&L, commissions, and matching."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class OrderHistoryIntelligence:
    """Parses order histories, matches buy/sell trades, and calculates realized P&L."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        self.orders_file = self.project_root / "state" / "toss_orders.json"

    def analyze_trades(self) -> dict[str, Any]:
        """Processes raw Toss orders, normalizes them, and calculates realized P&L (FIFO)."""
        if not self.orders_file.exists():
            return self._empty_analysis("Toss orders file not found")

        try:
            with open(self.orders_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            return self._empty_analysis(f"JSON parse error: {e}")

        # The payload might be a list of orders, or a dict with "orders" key
        orders = payload.get("orders", payload) if isinstance(payload, dict) else payload
        if not isinstance(orders, list):
            return self._empty_analysis("Invalid order history format")

        # Normalize and sort orders by time ascending
        # Toss order keys usually: symbol, orderType (BUY/SELL), executedQuantity, executedPrice, fee, etc.
        normalized_orders = []
        for o in orders:
            try:
                symbol = str(o.get("symbol") or o.get("ticker", "")).strip().upper()
                if not symbol:
                    continue
                
                side = str(o.get("orderType") or o.get("side") or "").strip().upper()
                if side not in {"BUY", "SELL"}:
                    continue
                
                qty = float(o.get("executedQuantity") or o.get("quantity") or 0.0)
                price = float(o.get("executedPrice") or o.get("price") or 0.0)
                fee = float(o.get("fee") or o.get("commission", 0.0))
                
                ordered_at_str = o.get("orderedAt") or o.get("date") or ""
                # Parse timestamp
                try:
                    dt = datetime.fromisoformat(ordered_at_str.replace("Z", "+00:00"))
                except Exception:
                    dt = datetime.now(UTC)
                
                normalized_orders.append({
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "fee": fee,
                    "dt": dt,
                    "ordered_at": ordered_at_str
                })
            except Exception:
                continue

        normalized_orders.sort(key=lambda x: x["dt"])

        # Perform FIFO matching by symbol
        inventory: dict[str, list[dict[str, Any]]] = {} # symbol -> list of buys: {"qty": q, "price": p, "fee": f}
        realized_pnl = 0.0
        total_commissions = 0.0
        trade_logs = []
        realized_details = []

        for o in normalized_orders:
            sym = o["symbol"]
            side = o["side"]
            qty = o["qty"]
            price = o["price"]
            fee = o["fee"]
            
            total_commissions += fee

            if side == "BUY":
                inventory.setdefault(sym, []).append({
                    "qty": qty,
                    "price": price,
                    "fee": fee
                })
            else:  # SELL
                # Match against buys in inventory (FIFO)
                remaining_qty = qty
                match_pnl = 0.0
                matched_buys = []
                
                buy_list = inventory.get(sym, [])
                while remaining_qty > 0 and buy_list:
                    buy = buy_list[0]
                    if buy["qty"] <= remaining_qty:
                        # Fully matched
                        match_qty = buy["qty"]
                        cost_basis = buy["price"] * match_qty
                        revenue = price * match_qty
                        pnl = revenue - cost_basis
                        
                        match_pnl += pnl
                        matched_buys.append({
                            "qty": match_qty,
                            "buy_price": buy["price"]
                        })
                        
                        remaining_qty -= buy["qty"]
                        buy_list.pop(0)
                    else:
                        # Partially matched
                        match_qty = remaining_qty
                        cost_basis = buy["price"] * match_qty
                        revenue = price * match_qty
                        pnl = revenue - cost_basis
                        
                        match_pnl += pnl
                        matched_buys.append({
                            "qty": match_qty,
                            "buy_price": buy["price"]
                        })
                        
                        buy["qty"] -= remaining_qty
                        remaining_qty = 0

                realized_pnl += match_pnl
                if matched_buys:
                    # Average buy price for this matched sell
                    total_buy_cost = sum(m["qty"] * m["buy_price"] for m in matched_buys)
                    avg_buy_price = total_buy_cost / qty if qty > 0 else 0.0
                    
                    realized_details.append({
                        "symbol": sym,
                        "sell_date": o["ordered_at"],
                        "quantity": qty,
                        "avg_buy_price": round(avg_buy_price, 2),
                        "sell_price": price,
                        "realized_pnl": round(match_pnl, 2),
                        "fee": fee
                    })

            trade_logs.append({
                "symbol": sym,
                "side": side,
                "quantity": qty,
                "price": price,
                "fee": fee,
                "date": o["ordered_at"]
            })

        # Calculate remaining average cost basis for open positions
        open_positions = []
        for sym, buys in inventory.items():
            total_qty = sum(b["qty"] for b in buys)
            if total_qty > 0:
                total_cost = sum(b["qty"] * b["price"] for b in buys)
                avg_price = total_cost / total_qty
                open_positions.append({
                    "symbol": sym,
                    "quantity": total_qty,
                    "average_cost": round(avg_price, 2)
                })

        return {
            "status": "success",
            "summary": {
                "total_orders_processed": len(normalized_orders),
                "total_realized_pnl_krw": round(realized_pnl, 0),
                "total_commissions_krw": round(total_commissions, 0),
                "active_positions_count": len(open_positions)
            },
            "open_positions": open_positions,
            "realized_details": realized_details,
            "trade_logs": trade_logs[-50:] # Limit logs to last 50 trades
        }

    def _empty_analysis(self, reason: str) -> dict[str, Any]:
        return {
            "status": "empty",
            "reason": reason,
            "summary": {
                "total_orders_processed": 0,
                "total_realized_pnl_krw": 0.0,
                "total_commissions_krw": 0.0,
                "active_positions_count": 0
            },
            "open_positions": [],
            "realized_details": [],
            "trade_logs": []
        }
