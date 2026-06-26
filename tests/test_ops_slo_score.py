import pytest
import json
from pathlib import Path
from jayu.ops_slo_score import calculate_ops_slo_score, get_ops_slo_trends

@pytest.fixture
def temp_paths(tmp_path):
    project_root = tmp_path / "project"
    runs_dir = project_root / "runs"
    runs_dir.mkdir(parents=True)
    
    class FakePaths:
        def __init__(self):
            self.project_root = project_root
            self.runs_dir = runs_dir
            self.state_dir = project_root / "state"
            self.signals_dir = project_root / "signals"
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self.signals_dir.mkdir(parents=True, exist_ok=True)
            
    return FakePaths()

def test_ops_slo_score_calculation(temp_paths):
    # Setup mock run dir
    run_id = "20260626_140000_test"
    run_dir = temp_paths.runs_dir / run_id
    run_dir.mkdir()
    
    # 1. manifest.json (health score 90.0)
    manifest = {
        "execution_status": "success",
        "safety_decision": "approved",
        "health": {"score": 90.0}
    }
    with open(run_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f)
        
    # 2. data_sources.json (Yahoo success, Tiingo success = 100% verification)
    data_sources = {
        "sources": [
            {"provider": "Yahoo", "ticker": "NVDA", "status": "success"},
            {"provider": "Tiingo", "ticker": "TSLA", "status": "success"}
        ]
    }
    with open(run_dir / "data_sources.json", "w", encoding="utf-8") as f:
        json.dump(data_sources, f)
        
    # 3. signals_risk.json (1 signal, approved = 100% risk approval)
    risk_signals = {
        "rows": [
            {"ticker": "NVDA", "status": "approved", "action": "buy"}
        ]
    }
    with open(run_dir / "signals_risk.json", "w", encoding="utf-8") as f:
        json.dump(risk_signals, f)
        
    # 4. Write mock safety_verdict and report to make evidence completeness high
    with open(run_dir / "safety_verdict.json", "w", encoding="utf-8") as f:
        json.dump({"verdict": "approved"}, f)
    with open(run_dir / "provider_disagreement_report.json", "w", encoding="utf-8") as f:
        json.dump({"disagreements": []}, f)
    with open(run_dir / "risk_explanation.json", "w", encoding="utf-8") as f:
        json.dump({"signals": []}, f)
    with open(run_dir / "report.md", "w", encoding="utf-8") as f:
        f.write("# Daily Report")

    # Evaluate SLO score
    # Expected inputs:
    # - data_rate: 100.0 (30% weight -> 30.0)
    # - risk_rate: 100.0 (25% weight -> 25.0)
    # - evidence_score: 100.0 (7/7 files exist) (20% weight -> 20.0)
    # - sla_rate: 100.0 (both Yahoo/Tiingo have 100% success rate -> SLA compliant) (15% weight -> 15.0)
    # - health_score: 90.0 (10% weight -> 9.0)
    # Expected Total: 30 + 25 + 20 + 15 + 9 = 99.0
    
    result = calculate_ops_slo_score(temp_paths, run_id=run_id)
    assert result["score"] == 99.0
    assert result["status"] == "success"
    assert result["breakdown"]["data_quality"] == 100.0
    assert result["breakdown"]["health"] == 90.0
    
    # Test trends
    trends = get_ops_slo_trends(temp_paths, limit=5)
    assert len(trends) == 1
    assert trends[0]["score"] == 99.0
    assert trends[0]["date"] == "20260626"
