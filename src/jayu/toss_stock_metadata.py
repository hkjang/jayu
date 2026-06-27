from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from .toss_security_master import TossSecurityMaster

class TossStockMetadataManager:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.master = TossSecurityMaster(self.project_root)
        self.cache_file = self.master.cache_file

    def load_cache(self) -> dict[str, Any]:
        return self.master.load_cache()

    def save_cache(self, cache: dict[str, Any]):
        self.master.save_cache(cache)

    def get_all_symbols_from_user_data(self) -> set[str]:
        return self.master.get_all_symbols_from_user_data()

    def get_stock_names(self, client: Any = None) -> dict[str, str]:
        # Return a simple mapping of {symbol: name} from the security master
        sec_master = self.master.get_security_master(client)
        return {sym: data.get("name", sym) for sym, data in sec_master.items()}
