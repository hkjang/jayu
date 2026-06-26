from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .paths import RuntimePaths
from .settings import Settings


class NextCommandRecommender:
    def __init__(self, settings: Settings, paths: RuntimePaths):
        self.settings = settings
        self.paths = paths

    def recommend(self) -> dict[str, Any]:
        """Analyzes the current system state and recommends the next CLI command
        with Korean explanations.
        """
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        today_compact = datetime.now(UTC).strftime("%Y%m%d")
        
        # 1. Check config validity / settings
        try:
            # Try parsing the settings file if it exists
            config_file = self.paths.project_root / "configs" / "settings.json"
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    json.load(f)
        except Exception as e:
            return {
                "command": "uv run jayu validate-config",
                "reason": "설정 파일(settings.json)에 구문 오류가 감지되었습니다.",
                "expected_result": "설정 파일의 구문 오류를 진단하고 세부 유효성 검사를 수행합니다.",
            }

        # 2. Check if today's signal is generated
        # Signals can be in signals/ or signals/shadow/ or signals/paper/ etc. depending on mode
        mode = self.settings.mode
        signal_dir = self.paths.signals_dir
        if mode == "shadow":
            signal_file = signal_dir / "shadow" / f"{today_str}.json"
        elif mode == "paper":
            signal_file = signal_dir / "paper" / f"{today_str}.json"
        else:
            signal_file = signal_dir / f"{today_str}.json"

        if not signal_file.exists() and not self.paths.signal_file.exists():
            return {
                "command": f"uv run jayu signal --mode {mode}",
                "reason": f"오늘({today_str})의 {mode} 투자 신호가 아직 생성되지 않았습니다.",
                "expected_result": "오늘의 시장 데이터를 수집하여 전략별 투자 신호를 생성하고 리스크 필터를 통과시킵니다.",
            }

        # 3. Check if today's report is built
        # Reports are typically saved in reports/ or run directories
        report_file = self.paths.project_root / "reports" / f"report_{today_str}.html"
        if not report_file.exists():
            return {
                "command": "uv run jayu report build",
                "reason": "오늘 생성된 신호에 대한 성과 및 운영 요약 보고서가 빌드되지 않았습니다.",
                "expected_result": "최신 신호와 시뮬레이션 결과를 기반으로 대시보드 및 HTML 요약 보고서를 생성합니다.",
            }

        # 4. Check if shadow-to-live promotion is eligible
        # If in shadow mode, check if we can run promotion check
        if mode == "shadow":
            promotion_file = self.paths.state_dir / "promotion.json"
            if promotion_file.exists():
                try:
                    with open(promotion_file, "r", encoding="utf-8") as f:
                        promo_data = json.load(f)
                        if promo_data.get("eligible") is True:
                            return {
                                "command": "uv run jayu promotion check",
                                "reason": "현재 shadow 전략의 성과가 기준을 만족하여 live 운영 환경으로 승격(Promotion)할 준비가 되었습니다.",
                                "expected_result": "승격 조건 충족 여부를 최종 검증하고 live 환경으로 자동 승격을 실행합니다.",
                            }
                except Exception:
                    pass

        # 5. Check if backup is needed (older than 7 days)
        backup_dir = self.paths.state_dir / "backups"
        backup_needed = True
        if backup_dir.exists():
            backups = list(backup_dir.glob("*.zip"))
            if backups:
                # Get the most recent backup
                latest_backup = max(backups, key=lambda p: p.stat().st_mtime)
                mtime = datetime.fromtimestamp(latest_backup.stat().st_mtime, UTC)
                if datetime.now(UTC) - mtime < timedelta(days=7):
                    backup_needed = False

        if backup_needed:
            return {
                "command": "uv run jayu backup create",
                "reason": "최근 7일간 시스템 설정 및 운영 데이터 백업이 수행되지 않았습니다.",
                "expected_result": "현재 상태, 실행 로그, 데이터 마트 및 설정을 포함하는 압축 백업 파일과 체크섬을 생성합니다.",
            }

        # Default fallback: check system status
        return {
            "command": "uv run jayu status",
            "reason": "현재 오늘 루틴 및 백업 상태가 모두 양호합니다. 전체 시스템의 세부 건강 상태 점검을 추천합니다.",
            "expected_result": "데이터 제공자 SLA, 리스크 원장, 스케줄러 루틴 및 종합 SLO 점수를 리포트합니다.",
        }
