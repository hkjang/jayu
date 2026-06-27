from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Sequence
from dataclasses import dataclass, asdict

@dataclass
class StandardizedSecurity:
    symbol: str
    name: str
    english_name: str
    market: str
    currency: str
    security_type: str  # STOCK, ETF, ETN, etc.
    leverage_factor: float  # 1.0, 2.0, 3.0, -1.0, etc.
    warnings: dict[str, Any]  # marketWarning, administrative, delistingCaution, tradingSuspended
    is_tradable: bool
    updated_at: float

class TossSecurityMaster:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.state_dir = self.project_root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.state_dir / "toss_security_master_cache.json"
        self.orders_file = self.state_dir / "toss_orders.json"
        self.portfolio_file = self.project_root / "toss_portfolio.csv"

    def load_cache(self) -> dict[str, dict[str, Any]]:
        cache = {}
        # Load from old stock metadata cache first as fallback
        old_cache_file = self.state_dir / "toss_stock_metadata_cache.json"
        if old_cache_file.exists():
            try:
                with open(old_cache_file, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                    for sym, val in old_data.items():
                        cache[sym] = {
                            "symbol": val.get("symbol") or sym,
                            "name": val.get("name") or sym,
                            "english_name": val.get("englishName") or "",
                            "market": val.get("market") or "UNKNOWN",
                            "currency": val.get("currency") or "USD",
                            "security_type": val.get("securityType") or "STOCK",
                            "leverage_factor": float(val.get("leverageFactor") or 1.0),
                            "warnings": val.get("warnings") or {},
                            "is_tradable": val.get("status", "ACTIVE") == "ACTIVE",
                            "updated_at": 0.0  # Mark as expired so it updates if client is available
                        }
            except Exception:
                pass

        # Load from new security master cache to overwrite
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    new_data = json.load(f)
                    cache.update(new_data)
            except Exception:
                pass
        return cache

    def save_cache(self, cache: dict[str, dict[str, Any]]):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_all_symbols_from_user_data(self) -> set[str]:
        symbols = set()
        # 1. From toss_orders.json
        if self.orders_file.exists():
            try:
                with open(self.orders_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    orders = data if isinstance(data, list) else data.get("orders", [])
                    for o in orders:
                        sym = o.get("symbol")
                        if sym:
                            symbols.add(sym.strip().upper())
            except Exception:
                pass

        # 2. From toss_portfolio.csv
        if self.portfolio_file.exists():
            try:
                import csv
                with open(self.portfolio_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sym = row.get("Symbol") or row.get("symbol")
                        if sym:
                            symbols.add(sym.strip().upper())
            except Exception:
                pass
        return symbols

    def get_security_master(self, client: Any = None) -> dict[str, dict[str, Any]]:
        cache = self.load_cache()
        symbols = self.get_all_symbols_from_user_data()
        
        # Add default fallbacks to ensure we have base list
        fallbacks = ["AAPL", "TSLA", "MSFT", "005930", "SCHD", "O", "JEPI", "TQQQ", "SOXL", "NVDA", "VOO", "JEPQ", "ROBO"]
        for f in fallbacks:
            symbols.add(f)

        now = time.time()
        missing_or_expired = []
        for sym in symbols:
            cached_item = cache.get(sym)
            # Expire after 24 hours (86400 seconds)
            if not cached_item or (now - cached_item.get("updated_at", 0)) > 86400:
                missing_or_expired.append(sym)

        if missing_or_expired and client is not None:
            # Query in chunks of 50 to avoid URL length limits
            chunk_size = 50
            for i in range(0, len(missing_or_expired), chunk_size):
                chunk = missing_or_expired[i:i+chunk_size]
                try:
                    res = client.stocks(chunk)
                    stocks_list = res.get("result", []) if isinstance(res, dict) else []
                    for stock_info in stocks_list:
                        sym = stock_info.get("symbol")
                        if not sym:
                            continue
                            
                        # Query warnings for this symbol
                        warnings_info = {}
                        try:
                            w_res = client.stock_warnings(sym)
                            warnings_info = w_res.get("result", {}) if isinstance(w_res, dict) else {}
                        except Exception:
                            # Default empty warnings
                            warnings_info = {
                                "symbol": sym,
                                "marketWarning": "NONE",
                                "administrative": False,
                                "delistingCaution": False,
                                "tradingSuspended": False,
                            }

                        # Standardize security type and leverage
                        sec_type = str(stock_info.get("securityType") or "STOCK").upper()
                        leverage = float(stock_info.get("leverageFactor") or 1.0)
                        
                        # Custom override for known leveraged ETFs if leverage factor is missing
                        if "TQQQ" in sym:
                            leverage = 3.0
                            sec_type = "ETF"
                        elif "SOXL" in sym:
                            leverage = 3.0
                            sec_type = "ETF"
                        elif "QLD" in sym:
                            leverage = 2.0
                            sec_type = "ETF"

                        is_tradable = True
                        if warnings_info.get("tradingSuspended") or stock_info.get("status") == "DELISTED":
                            is_tradable = False

                        standardized = StandardizedSecurity(
                            symbol=sym,
                            name=stock_info.get("name") or stock_info.get("englishName") or sym,
                            english_name=stock_info.get("englishName") or stock_info.get("name") or sym,
                            market=str(stock_info.get("market") or "UNKNOWN").upper(),
                            currency=str(stock_info.get("currency") or "KRW").upper(),
                            security_type=sec_type,
                            leverage_factor=leverage,
                            warnings=warnings_info,
                            is_tradable=is_tradable,
                            updated_at=now
                        )
                        cache[sym] = asdict(standardized)
                except Exception:
                    pass

        # Apply offline fallback values for any symbol still missing in cache
        fallback_data = {
            "005930": {"name": "삼성전자", "market": "KOSPI", "currency": "KRW", "security_type": "STOCK", "leverage_factor": 1.0},
            "AAPL": {"name": "애플", "market": "NASDAQ", "currency": "USD", "security_type": "STOCK", "leverage_factor": 1.0},
            "TSLA": {"name": "테슬라", "market": "NASDAQ", "currency": "USD", "security_type": "STOCK", "leverage_factor": 1.0},
            "MSFT": {"name": "마이크로소프트", "market": "NASDAQ", "currency": "USD", "security_type": "STOCK", "leverage_factor": 1.0},
            "SCHD": {"name": "SCHD (배당성장 ETF)", "market": "NYSE", "currency": "USD", "security_type": "ETF", "leverage_factor": 1.0},
            "O": {"name": "리얼티 인컴 (월배당 리츠)", "market": "NYSE", "currency": "USD", "security_type": "STOCK", "leverage_factor": 1.0},
            "JEPI": {"name": "JEPI (고배당 커버드콜)", "market": "NYSE", "currency": "USD", "security_type": "ETF", "leverage_factor": 1.0},
            "TQQQ": {"name": "TQQQ (나스닥 3배 레버리지)", "market": "NASDAQ", "currency": "USD", "security_type": "ETF", "leverage_factor": 3.0},
            "SOXL": {"name": "SOXL (반도체 3배 레버리지)", "market": "NYSE", "currency": "USD", "security_type": "ETF", "leverage_factor": 3.0},
            "NVDA": {"name": "엔비디아", "market": "NASDAQ", "currency": "USD", "security_type": "STOCK", "leverage_factor": 1.0},
            "VOO": {"name": "VOO (S&P 500 ETF)", "market": "NYSE", "currency": "USD", "security_type": "ETF", "leverage_factor": 1.0},
            "JEPQ": {"name": "JEPQ (나스닥 고배당 커버드콜)", "market": "NYSE", "currency": "USD", "security_type": "ETF", "leverage_factor": 1.0},
            "ROBO": {"name": "ROBO (로봇/자동화 ETF)", "market": "NYSE", "currency": "USD", "security_type": "ETF", "leverage_factor": 1.0},
            "QQQ": {"name": "QQQ (나스닥 100 ETF)", "market": "NASDAQ", "currency": "USD", "security_type": "ETF", "leverage_factor": 1.0},
            "QLD": {"name": "QLD (나스닥 2배 레버리지)", "market": "NASDAQ", "currency": "USD", "security_type": "ETF", "leverage_factor": 2.0},
        }

        for sym, fb in fallback_data.items():
            if sym not in cache:
                cache[sym] = {
                    "symbol": sym,
                    "name": fb["name"],
                    "english_name": sym,
                    "market": fb["market"],
                    "currency": fb["currency"],
                    "security_type": fb["security_type"],
                    "leverage_factor": fb["leverage_factor"],
                    "warnings": {
                        "symbol": sym,
                        "marketWarning": "NONE",
                        "administrative": False,
                        "delistingCaution": False,
                        "tradingSuspended": False,
                    },
                    "is_tradable": True,
                    "updated_at": now
                }

        self.save_cache(cache)
        return cache
