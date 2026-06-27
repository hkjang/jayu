from typing import Any
from pathlib import Path
import csv
import json
from .toss_security_master import TossSecurityMaster
from .security_risk_profile import SecurityRiskProfiler
from .toss_order_feature_store import build_toss_order_feature_store

class TossTradeContextBuilder:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)
        self.portfolio_file = self.project_root / "toss_portfolio.csv"
        self.orders_file = self.project_root / "state" / "toss_orders.json"

    def build_context(self, symbol: str, client: Any = None) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        
        # 1. Load Security Master & Risk Profile
        master = self.security_master.get_security_master(client)
        sec_info = master.get(symbol)
        
        if sec_info:
            risk = SecurityRiskProfiler.evaluate_risk(sec_info)
        else:
            sec_info = {
                "symbol": symbol,
                "name": symbol,
                "english_name": symbol,
                "market": "UNKNOWN",
                "currency": "KRW",
                "security_type": "STOCK",
                "leverage_factor": 1.0,
                "is_tradable": True,
                "warnings": {}
            }
            risk = {
                "symbol": symbol,
                "grade": "caution",
                "reasons": ["Toss 종목 마스터에 없음"],
                "autotrade_allowed": True
            }

        # 2. Load Holdings from toss_portfolio.csv
        holding_info = {}
        if self.portfolio_file.exists():
            try:
                with open(self.portfolio_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sym = (row.get("Symbol") or row.get("symbol") or "").strip().upper()
                        if sym == symbol:
                            holding_info = {
                                "qty": float(row.get("Qty") or row.get("qty") or 0.0),
                                "krw_value": float(row.get("KRW value") or row.get("krw_value") or 0.0),
                                "pl_krw": float(row.get("P/L KRW") or row.get("pl_krw") or 0.0),
                                "pl_pct": float(row.get("P/L %") or row.get("pl_pct") or 0.0),
                                "avg_price": float(row.get("Buy Price") or row.get("buy_price") or row.get("Purchase Price") or row.get("purchase_price") or 0.0),
                                "sector": row.get("Sector") or row.get("sector") or "-",
                                "category": row.get("Category") or row.get("category") or "-",
                            }
                            break
            except Exception:
                pass

        # 3. Load Past Orders & Performance from feature store
        orders_list = []
        performance = {
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "realized_pnl_krw": 0.0,
            "avg_holding_days": 0.0,
            "total_fees_krw": 0.0
        }
        
        if self.orders_file.exists():
            try:
                with open(self.orders_file, "r", encoding="utf-8") as f:
                    orders_payload = json.load(f)
                
                features = build_toss_order_feature_store(orders_payload)
                
                # Filter orders for this symbol
                orders_list = [o for o in features.get("orders", []) if o.get("symbol") == symbol]
                
                # Find symbol summary
                for s_stat in features.get("by_symbol", []):
                    if s_stat.get("symbol") == symbol:
                        total_trades = s_stat.get("buy_count", 0) + s_stat.get("sell_count", 0)
                        win_rate = 0.0
                        if s_stat.get("win_count", 0) + s_stat.get("loss_count", 0) > 0:
                            win_rate = (s_stat.get("win_count", 0) / (s_stat.get("win_count", 0) + s_stat.get("loss_count", 0))) * 100.0
                        
                        performance = {
                            "total_trades": total_trades,
                            "win_rate_pct": round(win_rate, 2),
                            "realized_pnl_krw": s_stat.get("realized_pnl_krw") or 0.0,
                            "avg_holding_days": round(s_stat.get("avg_holding_days") or 0.0, 1),
                            "total_fees_krw": s_stat.get("fees_krw") or 0.0
                        }
                        break
            except Exception:
                pass

        return {
            "symbol": symbol,
            "metadata": sec_info,
            "risk": risk,
            "holding": holding_info,
            "orders": orders_list[-10:],  # Return last 10 orders
            "performance": performance
        }
