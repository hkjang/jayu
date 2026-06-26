import pytest
import json
from pathlib import Path
from jayu.paths import RuntimePaths
from jayu.provider_sla_policy import evaluate_provider_sla

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
            
    return FakePaths()

def test_provider_sla_evaluation(temp_paths):
    # Setup mock runs
    # To trigger calculate_provider_trends, we need directories starting with "run-"
    for idx in range(3):
        run_id = f"run-20260626_{idx:02d}"
        run_dir = temp_paths.runs_dir / run_id
        run_dir.mkdir()
        
        # Write mock data_sources.json
        # Yahoo succeeds, Tiingo fails on some attempts to trigger SLA warning/block
        data_sources = {
            "sources": [
                {"provider": "Yahoo", "ticker": "NVDA", "status": "success"},
                {"provider": "Tiingo", "ticker": "TSLA", "status": "failure" if idx == 0 else "success"}
            ]
        }
        with open(run_dir / "data_sources.json", "w", encoding="utf-8") as f:
            json.dump(data_sources, f)
            
        # Write empty disagreement and risk reports
        with open(run_dir / "provider_disagreement_report.json", "w", encoding="utf-8") as f:
            json.dump({"disagreements": []}, f)
        with open(run_dir / "risk_explanation.json", "w", encoding="utf-8") as f:
            json.dump({"signals": []}, f)

    # Evaluate SLA
    report = evaluate_provider_sla(temp_paths, limit=5)
    
    assert report["runs_analyzed"] == 3
    assert "Yahoo" in report["providers"]
    assert "Tiingo" in report["providers"]
    
    # Yahoo: 3 attempts, 3 successes = 100% success rate, 0% failure -> compliant
    assert report["providers"]["Yahoo"]["sla_compliant"] is True
    assert report["providers"]["Yahoo"]["status"] == "success"
    
    # Tiingo: 3 attempts, 2 successes, 1 failure = 33.3% failure rate -> violates 5% limit -> non-compliant
    assert report["providers"]["Tiingo"]["sla_compliant"] is False
    assert report["providers"]["Tiingo"]["status"] == "blocked"
    assert any("실패율" in v for v in report["providers"]["Tiingo"]["violations"])
    assert report["sla_compliant"] is False
