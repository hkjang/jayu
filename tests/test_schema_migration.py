import json
import pytest
from pathlib import Path
from jayu.state_schema_migration import SchemaMigrator, CURRENT_SCHEMA_VERSION

def test_schema_migrator_version_parsing():
    migrator = SchemaMigrator()
    assert migrator.get_version_tuple("1.0") == (1, 0, 0)
    assert migrator.get_version_tuple("1.1.0") == (1, 1, 0)
    assert migrator.get_version_tuple("invalid") == (1, 0, 0)

def test_schema_migrator_run_manifest_upgrade(tmp_path):
    # Older manifest lacking explanation_level and git_revision
    old_manifest = {
        "execution_status": "success",
        "safety_decision": "approved",
        # no schema_version implies 1.0.0
    }
    
    file_path = tmp_path / "manifest.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(old_manifest, f)
        
    migrator = SchemaMigrator(CURRENT_SCHEMA_VERSION)
    report = migrator.migrate_file(file_path)
    
    assert report["status"] == "success"
    assert report["migrated"] is True
    assert report["from_version"] == "1.0.0"
    
    # Read back the migrated file
    with open(file_path, "r", encoding="utf-8") as f:
        migrated = json.load(f)
        
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    assert migrated["explanation_level"] == "general"
    assert migrated["git_revision"] == "unknown"
    assert migrated["dirty"] is False
    assert migrated["config_hash"] == "unknown"

def test_schema_migrator_signals_upgrade(tmp_path):
    old_signals = {
        "schema_version": "1.0",
        "signals": [
            {"ticker": "NVDA", "action": "buy"} # lacking status and data_verified
        ]
    }
    
    file_path = tmp_path / "today_signals.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(old_signals, f)
        
    migrator = SchemaMigrator(CURRENT_SCHEMA_VERSION)
    report = migrator.migrate_file(file_path)
    
    assert report["status"] == "success"
    assert report["migrated"] is True
    
    with open(file_path, "r", encoding="utf-8") as f:
        migrated = json.load(f)
        
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    assert migrated["signals"][0]["status"] == "not_evaluated"
    assert migrated["signals"][0]["data_verified"] is False
