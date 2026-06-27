import json
import time
from pathlib import Path
from typing import Any

class TossWarningRegistry:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.state_dir = self.project_root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.state_dir / "toss_warning_history.json"

    def load_history(self) -> list[dict[str, Any]]:
        if not self.history_file.exists():
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_history(self, history: list[dict[str, Any]]):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def register_warnings(self, symbol: str, warnings_info: dict[str, Any]) -> dict[str, Any]:
        """
        Registers current warning status and updates history.
        """
        history = self.load_history()
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        
        m_warning = str(warnings_info.get("marketWarning") or "NONE").upper()
        admin = bool(warnings_info.get("administrative", False))
        delist = bool(warnings_info.get("delistingCaution", False))
        suspended = bool(warnings_info.get("tradingSuspended", False))
        
        has_risk = (m_warning != "NONE") or admin or delist or suspended
        blocks_autotrade = admin or delist or suspended or m_warning in {"INVESTMENT_DANGER", "DANGER"}
        
        # Check if there is an active record for this symbol
        active_record = None
        for record in history:
            if record.get("symbol") == symbol and record.get("resolved_at") is None:
                active_record = record
                break
                
        if has_risk:
            if active_record:
                # Update active record with current status
                active_record["market_warning"] = m_warning
                active_record["administrative"] = admin
                active_record["delisting_caution"] = delist
                active_record["trading_suspended"] = suspended
                active_record["blocks_autotrade"] = blocks_autotrade
                active_record["last_seen_at"] = now_str
            else:
                # Create a new active record
                new_record = {
                    "symbol": symbol,
                    "market_warning": m_warning,
                    "administrative": admin,
                    "delisting_caution": delist,
                    "trading_suspended": suspended,
                    "blocks_autotrade": blocks_autotrade,
                    "detected_at": now_str,
                    "last_seen_at": now_str,
                    "resolved_at": None
                }
                history.append(new_record)
        else:
            # Resolved: if there was an active record, resolve it
            if active_record:
                active_record["resolved_at"] = now_str
                active_record["last_seen_at"] = now_str
                
        self.save_history(history)
        
        return {
            "symbol": symbol,
            "has_risk": has_risk,
            "blocks_autotrade": blocks_autotrade,
            "market_warning": m_warning,
            "administrative": admin,
            "delisting_caution": delist,
            "trading_suspended": suspended
        }
