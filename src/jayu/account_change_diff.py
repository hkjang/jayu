"""Computes daily differences in portfolio holdings, cash, and exposures."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class AccountChangeDiff:
    """Compares the current toss account snapshot with the previous backup to calculate changes."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        self.state_dir = self.project_root / "state"
        self.backup_dir = self.state_dir / "backups"

    def _find_previous_snapshot(self) -> Path | None:
        """Finds the most recent backup file of toss_account_snapshot."""
        if not self.backup_dir.exists():
            return None
        
        backups = []
        for p in self.backup_dir.glob("toss_account_snapshot_*.json"):
            # Extract timestamp to sort
            match = re.search(r"toss_account_snapshot_(\d{8}_\d{6})\.json", p.name)
            if match:
                backups.append((match.group(1), p))
        
        if not backups:
            return None
            
        # Sort by timestamp descending
        backups.sort(key=lambda x: x[0], reverse=True)
        return backups[0][1]

    def calculate_diff(self) -> dict[str, Any]:
        """Calculates differences between current snapshot and the previous backup snapshot."""
        current_path = self.state_dir / "toss_account_snapshot.json"
        prev_path = self._find_previous_snapshot()

        if not current_path.exists():
            return self._empty_diff_response("Current snapshot not found")

        try:
            with open(current_path, "r", encoding="utf-8") as f:
                current_holdings = json.load(f)
        except Exception as e:
            return self._empty_diff_response(f"Failed to load current snapshot: {e}")

        prev_holdings = []
        if prev_path and prev_path.exists():
            try:
                with open(prev_path, "r", encoding="utf-8") as f:
                    prev_holdings = json.load(f)
            except Exception:
                pass

        # Parse holdings into dictionaries keyed by symbol
        curr_map = {h["symbol"].upper(): h for h in current_holdings if "symbol" in h}
        prev_map = {h["symbol"].upper(): h for h in prev_holdings if "symbol" in h}

        holding_changes = []
        added_symbols = []
        removed_symbols = []
        
        # Calculate changes
        all_symbols = set(curr_map.keys()) | set(prev_map.keys())
        total_prev_value_usd = 0.0
        total_curr_value_usd = 0.0
        
        price_change_contribution_usd = 0.0
        quantity_change_contribution_usd = 0.0

        for sym in all_symbols:
            curr = curr_map.get(sym)
            prev = prev_map.get(sym)

            curr_qty = float(curr.get("holdingQuantity") or curr.get("qty", 0)) if curr else 0.0
            curr_price = float(curr.get("currentPrice") or curr.get("price", 0)) if curr else 0.0
            curr_value = curr_qty * curr_price
            
            prev_qty = float(prev.get("holdingQuantity") or prev.get("qty", 0)) if prev else 0.0
            prev_price = float(prev.get("currentPrice") or prev.get("price", 0)) if prev else 0.0
            prev_value = prev_qty * prev_price

            total_curr_value_usd += curr_value
            total_prev_value_usd += prev_value

            if curr and not prev:
                added_symbols.append(sym)
                quantity_change_contribution_usd += curr_value
                holding_changes.append({
                    "symbol": sym,
                    "type": "added",
                    "qty_diff": curr_qty,
                    "val_diff_usd": curr_value,
                    "price_diff_pct": 0.0
                })
            elif prev and not curr:
                removed_symbols.append(sym)
                quantity_change_contribution_usd -= prev_value
                holding_changes.append({
                    "symbol": sym,
                    "type": "removed",
                    "qty_diff": -prev_qty,
                    "val_diff_usd": -prev_value,
                    "price_diff_pct": -100.0
                })
            elif curr and prev:
                qty_diff = curr_qty - prev_qty
                price_diff = curr_price - prev_price
                val_diff = curr_value - prev_value
                
                # Decompose value change:
                # 1. Quantity change contribution = (curr_qty - prev_qty) * prev_price
                # 2. Price change contribution = curr_qty * (curr_price - prev_price)
                q_contrib = qty_diff * prev_price
                p_contrib = curr_qty * price_diff
                
                price_change_contribution_usd += p_contrib
                quantity_change_contribution_usd += q_contrib

                if qty_diff != 0 or price_diff != 0:
                    holding_changes.append({
                        "symbol": sym,
                        "type": "modified",
                        "qty_diff": qty_diff,
                        "val_diff_usd": val_diff,
                        "price_diff_pct": (price_diff / prev_price * 100.0) if prev_price > 0 else 0.0,
                        "decomposition": {
                            "quantity_effect_usd": q_contrib,
                            "price_effect_usd": p_contrib
                        }
                    })

        val_change_usd = total_curr_value_usd - total_prev_value_usd
        val_change_pct = (val_change_usd / total_prev_value_usd * 100.0) if total_prev_value_usd > 0 else 0.0

        # Simple conversion rate fallback
        usd_krw = 1350.0
        try:
            # Try to read actual cached rate from tax fx engine if possible
            from .dividend_tax_fx_engine import DividendTaxFxEngine
            engine = DividendTaxFxEngine(self.project_root)
            usd_krw = engine.get_live_fx_rate()
        except Exception:
            pass

        return {
            "status": "success",
            "compare_file": prev_path.name if prev_path else "none",
            "summary": {
                "previous_value_usd": round(total_prev_value_usd, 2),
                "current_value_usd": round(total_curr_value_usd, 2),
                "previous_value_krw": round(total_prev_value_usd * usd_krw, 0),
                "current_value_krw": round(total_curr_value_usd * usd_krw, 0),
                "total_change_usd": round(val_change_usd, 2),
                "total_change_krw": round(val_change_usd * usd_krw, 0),
                "total_change_pct": round(val_change_pct, 2),
                "effects": {
                    "price_change_contribution_usd": round(price_change_contribution_usd, 2),
                    "price_change_contribution_krw": round(price_change_contribution_usd * usd_krw, 0),
                    "quantity_change_contribution_usd": round(quantity_change_contribution_usd, 2),
                    "quantity_change_contribution_krw": round(quantity_change_contribution_usd * usd_krw, 0)
                }
            },
            "added_symbols": added_symbols,
            "removed_symbols": removed_symbols,
            "changes": holding_changes
        }

    def _empty_diff_response(self, reason: str) -> dict[str, Any]:
        return {
            "status": "empty",
            "reason": reason,
            "compare_file": "none",
            "summary": {
                "previous_value_usd": 0.0,
                "current_value_usd": 0.0,
                "previous_value_krw": 0.0,
                "current_value_krw": 0.0,
                "total_change_usd": 0.0,
                "total_change_krw": 0.0,
                "total_change_pct": 0.0,
                "effects": {
                    "price_change_contribution_usd": 0.0,
                    "price_change_contribution_krw": 0.0,
                    "quantity_change_contribution_usd": 0.0,
                    "quantity_change_contribution_krw": 0.0
                }
            },
            "added_symbols": [],
            "removed_symbols": [],
            "changes": []
        }
