import csv
from typing import Any
from pathlib import Path
from collections import defaultdict
from .toss_security_master import TossSecurityMaster

class PortfolioSecurityExposure:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)
        self.portfolio_file = self.project_root / "toss_portfolio.csv"

    def calculate_exposure(self) -> dict[str, Any]:
        """
        Calculates exposure metrics by joining holdings with security master metadata.
        Groups by market, currency, security type, leverage factor, sector, and warning status.
        """
        master = self.security_master.get_security_master()
        
        holdings = []
        total_value_krw = 0.0
        
        if self.portfolio_file.exists():
            try:
                with open(self.portfolio_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sym = (row.get("Symbol") or row.get("symbol") or "").strip().upper()
                        qty = float(row.get("Qty") or row.get("qty") or 0.0)
                        val_krw = float(row.get("KRW value") or row.get("krw_value") or 0.0)
                        if qty > 0:
                            holdings.append({
                                "symbol": sym,
                                "qty": qty,
                                "krw_value": val_krw,
                                "sector": row.get("Sector") or row.get("sector") or "-"
                            })
                            total_value_krw += val_krw
            except Exception:
                pass

        # Grouping containers
        by_type = defaultdict(float)
        by_market = defaultdict(float)
        by_currency = defaultdict(float)
        by_leverage = defaultdict(float)
        by_sector = defaultdict(float)
        by_warning_status = defaultdict(float)
        
        for h in holdings:
            sym = h["symbol"]
            val = h["krw_value"]
            sec = master.get(sym) or {}
            
            # 1. Type
            sec_type = str(sec.get("security_type") or "STOCK").upper()
            leverage = float(sec.get("leverage_factor") or 1.0)
            if leverage > 1.0:
                type_label = f"LEVERAGED {sec_type} ({leverage}x)"
            else:
                type_label = sec_type
            by_type[type_label] += val
            
            # 2. Market
            market = str(sec.get("market") or "UNKNOWN").upper()
            by_market[market] += val
            
            # 3. Currency
            currency = str(sec.get("currency") or "KRW").upper()
            by_currency[currency] += val
            
            # 4. Leverage
            leverage_label = f"{leverage}x"
            by_leverage[leverage_label] += val
            
            # 5. Sector
            sector = h["sector"] or sec.get("sector") or "Unclassified"
            by_sector[sector] += val
            
            # 6. Warning status
            warnings = sec.get("warnings") or {}
            m_warning = str(warnings.get("marketWarning") or "NONE").upper()
            if m_warning != "NONE":
                warning_label = f"WARNED ({m_warning})"
            elif warnings.get("tradingSuspended"):
                warning_label = "SUSPENDED"
            elif warnings.get("administrative"):
                warning_label = "ADMINISTRATIVE"
            elif warnings.get("delistingCaution"):
                warning_label = "DELISTING_CAUTION"
            else:
                warning_label = "NORMAL"
            by_warning_status[warning_label] += val

        # Convert to percentages
        def to_pct_list(grouped_dict):
            lst = []
            for k, v in grouped_dict.items():
                pct = (v / total_value_krw * 100.0) if total_value_krw > 0 else 0.0
                lst.append({
                    "name": k,
                    "value_krw": round(v, 2),
                    "percentage": round(pct, 2)
                })
            return sorted(lst, key=lambda x: x["value_krw"], reverse=True)

        return {
            "total_value_krw": round(total_value_krw, 2),
            "by_type": to_pct_list(by_type),
            "by_market": to_pct_list(by_market),
            "by_currency": to_pct_list(by_currency),
            "by_leverage": to_pct_list(by_leverage),
            "by_sector": to_pct_list(by_sector),
            "by_warning_status": to_pct_list(by_warning_status)
        }
