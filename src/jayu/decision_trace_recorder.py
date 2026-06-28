"""Records execution traces of trading decisions for auditable replay."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class DecisionTraceRecorder:
    """Saves granular traces of the decision pipeline (Signal -> Risk -> Quality -> Autotrade)."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        self.trace_dir = self.project_root / "state" / "decision_traces"

    def record_trace(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        risk_evaluation: dict[str, Any],
        quality_gate: dict[str, Any],
        chasing_guard: dict[str, Any],
        final_verdict: dict[str, Any]
    ) -> str:
        """Saves a structured JSON trace of all evaluation stages."""
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        trace_id = f"trace_{symbol.upper()}_{timestamp}"
        
        trace_data = {
            "trace_id": trace_id,
            "symbol": symbol.upper(),
            "timestamp": datetime.now(UTC).isoformat(),
            "epoch_time": time.time(),
            "stages": {
                "1_signal_generation": signal_data,
                "2_risk_gate": risk_evaluation,
                "3_data_quality_gate": quality_gate,
                "4_dividend_chasing_guard": chasing_guard,
                "5_autotrading_guard": final_verdict
            }
        }
        
        file_path = self.trace_dir / f"{trace_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(trace_data, f, ensure_ascii=False, indent=2)
            
        return trace_id
