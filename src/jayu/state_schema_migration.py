from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = "1.1.0"

class SchemaMigrator:
    def __init__(self, target_version: str = CURRENT_SCHEMA_VERSION) -> None:
        self.target_version = target_version

    def get_version_tuple(self, version_str: str) -> tuple[int, ...]:
        # Normalize versions like "1.0" to "1.0.0"
        parts = version_str.strip().split(".")
        while len(parts) < 3:
            parts.append("0")
        try:
            return tuple(int(p) for p in parts[:3])
        except ValueError:
            return (1, 0, 0)

    def migrate_data(self, data: dict[str, Any], file_name: str) -> tuple[dict[str, Any], str, list[str]]:
        original_version = str(data.get("schema_version", "1.0.0"))
        logs = []
        
        current_v = self.get_version_tuple(original_version)
        target_v = self.get_version_tuple(self.target_version)
        
        if current_v >= target_v:
            return data, original_version, logs

        # Step 1: Migrate from 1.0.0 (or "1.0") to 1.1.0
        if current_v < (1, 1, 0):
            logs.append(f"Migrating {file_name} from {original_version} to 1.1.0")
            # Enforce key fields for runs/manifest.json
            if "manifest" in file_name or "run" in file_name:
                if "explanation_level" not in data:
                    data["explanation_level"] = "general"
                    logs.append("Added default 'explanation_level': 'general'")
                if "git_revision" not in data:
                    data["git_revision"] = "unknown"
                    logs.append("Added default 'git_revision': 'unknown'")
                if "dirty" not in data:
                    data["dirty"] = False
                    logs.append("Added default 'dirty': false")
                if "config_hash" not in data:
                    data["config_hash"] = "unknown"
                    logs.append("Added default 'config_hash': 'unknown'")
                    
            # Enforce key fields for today_signals.json
            elif "signal" in file_name:
                if "signals" in data and isinstance(data["signals"], list):
                    for sig in data["signals"]:
                        if "status" not in sig:
                            sig["status"] = "not_evaluated"
                            logs.append("Added default signal status 'not_evaluated'")
                        if "data_verified" not in sig:
                            sig["data_verified"] = False
                            
            # Enforce key fields for state/best_strategy.json
            elif "best_strategy" in file_name:
                if "strategy_id" not in data:
                    data["strategy_id"] = "unknown"
                    logs.append("Added default 'strategy_id'")
                    
            data["schema_version"] = "1.1.0"
            current_v = (1, 1, 0)

        return data, original_version, logs

    def migrate_file(self, file_path: Path) -> dict[str, Any]:
        report = {
            "file": file_path.name,
            "path": str(file_path),
            "migrated": False,
            "from_version": "unknown",
            "to_version": self.target_version,
            "logs": [],
            "status": "success"
        }
        
        if not file_path.exists():
            report["status"] = "error"
            report["logs"].append("File does not exist")
            return report
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            report["status"] = "error"
            report["logs"].append(f"JSON decode failed: {e}")
            return report
            
        if not isinstance(data, dict):
            report["status"] = "warning"
            report["logs"].append("JSON root is not a dictionary. Cannot check or migrate schema.")
            return report
            
        original_version = str(data.get("schema_version", "1.0.0"))
        report["from_version"] = original_version
        
        if self.get_version_tuple(original_version) >= self.get_version_tuple(self.target_version):
            report["logs"].append("File is already up to date")
            return report
            
        try:
            migrated_data, from_v, logs = self.migrate_data(data, file_path.name)
            report["logs"].extend(logs)
            
            if self.get_version_tuple(from_v) < self.get_version_tuple(self.target_version):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(migrated_data, f, indent=2, ensure_ascii=False)
                report["migrated"] = True
                report["logs"].append(f"Successfully wrote migrated JSON to {file_path.name}")
        except Exception as e:
            report["status"] = "error"
            report["logs"].append(f"Migration failed: {e}")
            
        return report

    def migrate_all(self, paths: Any) -> list[dict[str, Any]]:
        reports = []
        
        # 1. Scan state directory
        for p in paths.state_dir.glob("*.json"):
            reports.append(self.migrate_file(p))
            
        # 2. Scan signals directory
        for p in paths.signals_dir.glob("*.json"):
            reports.append(self.migrate_file(p))
            
        # 3. Scan runs directory recursively
        for p in paths.runs_dir.rglob("*.json"):
            reports.append(self.migrate_file(p))
            
        return reports
