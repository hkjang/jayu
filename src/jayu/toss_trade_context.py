import csv
import json
from pathlib import Path
from typing import Any
from .toss_security_master import TossSecurityMaster
from .toss_order_feature_store import build_toss_order_feature_store

class TossTradeContext:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)
        self.portfolio_file = self.project_root / "toss_portfolio.csv"
        self.orders_file = self.project_root / "state" / "toss_orders.json"
        self.signals_file = self.project_root / "state" / "today_signals.json"

    def build_context(self, symbol: str, client: Any = None) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        
        # 1. Metadata
        master = self.security_master.get_security_master(client)
        meta = master.get(symbol) or {
            "symbol": symbol,
            "name": symbol,
            "english_name": symbol,
            "market": "UNKNOWN",
            "currency": "USD",
            "security_type": "STOCK",
            "leverage_factor": 1.0,
            "warnings": {
                "symbol": symbol,
                "marketWarning": "NONE",
                "administrative": False,
                "delistingCaution": False,
                "tradingSuspended": False,
            },
            "is_tradable": True
        }

        # 2. Risk evaluation
        warnings = meta.get("warnings") or {}
        m_warning = str(warnings.get("marketWarning") or "NONE").upper()
        admin = bool(warnings.get("administrative", False))
        delist = bool(warnings.get("delistingCaution", False))
        suspended = bool(warnings.get("tradingSuspended", False))
        leverage = float(meta.get("leverage_factor") or 1.0)
        
        reasons = []
        grade = "normal"
        autotrade_allowed = True
        
        if suspended:
            reasons.append("거래정지 종목")
            grade = "blocked"
            autotrade_allowed = False
        elif admin:
            reasons.append("관리종목 지정")
            grade = "blocked"
            autotrade_allowed = False
        elif delist:
            reasons.append("상장폐지 우려")
            grade = "blocked"
            autotrade_allowed = False
        elif m_warning in {"INVESTMENT_DANGER", "DANGER"}:
            reasons.append("투자위험 종목")
            grade = "blocked"
            autotrade_allowed = False
        elif m_warning in {"INVESTMENT_WARNING", "WARNING"}:
            reasons.append("투자경고 종목")
            grade = "high_risk"
            autotrade_allowed = True  # Allowed but high risk
        elif m_warning in {"INVESTMENT_CAUTION", "CAUTION"}:
            reasons.append("투자주의 종목")
            grade = "caution"
        elif leverage > 1.5:
            reasons.append(f"{leverage}x 레버리지 상품")
            grade = "caution"

        risk = {
            "symbol": symbol,
            "grade": grade,
            "reasons": reasons,
            "autotrade_allowed": autotrade_allowed
        }

        # 3. Holding status
        holding = {
            "qty": 0.0,
            "krw_value": 0.0,
            "pl_krw": 0.0,
            "pl_pct": 0.0,
            "avg_price": 0.0,
            "sector": "-",
            "category": "-"
        }
        if self.portfolio_file.exists():
            try:
                with open(self.portfolio_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row_sym = (row.get("Symbol") or row.get("symbol") or "").strip().upper()
                        if row_sym == symbol or row_sym.split(".")[0] == symbol:
                            holding = {
                                "qty": float(row.get("Qty") or row.get("qty") or 0.0),
                                "krw_value": float(row.get("KRW value") or row.get("krw_value") or 0.0),
                                "pl_krw": float(row.get("P/L KRW") or row.get("pl_krw") or 0.0),
                                "pl_pct": float(row.get("P/L %") or row.get("pl_pct") or 0.0),
                                "avg_price": float(row.get("Buy Price") or row.get("buy_price") or 0.0),
                                "sector": row.get("Sector") or row.get("sector") or "-",
                                "category": row.get("Category") or row.get("category") or "-"
                            }
                            break
            except Exception:
                pass

        # 4. Orders & Performance
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
                features = build_toss_order_feature_store(orders_payload, security_master=master)
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

        # 5. Active Signal
        sig_info = {}
        if self.signals_file.exists():
            try:
                with open(self.signals_file, "r", encoding="utf-8") as f:
                    signals_data = json.load(f)
                # Could be list or dict
                if isinstance(signals_data, list):
                    for s in signals_data:
                        if str(s.get("ticker")).upper() == symbol:
                            sig_info = s
                            break
                elif isinstance(signals_data, dict):
                    sig_info = signals_data.get(symbol) or {}
            except Exception:
                pass

        return {
            "symbol": symbol,
            "metadata": meta,
            "risk": risk,
            "holding": holding,
            "orders": orders_list,
            "performance": performance,
            "signal": sig_info
        }
