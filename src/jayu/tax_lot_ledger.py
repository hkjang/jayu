from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from datetime import datetime

class TaxLotLedger:
    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = ledger_path

    def load_lots(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        try:
            with open(self.ledger_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_lots(self, lots: list[dict[str, Any]]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "w", encoding="utf-8") as f:
            json.dump(lots, f, indent=2, ensure_ascii=False)

    def add_buy(
        self,
        ticker: str,
        quantity: float,
        unit_price: float,
        fx_rate: float,
        currency: str = "USD",
        commission: float = 0.0,
        buy_date: str | None = None
    ) -> dict[str, Any]:
        lots = self.load_lots()
        date_str = buy_date or datetime.now().strftime("%Y%m%d")
        
        lot = {
            "lot_id": f"{ticker}_{date_str}_{len(lots) + 1}",
            "ticker": ticker.upper(),
            "buy_date": date_str,
            "quantity": quantity,
            "remaining_quantity": quantity,
            "unit_price": unit_price,
            "fx_rate": fx_rate,
            "currency": currency.upper(),
            "commission": commission
        }
        lots.append(lot)
        self.save_lots(lots)
        return lot

    def sell_fifo(
        self,
        ticker: str,
        sell_quantity: float,
        sell_price: float,
        sell_fx_rate: float,
        commission: float = 0.0,
        sell_date: str | None = None
    ) -> tuple[float, list[dict[str, Any]]]:
        """FIFO 방식으로 주식을 매도 처리하고 실현 손익을 계산합니다."""
        lots = self.load_lots()
        ticker = ticker.upper()
        
        remaining_to_sell = sell_quantity
        realized_pnl = 0.0
        sold_details = []
        
        date_str = sell_date or datetime.now().strftime("%Y%m%d")
        
        for lot in lots:
            if lot["ticker"] != ticker or lot["remaining_quantity"] <= 0:
                continue
                
            qty_to_take = min(lot["remaining_quantity"], remaining_to_sell)
            
            # Acquisition cost (converted to local currency KRW)
            buy_cost_krw = qty_to_take * lot["unit_price"] * lot["fx_rate"]
            # Sell value (converted to local currency KRW)
            sell_val_krw = qty_to_take * sell_price * sell_fx_rate
            
            # Allocation of buy commission
            pro_rata_buy_comm = (qty_to_take / lot["quantity"]) * lot["commission"]
            
            # Realized P&L for this chunk
            chunk_pnl = (sell_val_krw - buy_cost_krw) - pro_rata_buy_comm
            realized_pnl += chunk_pnl
            
            # Update lot
            lot["remaining_quantity"] -= qty_to_take
            remaining_to_sell -= qty_to_take
            
            # Record sold detail
            sold_details.append({
                "lot_id": lot["lot_id"],
                "quantity_sold": qty_to_take,
                "buy_date": lot["buy_date"],
                "sell_date": date_str,
                "realized_pnl": chunk_pnl
            })
            
            if remaining_to_sell <= 0:
                break
                
        # Deduct sell commission from total realized pnl
        realized_pnl -= commission
        
        # Save updated lots back
        self.save_lots(lots)
        return round(realized_pnl, 2), sold_details

    def reconcile_with_toss(self, toss_holdings: list[dict[str, Any]]) -> dict[str, Any]:
        """로컬 Tax Lot 원장의 잔고와 실제 Toss OpenAPI 잔고를 대조합니다."""
        lots = self.load_lots()
        
        # 1. Aggregate local active lots
        local_holdings: dict[str, dict[str, Any]] = {}
        for lot in lots:
            qty = lot.get("remaining_quantity", 0.0)
            if qty <= 0:
                continue
            ticker = lot["ticker"]
            if ticker not in local_holdings:
                local_holdings[ticker] = {"ticker": ticker, "quantity": 0.0, "total_cost_krw": 0.0}
            local_holdings[ticker]["quantity"] += qty
            local_holdings[ticker]["total_cost_krw"] += qty * lot["unit_price"] * lot["fx_rate"]
            
        for h in local_holdings.values():
            h["avg_price_krw"] = round(h["total_cost_krw"] / h["quantity"], 2) if h["quantity"] > 0 else 0.0
            
        # 2. Compare against Toss holdings
        discrepancies = []
        reconciled = True
        
        # Keep track of matched tickers
        matched_tickers = set()
        
        for toss in toss_holdings:
            ticker = toss.get("ticker", toss.get("symbol", "")).upper()
            if not ticker:
                continue
            matched_tickers.add(ticker)
            
            toss_qty = float(toss.get("quantity", toss.get("qty", 0.0)))
            toss_avg_cost = float(toss.get("avg_cost", toss.get("avg_price", 0.0)))
            
            local = local_holdings.get(ticker, {"quantity": 0.0, "avg_price_krw": 0.0})
            qty_diff = toss_qty - local["quantity"]
            
            # We allow small float tolerances
            if abs(qty_diff) > 0.0001:
                reconciled = False
                discrepancies.append({
                    "ticker": ticker,
                    "ledger_qty": local["quantity"],
                    "toss_qty": toss_qty,
                    "qty_diff": round(qty_diff, 4),
                    "type": "quantity_discrepancy",
                    "severity": "blocked" if abs(qty_diff) > 1.0 else "warning"
                })
                
        # 3. Check for tickers in ledger that are missing in Toss
        for ticker, local in local_holdings.items():
            if ticker not in matched_tickers:
                reconciled = False
                discrepancies.append({
                    "ticker": ticker,
                    "ledger_qty": local["quantity"],
                    "toss_qty": 0.0,
                    "qty_diff": -local["quantity"],
                    "type": "missing_in_toss",
                    "severity": "blocked"
                })
                
        return {
            "reconciled": reconciled,
            "discrepancy_count": len(discrepancies),
            "discrepancies": discrepancies,
            "local_holdings": list(local_holdings.values())
        }
