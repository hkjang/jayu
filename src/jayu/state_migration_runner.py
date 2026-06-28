"""Migration runner for automatically upgrading older state schemas to the latest version."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .state_schema_registry import CURRENT_VERSIONS


class StateMigrationRunner:
    """Handles backup and structure upgrades of state JSON files."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        self.state_dir = self.project_root / "state"
        self.backup_dir = self.state_dir / "backups"

    def _create_backup(self, file_path: Path) -> Path | None:
        if not file_path.exists():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"
        shutil.copy2(file_path, backup_path)
        return backup_path

    def migrate_file(self, file_type: str, file_path: Path) -> dict[str, Any]:
        """Upgrades the schema of the target file to the latest version if needed."""
        if not file_path.exists():
            return {"status": "skipped", "reason": "file_not_found"}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return {"status": "failed", "reason": f"json_parse_error: {e}"}

        # Resolve current version
        # If it's a list (like toss_account_snapshot), schema_version cannot be stored inside the outer list.
        # Thus we check metadata or assume it's legacy if missing fields are present.
        current_expected_ver = CURRENT_VERSIONS.get(file_type, "1.0")
        
        is_dict = isinstance(data, dict)
        file_ver = "1.0"
        if is_dict:
            file_ver = str(data.get("schema_version", "1.0"))

        if file_ver == current_expected_ver and file_type != "toss_account_snapshot":
            return {"status": "skipped", "reason": "already_latest"}

        # Create backup before migration
        backup_file = self._create_backup(file_path)

        # Apply Migrators
        migration_applied = False
        migrated_data = data

        if file_type == "toss_account_snapshot":
            # Migrate old snapshot format:
            # e.g., missing exchange or currency, or mapping symbol -> symbol
            if isinstance(migrated_data, list):
                for item in migrated_data:
                    if "exchange" not in item:
                        item["exchange"] = "US_MARKET"
                        migration_applied = True
                    if "currency" not in item:
                        item["currency"] = "USD"
                        migration_applied = True
                    # Upgrade holdingQuantity from qty if legacy
                    if "qty" in item and "holdingQuantity" not in item:
                        item["holdingQuantity"] = item["qty"]
                        migration_applied = True
                    if "price" in item and "currentPrice" not in item:
                        item["currentPrice"] = item["price"]
                        migration_applied = True

        elif file_type == "dividend_cache":
            if file_ver == "1.0":
                # Upgrade dividend cache: add source_hash and error_reason fields
                if "error_reason" not in migrated_data:
                    migrated_data["error_reason"] = None
                    migration_applied = True
                if "source_hash" not in migrated_data:
                    migrated_data["source_hash"] = None
                    migration_applied = True
                migrated_data["schema_version"] = "1.1"
                migration_applied = True

        elif file_type == "dashboard_cache":
            if file_ver == "1.0":
                # Upgrade dashboard cache: add unmapped_count and calculations timestamp
                if "unmapped_count" not in migrated_data:
                    migrated_data["unmapped_count"] = 0
                    migration_applied = True
                migrated_data["schema_version"] = "1.1"
                migration_applied = True

        if migration_applied:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(migrated_data, f, ensure_ascii=False, indent=2)
                return {
                    "status": "success",
                    "backup_path": str(backup_file.relative_to(self.project_root)) if backup_file else None,
                    "from_version": file_ver,
                    "to_version": current_expected_ver
                }
            except Exception as e:
                # Restore from backup if write fails
                if backup_file:
                    shutil.copy2(backup_file, file_path)
                return {"status": "failed", "reason": f"write_error: {e}"}

        return {"status": "skipped", "reason": "no_migration_needed"}
