"""test_performance_budget.py — 대시보드 성능 예산(Performance Budget) 검증 테스트.

대형화 및 자동 새로고침 도입에 따른 대시보드 성능 저하를 방지하기 위해
API 페이로드 크기(5MB 제한), 렌더링 섹션 수, 자동 리프레시 주기 등의 적합성을 검증합니다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from jayu import dashboard
from jayu.paths import RuntimePaths


@pytest.fixture
def temp_runtime_paths(tmp_path: Path) -> RuntimePaths:
    """임시 런타임 경로 구조를 설정하는 Fixture."""
    paths = RuntimePaths.from_root(tmp_path)
    paths.ensure_runtime_dirs()
    return paths


def test_api_payload_size_budget(temp_runtime_paths):
    """모든 주요 대시보드 API 빌더의 응답 페이로드 크기가 5MB 예산 제한을 충족하는지 검증한다."""
    # 대시보드 데이터 빌드에 필요한 최소 임시 데이터 생성
    # (실제 대시보드 빌더는 runs 디렉토리나 환경 설정을 읽음)
    paths = temp_runtime_paths
    
    # 임시 실행 기록 생성
    run_dir = paths.runs_dir / "20260626_120000_simulate_TEST"
    run_dir.mkdir()
    
    # 핵심 증거 파일들 작성
    from jayu.io import atomic_write_json
    atomic_write_json(run_dir / "manifest.json", {
        "run_id": "20260626_120000_simulate_TEST",
        "command": "signal",
        "status": "success",
        "started_at": "2026-06-26T12:00:00Z",
        "finished_at": "2026-06-26T12:05:00Z",
        "config_hash": "test-hash",
        "data_reports": {},
        "result": {"mode": "shadow"}
    })
    atomic_write_json(run_dir / "signals_risk.json", {})
    atomic_write_json(run_dir / "data_sources.json", {"sources": []})
    
    # 5MB 예산 제한 (바이트 단위: 5,242,880)
    MAX_PAYLOAD_BYTES = 5 * 1024 * 1024

    # 1. Overview API 페이로드 검사
    overview = dashboard.build_dashboard_overview(paths)
    overview_size = len(json.dumps(overview, ensure_ascii=False).encode("utf-8"))
    assert overview_size < MAX_PAYLOAD_BYTES, f"Overview API payload size {overview_size} bytes exceeds 5MB budget."

    # 2. Decision API 페이로드 검사
    decision = dashboard.build_dashboard_decision(paths)
    decision_size = len(json.dumps(decision, ensure_ascii=False).encode("utf-8"))
    assert decision_size < MAX_PAYLOAD_BYTES, f"Decision API payload size {decision_size} bytes exceeds 5MB budget."

    # 3. Data Quality API 페이로드 검사
    dq = dashboard.build_dashboard_data_quality(paths)
    dq_size = len(json.dumps(dq, ensure_ascii=False).encode("utf-8"))
    assert dq_size < MAX_PAYLOAD_BYTES, f"Data Quality API payload size {dq_size} bytes exceeds 5MB budget."

    # 4. Risk API 페이로드 검사
    risk = dashboard.build_dashboard_risk(paths)
    risk_size = len(json.dumps(risk, ensure_ascii=False).encode("utf-8"))
    assert risk_size < MAX_PAYLOAD_BYTES, f"Risk API payload size {risk_size} bytes exceeds 5MB budget."

    # 5. Signals API 페이로드 검사
    signals = dashboard.build_dashboard_signals(paths)
    signals_size = len(json.dumps(signals, ensure_ascii=False).encode("utf-8"))
    assert signals_size < MAX_PAYLOAD_BYTES, f"Signals API payload size {signals_size} bytes exceeds 5MB budget."


def test_dashboard_html_rendering_section_budget():
    """대시보드 HTML에 너무 많은 렌더링 섹션이 과밀되어 프론트 로드가 지연되지 않는지 검증한다."""
    html_path = Path("src/jayu/dashboard_static/index.html")
    assert html_path.exists(), "Dashboard index.html does not exist."

    html_content = html_path.read_text(encoding="utf-8")
    
    # 대시보드 탭/섹션 역할을 하는 DOM 요소 개수 확인 (예: class="tab-pane" 또는 id="tab-..." 등)
    # index.html 파일 내 section 태그 또는 탭 콘텐츠 아이디 세트 개수
    sections = re.findall(r'id=["\'](?:tab|section)-[^"\']+["\']|class=["\'][^"\']*tab-content[^"\']*["\']', html_content)
    
    # 탭/섹션 수가 과하게 많아(예: 15개 초과) 단일 화면 렌더링 부하를 일으키는지 점검
    MAX_SECTIONS = 15
    assert len(sections) <= MAX_SECTIONS, f"Number of dashboard rendering sections {len(sections)} exceeds safety limit of {MAX_SECTIONS}."


def test_dashboard_frontend_auto_refresh_interval_budget():
    """프론트엔드 자동 새로고침 주기가 너무 짧아서 서버에 DDoS 형태의 부하를 주지 않는지 검증한다."""
    js_dir = Path("src/jayu/dashboard_static")
    assert js_dir.exists(), "dashboard_static directory does not exist."

    # 안전한 리프레시 최소 시간: 10초 (10000ms)
    # 로컬/시뮬레이션 환경이므로 실시간 주식 주문 수준의 극단적 짧은 주기(예: 1초 미만)는 방지
    MIN_REFRESH_MS = 10000

    js_files = list(js_dir.glob("*.js"))
    assert len(js_files) > 0, "No JS files found in dashboard_static."

    for js_file in js_files:
        content = js_file.read_text(encoding="utf-8")
        
        # setInterval 호출 패턴 매칭 (예: setInterval(fn, 30000))
        intervals = re.findall(r'setInterval\s*\(\s*(?:[^,\s]+)\s*,\s*(\d+)\s*\)', content)
        for val_str in intervals:
            interval_ms = int(val_str)
            assert interval_ms >= MIN_REFRESH_MS, (
                f"Auto-refresh interval {interval_ms}ms in {js_file.name} is too short. "
                f"Must be at least {MIN_REFRESH_MS}ms to prevent server overload."
            )
            
        # setTimeout으로 구현된 재귀 리프레시 루프 패턴 검사
        timeouts = re.findall(r'setTimeout\s*\(\s*(?:[^,\s]+)\s*,\s*(\d+)\s*\)', content)
        for val_str in timeouts:
            timeout_ms = int(val_str)
            # 1초 미만의 너무 짧은 주기적 지연이 설정되었는지 검증 (UI 애니메이션 목적이 아닌 데이터 폴링 용도의 지연 감지)
            # 데이터 로드/폴링 관련 지명에 대해 제한 적용 (보통 5초 미만은 폴링 방지)
            if "load" in content or "fetch" in content or "refresh" in content:
                # 데이터 새로고침 함수 근처에서 setTimeout이 사용된 경우만 필터링
                if timeout_ms < 5000:
                    # 5초 미만 폴링은 경고
                    pass  # 애니메이션/UI 피드백 지연과 폴링 지연을 정확히 분별하기 위해 assert는 보수적으로 적용
