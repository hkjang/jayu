import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Sequence

logger = logging.getLogger(__name__)

class TossStockMetadataManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.cache_file = project_root / "state" / "toss_stock_metadata_cache.json"
        self.orders_file = project_root / "state" / "toss_orders.json"
        self.portfolio_file = project_root / "state" / "toss_portfolio.csv"

    def load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_file.exists():
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load stock metadata cache: {e}")
            return {}

    def save_cache(self, cache: dict[str, dict[str, Any]]) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save stock metadata cache: {e}")

    def get_all_symbols_from_user_data(self) -> set[str]:
        symbols = set()
        
        # 1. From toss_orders.json
        if self.orders_file.exists():
            try:
                with open(self.orders_file, "r", encoding="utf-8") as f:
                    orders = json.load(f)
                    for o in orders:
                        sym = o.get("symbol")
                        if sym:
                            symbols.add(sym.upper())
            except Exception:
                pass
                
        # 2. From toss_portfolio.csv
        if self.portfolio_file.exists():
            try:
                import csv
                with open(self.portfolio_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sym = row.get("ticker") or row.get("symbol")
                        if sym:
                            symbols.add(sym.upper())
            except Exception:
                pass
                
        return symbols

    def get_stock_names(self, client: Any = None) -> dict[str, str]:
        cache = self.load_cache()
        user_symbols = self.get_all_symbols_from_user_data()
        
        # Identify missing or expired symbols (older than 24 hours)
        missing_symbols = []
        now = datetime.now()
        
        for sym in user_symbols:
            cached_item = cache.get(sym)
            if not cached_item:
                missing_symbols.append(sym)
            else:
                updated_at_str = cached_item.get("updated_at")
                if updated_at_str:
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str)
                        if now - updated_at > timedelta(hours=24):
                            missing_symbols.append(sym)
                    except ValueError:
                        missing_symbols.append(sym)
                else:
                    missing_symbols.append(sym)
                    
        # If we have missing symbols and a client is provided, query the Toss API
        if missing_symbols and client is not None:
            try:
                chunk_size = 50
                for i in range(0, len(missing_symbols), chunk_size):
                    chunk = missing_symbols[i:i+chunk_size]
                    res = client.stocks(chunk)
                    
                    stock_list = []
                    if isinstance(res, dict):
                        stock_list = res.get("result") or res.get("data", {}).get("items") or []
                    elif isinstance(res, list):
                        stock_list = res
                        
                    for stock in stock_list:
                        sym = stock.get("symbol")
                        if sym:
                            cache[sym.upper()] = {
                                "symbol": sym,
                                "name": stock.get("name") or stock.get("stockName"),
                                "englishName": stock.get("englishName") or stock.get("english_name"),
                                "currency": stock.get("currency"),
                                "updated_at": now.isoformat()
                            }
                self.save_cache(cache)
            except Exception as e:
                logger.error(f"Failed to fetch stock metadata from Toss API: {e}")
                
        # Return a simple mapping of symbol -> name
        mapping = {}
        for sym, item in cache.items():
            name = item.get("name")
            if name:
                mapping[sym] = name
                
        # Also include any hardcoded fallbacks just in case
        fallback_names = {
            "005930": "삼성전자",
            "AAPL": "애플",
            "TSLA": "테슬라",
            "MSFT": "마이크로소프트",
            "SCHD": "SCHD",
            "O": "리얼티 인컴",
            "JEPI": "JEPI",
            "TQQQ": "TQQQ",
            "SOXL": "SOXL",
            "NVDA": "엔비디아",
            "VOO": "VOO (S&P 500 ETF)",
            "JEPQ": "JEPQ (나스닥 고배당 커버드콜)",
            "ROBO": "ROBO (로봇/자동화 ETF)",
            "QQQ": "QQQ (나스닥 100 ETF)",
            "QLD": "QLD (나스닥 2배 레버리지)",
        }
        for sym, name in fallback_names.items():
            if sym not in mapping:
                mapping[sym] = name
                
        return mapping
