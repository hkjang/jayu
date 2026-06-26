import pytest
import json
import sqlite3
from pathlib import Path
from jayu.paths import RuntimePaths
from jayu.ops_datamart import init_db, insert_run_data, sync_all_runs, get_trends

@pytest.fixture
def temp_paths(tmp_path):
    # Setup temporary directory structure mimicking RuntimePaths
    project_root = tmp_path / "project"
    runs_dir = project_root / "runs"
    state_dir = project_root / "state"
    signals_dir = project_root / "signals"
    
    runs_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    signals_dir.mkdir(parents=True)
    
    class FakePaths:
        def __init__(self):
            self.project_root = project_root
            self.runs_dir = runs_dir
            self.state_dir = state_dir
            self.signals_dir = signals_dir
            
    return FakePaths()

def test_ops_datamart_init_and_sync(temp_paths, tmp_path):
    db_path = tmp_path / "test_ops.sqlite"
    init_db(db_path)
    
    # Verify tables exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    assert "runs" in tables
    assert "signals" in tables
    assert "risk_verdicts" in tables
    
    # Create mock run directory
    run_id = "20260626_130000_test"
    run_dir = temp_paths.runs_dir / run_id
    run_dir.mkdir(parents=True)
    
    # Write mock manifest
    manifest = {
        "execution_status": "success",
        "safety_decision": "approved",
        "failure_code": "NONE",
        "health": {"score": 95.0}
    }
    with open(run_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f)
        
    # Write mock signals
    signals = [
        {"ticker": "NVDA", "action": "buy", "strategy": "RSI2", "score": 85.0, "status": "approved", "data_verified": True}
    ]
    with open(run_dir / "today_signals.json", "w", encoding="utf-8") as f:
        json.dump({"signals": signals}, f)
        
    # Sync all runs
    count = sync_all_runs(db_path, temp_paths)
    assert count == 1
    
    # Query trends
    trends = get_trends(db_path, limit_days=10)
    assert trends["run_count"] == 1
    assert trends["success_rate"] == 100.0
    assert trends["avg_health_score"] == 95.0
    assert trends["runs"][0]["signal_count"] == 1
