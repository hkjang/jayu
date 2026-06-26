from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from jayu.paths import RuntimePaths
from jayu.io import read_json, atomic_write_json
from jayu.run_compare import resolve_run_dir, compare_runs

def build_decision_diff(paths: RuntimePaths, run_id: str = "latest") -> dict[str, Any]:
    """이전 실행과 현재 실행을 비교하여 의사결정의 변화 내역(Decision Diff)을 생성하고 decision_diff.json에 저장합니다."""
    latest_dir = resolve_run_dir(paths, run_id)
    if not latest_dir:
        return _empty_diff_payload("latest", "N/A")
        
    # 유효한 실행 디렉토리 목록 스캔 및 시간 순 정렬
    valid_runs = []
    for d in paths.runs_dir.iterdir():
        if d.is_dir() and (d / "manifest.json").exists():
            manifest = read_json(d / "manifest.json", default={})
            if manifest:
                started = manifest.get("started_at") or ""
                finished = manifest.get("finished_at") or ""
                valid_runs.append({
                    "dir": d,
                    "time": finished or started or d.name
                })
    valid_runs.sort(key=lambda x: x["time"], reverse=True)
    
    # 만약 현재 실행이 최신이 아니라 특정 run_id라면, 그 실행의 인덱스를 찾아 그 바로 다음 실행(이전 실행)을 비교군으로 삼음
    prev_dir = None
    try:
        dir_names = [r["dir"].name for r in valid_runs]
        idx = dir_names.index(latest_dir.name)
        if idx + 1 < len(valid_runs):
            prev_dir = valid_runs[idx + 1]["dir"]
    except ValueError:
        pass
        
    if not prev_dir:
        # 이전 실행이 없으면 빈 비교 결과 생성
        payload = _empty_diff_payload(latest_dir.name, "N/A")
        atomic_write_json(latest_dir / "decision_diff.json", payload)
        return payload
        
    # 두 실행 비교 수행
    try:
        diff_data = compare_runs(paths, prev_dir.name, latest_dir.name)
    except Exception as e:
        # 예외 발생 시 에러용 페이로드 반환
        payload = _empty_diff_payload(latest_dir.name, prev_dir.name, error=str(e))
        atomic_write_json(latest_dir / "decision_diff.json", payload)
        return payload
        
    left_status = diff_data["decision"]["left_status"]
    right_status = diff_data["decision"]["right_status"]
    left_risk = diff_data["risk"]["left_status"]
    right_risk = diff_data["risk"]["right_status"]
    
    overall_changed = (left_status != right_status) or (left_risk != right_risk)
    
    left_blockers = diff_data["risk"]["left_blockers"]
    right_blockers = diff_data["risk"]["right_blockers"]
    added_blockers = list(set(right_blockers) - set(left_blockers))
    removed_blockers = list(set(left_blockers) - set(right_blockers))
    
    # 신호 종목 변화 추적
    left_signals = read_json(prev_dir / "signals_risk.json", default={})
    right_signals = read_json(latest_dir / "signals_risk.json", default={})
    
    left_tickers = list(left_signals.keys())
    right_tickers = list(right_signals.keys())
    added_tickers = list(set(right_tickers) - set(left_tickers))
    removed_tickers = list(set(left_tickers) - set(right_tickers))
    
    # 한국어 메시지 조립
    messages = []
    if overall_changed:
        messages.append(f"의사결정 결과가 '{left_status}/{left_risk}'에서 '{right_status}/{right_risk}'(으)로 변경되었습니다.")
    else:
        messages.append(f"전체 의사결정 판결은 '{right_status}/{right_risk}' 상태로 유지되었습니다.")
        
    if added_blockers:
        messages.append(f"새롭게 차단 사유로 감지된 항목: {', '.join(added_blockers)}")
    if removed_blockers:
        messages.append(f"차단이 해제된 항목: {', '.join(removed_blockers)}")
        
    if added_tickers or removed_tickers:
        messages.append(f"신호 대상 종목에 변화가 있습니다. (추가: {len(added_tickers)}개, 제외: {len(removed_tickers)}개)")
        
    # 권장 액션 가이드 작성
    recommended_action_text = "이전 실행 결과와 변동이 없습니다. 정상 가이드라인에 따라 운영해 주세요."
    if right_status == "failed" or right_risk == "blocked":
        if added_blockers:
            recommended_action_text = f"새로운 차단 조건인 {', '.join(added_blockers)} 해결을 위해 데이터 무결성 또는 리스크 설정치를 점검하십시오."
        else:
            recommended_action_text = "리스크 관리 규칙 미충족 조건을 검토하고 복구 가이드를 따르십시오."
    elif right_status == "success" and left_status != "success":
        recommended_action_text = "리스크 게이트 및 데이터 정합성 불일치가 모두 해소되어 정상 거래 준비 상태가 되었습니다. 신호를 확인해 주세요."
        
    payload = {
        "left_run_id": prev_dir.name,
        "right_run_id": latest_dir.name,
        "overall_changed": overall_changed,
        "left_status": f"{left_status}/{left_risk}",
        "right_status": f"{right_status}/{right_risk}",
        "explanation": " ".join(messages),
        "blockers": {
            "added": added_blockers,
            "removed": removed_blockers,
            "changed": len(added_blockers) > 0 or len(removed_blockers) > 0
        },
        "affected_tickers": {
            "added": added_tickers,
            "removed": removed_tickers,
            "changed": len(added_tickers) > 0 or len(removed_tickers) > 0
        },
        "recommended_action": {
            "text": recommended_action_text
        }
    }
    
    # JSON 파일로 저장
    atomic_write_json(latest_dir / "decision_diff.json", payload)
    return payload

def _empty_diff_payload(latest_id: str, prev_id: str, error: str | None = None) -> dict[str, Any]:
    """비교할 이전 런이 없거나 오류가 발생했을 때의 기본 페이로드를 생성합니다."""
    explanation = "비교 가능한 이전 실행 기록이 없어 판단 변화 내역을 제공할 수 없습니다."
    if error:
        explanation = f"실행 비교 중 오류가 발생했습니다: {error}"
    return {
        "left_run_id": prev_id,
        "right_run_id": latest_id,
        "overall_changed": False,
        "left_status": "N/A",
        "right_status": "N/A",
        "explanation": explanation,
        "blockers": {
            "added": [],
            "removed": [],
            "changed": False
        },
        "affected_tickers": {
            "added": [],
            "removed": [],
            "changed": False
        },
        "recommended_action": {
            "text": "이전 실행 기록이 존재하지 않거나 단일 실행 상태입니다."
        }
    }
