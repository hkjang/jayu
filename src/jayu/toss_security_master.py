from __future__ import annotations

import json
import time
import hashlib
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
    is_etf: bool
    is_leverage: bool
    leverage_factor: float  # 1.0, 2.0, 3.0, -1.0, etc.
    warnings: dict[str, Any]  # marketWarning, administrative, delistingCaution, tradingSuspended
    is_tradable: bool
    updated_at: float
    source_hash: str

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
                        sec_type = val.get("securityType") or "STOCK"
                        lev = float(val.get("leverageFactor") or 1.0)
                        cache[sym] = {
                            "symbol": val.get("symbol") or sym,
                            "name": val.get("name") or sym,
                            "english_name": val.get("englishName") or "",
                            "market": val.get("market") or "UNKNOWN",
                            "currency": val.get("currency") or "USD",
                            "security_type": sec_type,
                            "is_etf": sec_type == "ETF",
                            "is_leverage": lev > 1.0 or lev < -1.0,
                            "leverage_factor": lev,
                            "warnings": val.get("warnings") or {},
                            "is_tradable": val.get("status", "ACTIVE") == "ACTIVE",
                            "updated_at": 0.0,
                            "source_hash": "legacy_cache"
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
        fallbacks = ["AAPL", "TSLA", "MSFT", "005930", "SCHD", "O", "JEPI", "TQQQ", "SOXL", "NVDA", "VOO", "JEPQ", "ROBO", "QQQ", "QLD"]
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

                        # Calculate source hash
                        raw_data_str = json.dumps({"stock": stock_info, "warnings": warnings_info}, sort_keys=True)
                        source_hash = hashlib.sha256(raw_data_str.encode("utf-8")).hexdigest()

                        standardized = StandardizedSecurity(
                            symbol=sym,
                            name=stock_info.get("name") or stock_info.get("englishName") or sym,
                            english_name=stock_info.get("englishName") or stock_info.get("name") or sym,
                            market=str(stock_info.get("market") or "UNKNOWN").upper(),
                            currency=str(stock_info.get("currency") or "KRW").upper(),
                            security_type=sec_type,
                            is_etf=sec_type == "ETF",
                            is_leverage=leverage > 1.0 or leverage < -1.0,
                            leverage_factor=leverage,
                            warnings=warnings_info,
                            is_tradable=is_tradable,
                            updated_at=now,
                            source_hash=source_hash
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
                    "is_etf": fb["security_type"] == "ETF",
                    "is_leverage": fb["leverage_factor"] > 1.0,
                    "leverage_factor": fb["leverage_factor"],
                    "warnings": {
                        "symbol": sym,
                        "marketWarning": "NONE",
                        "administrative": False,
                        "delistingCaution": False,
                        "tradingSuspended": False,
                    },
                    "is_tradable": True,
                    "updated_at": now,
                    "source_hash": "offline_fallback"
                }

        self.save_cache(cache)

        # Calculate holding info from toss_portfolio.csv and toss_orders.json
        actual_holdings = {}
        if self.portfolio_file.exists():
            try:
                import csv
                with open(self.portfolio_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Headers: 종목명,티커,보유 수량,현재가,평가금,통화
                        ticker = row.get("티커") or row.get("ticker") or row.get("symbol") or row.get("Symbol") or row.get("Ticker")
                        qty_str = row.get("보유 수량") or row.get("quantity") or row.get("qty") or row.get("Qty") or row.get("Quantity")
                        price_str = row.get("현재가") or row.get("current_price") or row.get("price") or row.get("Price") or row.get("Current Price") or row.get("CurrentPrice")
                        name_val = row.get("종목명") or row.get("name") or row.get("Name")
                        if ticker and qty_str:
                            ticker = ticker.strip().upper()
                            try:
                                qty = float(qty_str.replace(",", ""))
                                price = float(price_str.replace(",", "")) if price_str else 0.0
                                actual_holdings[ticker] = {
                                    "quantity": qty,
                                    "current_price": price,
                                    "name": name_val.strip() if name_val else ""
                                }
                            except ValueError:
                                pass
            except Exception:
                pass

        orders = []
        if self.orders_file.exists():
            try:
                with open(self.orders_file, "r", encoding="utf-8") as f:
                    orders = json.load(f)
                    if not isinstance(orders, list):
                        orders = orders.get("orders", [])
            except Exception:
                pass

        # Group orders by symbol
        orders_by_symbol = {}
        for o in orders:
            sym = o.get("symbol")
            if sym:
                orders_by_symbol.setdefault(sym.strip().upper(), []).append(o)

        holding_info = {}
        for sym, sym_orders in orders_by_symbol.items():
            # Sort chronologically (oldest first)
            sym_orders = sorted(sym_orders, key=lambda x: x.get("orderedAt", ""))
            
            # FIFO simulation
            lots = [] # list of [qty, price, date]
            for o in sym_orders:
                status = o.get("status")
                if status and status not in ("FILLED", "PARTIALLY_FILLED"):
                    continue
                
                side = o.get("side")
                exec_info = o.get("execution") or {}
                qty = float(exec_info.get("filledQuantity") or o.get("quantity") or 0.0)
                price = float(exec_info.get("averageFilledPrice") or o.get("price") or 0.0)
                dt = o.get("orderedAt")
                
                if qty <= 0:
                    continue
                
                if side == "BUY":
                    lots.append([qty, price, dt])
                elif side == "SELL":
                    rem = qty
                    while rem > 0 and lots:
                        if lots[0][0] <= rem:
                            rem -= lots[0][0]
                            lots.pop(0)
                        else:
                            lots[0][0] -= rem
                            rem = 0.0

            # Match with actual holdings if present
            actual = actual_holdings.get(sym)
            actual_qty = actual["quantity"] if actual else 0.0
            
            sim_qty = sum(lot[0] for lot in lots)
            
            if actual_qty > sim_qty:
                diff = actual_qty - sim_qty
                oldest_date = sym_orders[0].get("orderedAt") if sym_orders else None
                lots.insert(0, [diff, None, oldest_date])
            elif actual_qty < sim_qty and actual_qty > 0:
                # Trim from oldest to match actual_qty
                rem = sim_qty - actual_qty
                while rem > 0 and lots:
                    if lots[0][0] <= rem:
                        rem -= lots[0][0]
                        lots.pop(0)
                    else:
                        lots[0][0] -= rem
                        rem = 0.0
            
            current_held_qty = actual_qty if actual else sim_qty
            if current_held_qty > 0 and lots:
                known_qty = sum(lot[0] for lot in lots if lot[1] is not None)
                known_cost = sum(lot[0] * lot[1] for lot in lots if lot[1] is not None)
                avg_price = known_cost / known_qty if known_qty > 0 else None
                
                is_pre_existing = (lots[0][1] is None)
                start_date = lots[0][2]
                
                holding_info[sym] = {
                    "holding_start_date": start_date,
                    "is_pre_existing": is_pre_existing,
                    "average_price": avg_price,
                    "quantity": current_held_qty,
                }

        # For any actual holding not in holding_info
        for sym, actual in actual_holdings.items():
            if sym not in holding_info and actual["quantity"] > 0:
                holding_info[sym] = {
                    "holding_start_date": None,
                    "is_pre_existing": True,
                    "average_price": None,
                    "quantity": actual["quantity"],
                }

        # Enrich cache before returning
        enriched_cache = {}
        for sym, val in cache.items():
            item = dict(val)
            info = holding_info.get(sym)
            if info:
                item["is_holding"] = True
                item["holding_start_date"] = info["holding_start_date"]
                item["is_pre_existing"] = info["is_pre_existing"]
                item["holding_average_price"] = info["average_price"]
                item["holding_quantity"] = info["quantity"]
            else:
                item["is_holding"] = False
                item["holding_start_date"] = None
                item["is_pre_existing"] = False
                item["holding_average_price"] = None
                item["holding_quantity"] = 0.0
            
            actual = actual_holdings.get(sym)
            if actual:
                item["current_price"] = actual["current_price"]
                if actual.get("name"):
                    item["name"] = actual["name"]
            else:
                item["current_price"] = None
                
            enriched_cache[sym] = item

        # Add any holding_info symbols that are not in cache
        for sym, info in holding_info.items():
            if sym not in enriched_cache:
                actual = actual_holdings.get(sym)
                name_val = actual["name"] if actual and actual.get("name") else sym
                curr = "KRW" if (sym.endswith(".KS") or sym.endswith(".KQ") or sym.isdigit()) else "USD"
                
                enriched_cache[sym] = {
                    "symbol": sym,
                    "name": name_val,
                    "english_name": sym,
                    "market": "UNKNOWN",
                    "currency": curr,
                    "security_type": "STOCK",
                    "is_etf": False,
                    "is_leverage": False,
                    "leverage_factor": 1.0,
                    "warnings": {
                        "symbol": sym,
                        "marketWarning": "NONE",
                        "administrative": False,
                        "delistingCaution": False,
                        "tradingSuspended": False,
                    },
                    "is_tradable": True,
                    "updated_at": now,
                    "source_hash": "dynamic_holding",
                    "is_holding": True,
                    "holding_start_date": info["holding_start_date"],
                    "is_pre_existing": info["is_pre_existing"],
                    "holding_average_price": info["average_price"],
                    "holding_quantity": info["quantity"],
                    "current_price": actual["current_price"] if actual else None
                }
            
        return enriched_cache
