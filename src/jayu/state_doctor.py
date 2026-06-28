"""Diagnoses and provides recovery guides for broken, corrupted, or stale state files."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .state_schema_registry import SCHEMA_RULES, validate_state_structure


class StateDoctor:
    """Diagnoses state store anomalies and provides recovery instructions."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        self.state_dir = self.project_root / "state"

    def diagnose_all(self) -> dict[str, Any]:
        """Runs a complete checkup on all state files in the directory."""
        diagnoses = {}
        anomalies_found = 0

        files_to_check = {
            "toss_account_snapshot": self.state_dir / "toss_account_snapshot.json",
            "dividend_cache": None, # checked dynamically in directory
            "dashboard_cache": self.state_dir / "dividend_dashboard_cache.json",
            "feature_inventory": self.state_dir / "feature_inventory.json",
            "order_history_cache": self.state_dir / "toss_order_history_cache.json"
        }

        # Check explicit files
        for file_type, path in files_to_check.items():
            if not path:
                continue
            diag = self.check_file(file_type, path)
            diagnoses[file_type] = diag
            if diag["status"] != "healthy":
                anomalies_found += 1

        # Check dividend cache directory
        dividend_cache_dir = self.state_dir / "dividend_cache"
        div_cache_diagnoses = []
        if dividend_cache_dir.exists():
            for p in dividend_cache_dir.glob("*.json"):
                diag = self.check_file("dividend_cache", p)
                if diag["status"] != "healthy":
                    div_cache_diagnoses.append({
                        "file": p.name,
                        "diagnosis": diag
                    })
                    anomalies_found += 1
        diagnoses["dividend_cache_details"] = div_cache_diagnoses

        # Check CSV Fallback Stale check
        csv_path = self.project_root / "toss_portfolio.csv"
        csv_diag = {"status": "healthy", "reason": "not_present"}
        if csv_path.exists():
            mtime = csv_path.stat().st_mtime
            age_days = (time.time() - mtime) / 86400.0
            if age_days > 7.0:
                csv_diag = {
                    "status": "warning",
                    "reason": "stale_fallback",
                    "age_days": round(age_days, 1),
                    "guide": "toss_portfolio.csv 파일이 7일 이상 갱신되지 않았습니다. 최신 보유 계좌 상태인지 확인하세요."
                }
                anomalies_found += 1
            else:
                csv_diag = {
                    "status": "healthy",
                    "reason": "recent",
                    "age_days": round(age_days, 1)
                }
        diagnoses["toss_portfolio_csv"] = csv_diag

        return {
            "diagnosed_at": time.time(),
            "healthy": anomalies_found == 0,
            "anomalies_count": anomalies_found,
            "reports": diagnoses
        }

    def check_file(self, file_type: str, path: Path) -> dict[str, Any]:
        """Checks structural integrity and freshness of a single state file."""
        if not path.exists():
            return {
                "status": "warning",
                "reason": "missing",
                "path": str(path.relative_to(self.project_root)),
                "guide": f"필수 상태 파일 {path.name}이 없습니다. 시스템 작동 시 자동으로 생성되지만, 수동 조치하려면 Toss API 조회 또는 cli를 구동하세요."
            }

        # 1. Parse JSON check
        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                return {
                    "status": "corrupted",
                    "reason": "empty_file",
                    "path": str(path.relative_to(self.project_root)),
                    "guide": f"파일이 비어 있습니다. 해당 파일을 삭제한 후 API를 다시 구동하여 신규 세팅되도록 하십시오."
                }
            data = json.loads(content)
        except json.JSONDecodeError as e:
            return {
                "status": "corrupted",
                "reason": f"json_decode_error: {e}",
                "path": str(path.relative_to(self.project_root)),
                "guide": f"JSON 형식이 손상되었습니다. 백업이 있다면 복구하고, 없다면 파일을 삭제하여 재생성되도록 유도하십시오."
            }

        # 2. Structural validation
        is_valid, err = validate_state_structure(file_type, data)
        if not is_valid:
            return {
                "status": "invalid_schema",
                "reason": err,
                "path": str(path.relative_to(self.project_root)),
                "guide": f"스키마가 유효하지 않습니다. 'state_migration_runner'를 사용하여 최신 구조로 마이그레이션하거나 데이터를 초기화하세요."
            }

        # 3. Freshness check
        mtime = path.stat().st_mtime
        age_hours = (time.time() - mtime) / 3600.0

        # Different freshness thresholds
        thresholds = {
            "toss_account_snapshot": 24.0,  # 24 hours
            "dividend_cache": 168.0,        # 7 days
            "dashboard_cache": 2.0,         # 2 hours
            "order_history_cache": 24.0     # 24 hours
        }

        limit = thresholds.get(file_type, 720.0)
        if age_hours > limit:
            return {
                "status": "stale",
                "reason": f"cache_expired ({age_hours:.1f} hours old, limit: {limit} hours)",
                "path": str(path.relative_to(self.project_root)),
                "guide": f"데이터가 너무 오래되었습니다({age_hours:.1f}시간 경과). 강제 캐시 갱신 기능을 구동하여 최신 데이터를 다운로드하십시오."
            }

        return {
            "status": "healthy",
            "reason": "valid_and_fresh",
            "path": str(path.relative_to(self.project_root)),
            "age_hours": round(age_hours, 2)
        }
