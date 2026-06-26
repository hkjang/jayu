from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
from jayu.paths import RuntimePaths
from jayu.io import read_json

def resolve_run_dir(paths: RuntimePaths, run_id: str) -> Path | None:
    """실행 ID를 실행 디렉토리 경로로 해소합니다. 'latest'는 최신 실행, 'previous'는 그 이전 실행을 뜻합니다."""
    if not paths.runs_dir.exists():
        return None
    
    # manifest.json을 포함하는 유효한 실행 디렉토리 목록 스캔
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
                
    # 시간 순으로 정렬 (최신이 첫 번째)
    valid_runs.sort(key=lambda x: x["time"], reverse=True)
    
    if not valid_runs:
        return None
        
    if run_id == "latest":
        return valid_runs[0]["dir"]
    elif run_id == "previous":
        return valid_runs[1]["dir"] if len(valid_runs) > 1 else None
        
    # 특정 run_id 매칭 시도 (디렉토리명 또는 manifest 내 run_id)
    for run in valid_runs:
        d = run["dir"]
        if d.name == run_id:
            return d
        manifest = read_json(d / "manifest.json", default={})
        if manifest.get("run_id") == run_id:
            return d
            
    return None

def compare_runs(paths: RuntimePaths, left_id: str, right_id: str) -> dict[str, Any]:
    """두 실행(left vs right)의 설정, 데이터 품질, 신호, 리스크, 의사결정, 산출물 차이를 비교합니다."""
    left_dir = resolve_run_dir(paths, left_id)
    right_dir = resolve_run_dir(paths, right_id)
    
    if not left_dir:
        raise ValueError(f"왼쪽 실행(left)을 찾을 수 없습니다: {left_id}")
    if not right_dir:
        raise ValueError(f"오른쪽 실행(right)을 찾을 수 없습니다: {right_id}")
        
    left_name = left_dir.name
    right_name = right_dir.name
    
    # 1. 파일 로드 (None 방지를 위해 or {} 적용)
    left_manifest = read_json(left_dir / "manifest.json", default={}) or {}
    right_manifest = read_json(right_dir / "manifest.json", default={}) or {}
    
    left_verdict = read_json(left_dir / "safety_verdict.json", default={}) or {}
    right_verdict = read_json(right_dir / "safety_verdict.json", default={}) or {}
    
    left_dq = read_json(left_dir / "data_sources.json", default={}) or {}
    right_dq = read_json(right_dir / "data_sources.json", default={}) or {}
    
    left_disagree = read_json(left_dir / "provider_disagreement_report.json", default={}) or {}
    right_disagree = read_json(right_dir / "provider_disagreement_report.json", default={}) or {}
    
    left_signals = read_json(left_dir / "signals_risk.json", default={}) or {}
    right_signals = read_json(right_dir / "signals_risk.json", default={}) or {}
    
    left_risk = read_json(left_dir / "risk_explanation.json", default={}) or {}
    right_risk = read_json(right_dir / "risk_explanation.json", default={}) or {}
    
    # 2. 설정 비교
    left_config_hash = left_manifest.get("config_hash") or "N/A"
    right_config_hash = right_manifest.get("config_hash") or "N/A"
    config_changed = left_config_hash != right_config_hash
    
    # 3. 데이터 품질 비교
    left_data_hash = (left_manifest.get("result") or {}).get("data_hash") or "N/A"
    right_data_hash = (right_manifest.get("result") or {}).get("data_hash") or "N/A"
    data_changed = left_data_hash != right_data_hash
    
    # 제공자 불일치(Disagreement) 개수 비교
    left_disagree_count = len((left_disagree or {}).get("disagreements") or [])
    right_disagree_count = len((right_disagree or {}).get("disagreements") or [])
    
    # 데이터 소스 상태 비교
    left_sources = (left_dq or {}).get("sources") or []
    right_sources = (right_dq or {}).get("sources") or []
    left_success_sources = sum(1 for s in left_sources if isinstance(s, dict) and s.get("status") == "success")
    right_success_sources = sum(1 for s in right_sources if isinstance(s, dict) and s.get("status") == "success")
    
    # 4. 신호(Signals) 비교
    left_sig_count = len(left_signals) if isinstance(left_signals, dict) else 0
    right_sig_count = len(right_signals) if isinstance(right_signals, dict) else 0
    
    left_buy_count = 0
    if isinstance(left_signals, dict):
        left_buy_count = sum(1 for s in left_signals.values() if isinstance(s, dict) and s.get("action") == "buy")
    right_buy_count = 0
    if isinstance(right_signals, dict):
        right_buy_count = sum(1 for s in right_signals.values() if isinstance(s, dict) and s.get("action") == "buy")
        
    left_eligible_count = 0
    if isinstance(left_signals, dict):
        left_eligible_count = sum(1 for s in left_signals.values() if isinstance(s, dict) and s.get("eligible") is True)
    right_eligible_count = 0
    if isinstance(right_signals, dict):
        right_eligible_count = sum(1 for s in right_signals.values() if isinstance(s, dict) and s.get("eligible") is True)
        
    left_blocked_count = 0
    if isinstance(left_signals, dict):
        left_blocked_count = sum(1 for s in left_signals.values() if isinstance(s, dict) and s.get("blocked") is True)
    right_blocked_count = 0
    if isinstance(right_signals, dict):
        right_blocked_count = sum(1 for s in right_signals.values() if isinstance(s, dict) and s.get("blocked") is True)
    
    # 5. 리스크 게이트 비교
    left_risk_status = left_verdict.get("overall") or "unknown"
    right_risk_status = right_verdict.get("overall") or "unknown"
    
    left_risk_blocked = (left_risk or {}).get("blocked_count") or 0
    right_risk_blocked = (right_risk or {}).get("blocked_count") or 0
    left_risk_approved = (left_risk or {}).get("approved_count") or 0
    right_risk_approved = (right_risk or {}).get("approved_count") or 0
    
    # 6. 의사결정 비교
    left_status = left_manifest.get("status") or "unknown"
    right_status = right_manifest.get("status") or "unknown"
    
    left_reasons = (left_verdict or {}).get("reasons") or []
    right_reasons = (right_verdict or {}).get("reasons") or []
    left_blockers = [r.get("code") for r in left_reasons if isinstance(r, dict) and r.get("code")]
    right_blockers = [r.get("code") for r in right_reasons if isinstance(r, dict) and r.get("code")]
    
    # 7. 필수 산출물 완성도 체크
    required_files = [
        "manifest.json",
        "data_sources.json",
        "provider_disagreement_report.json",
        "signals_risk.json",
        "risk_explanation.json",
        "safety_verdict.json",
        "promotion.json"
    ]
    left_artifacts = {f: (left_dir / f).exists() for f in required_files}
    right_artifacts = {f: (right_dir / f).exists() for f in required_files}
    
    left_completeness = sum(1 for exists in left_artifacts.values() if exists) / len(required_files) * 100
    right_completeness = sum(1 for exists in right_artifacts.values() if exists) / len(required_files) * 100

    # 8. 종합 설명 생성 (한국어)
    explanation = []
    if left_status != right_status or left_risk_status != right_risk_status:
        explanation.append(f"의사결정 결과가 '{left_status}/{left_risk_status}'에서 '{right_status}/{right_risk_status}'(으)로 변경되었습니다.")
    else:
        explanation.append("의사결정 및 리스크 상태는 동일하게 유지되었습니다.")
        
    if config_changed:
        explanation.append(f"설정 파일 해시가 변경되었습니다. 이전: {left_config_hash[:8]} -> 현재: {right_config_hash[:8]}")
    if data_changed:
        explanation.append(f"수집된 데이터 해시가 변경되었습니다. 이전: {left_data_hash[:8]} -> 현재: {right_data_hash[:8]}")
        
    if left_disagree_count != right_disagree_count:
        explanation.append(f"제공자 간 불일치 종목 수가 {left_disagree_count}개에서 {right_disagree_count}개로 변경되었습니다.")
        
    if left_sig_count != right_sig_count:
        explanation.append(f"생성된 총 신호 수가 {left_sig_count}개에서 {right_sig_count}개로 변화하였습니다.")
        
    if left_eligible_count != right_eligible_count:
        explanation.append(f"최종 진입 승인 종목 수가 {left_eligible_count}개에서 {right_eligible_count}개로 변경되었습니다.")
        
    # 차단 사유 비교 설명
    added_blockers = set(right_blockers) - set(left_blockers)
    removed_blockers = set(left_blockers) - set(right_blockers)
    if added_blockers:
        explanation.append(f"새로운 차단 사유가 감지되었습니다: {', '.join(added_blockers)}")
    if removed_blockers:
        explanation.append(f"이전 차단 사유가 해결되었습니다: {', '.join(removed_blockers)}")

    return {
        "left_run_id": left_name,
        "right_run_id": right_name,
        "config": {
            "left_hash": left_config_hash,
            "right_hash": right_config_hash,
            "changed": config_changed
        },
        "data_quality": {
            "left_hash": left_data_hash,
            "right_hash": right_data_hash,
            "changed": data_changed,
            "left_disagreements": left_disagree_count,
            "right_disagreements": right_disagree_count,
            "left_success_sources": left_success_sources,
            "right_success_sources": right_success_sources,
        },
        "signals": {
            "left_total": left_sig_count,
            "right_total": right_sig_count,
            "left_buy": left_buy_count,
            "right_buy": right_buy_count,
            "left_eligible": left_eligible_count,
            "right_eligible": right_eligible_count,
            "left_blocked": left_blocked_count,
            "right_blocked": right_blocked_count,
        },
        "risk": {
            "left_status": left_risk_status,
            "right_status": right_risk_status,
            "left_blocked": left_risk_blocked,
            "right_blocked": right_risk_blocked,
            "left_approved": left_risk_approved,
            "right_approved": right_risk_approved,
            "left_blockers": left_blockers,
            "right_blockers": right_blockers,
        },
        "artifacts": {
            "left_completeness": round(left_completeness, 1),
            "right_completeness": round(right_completeness, 1),
            "left_files": left_artifacts,
            "right_files": right_artifacts,
        },
        "decision": {
            "left_status": left_status,
            "right_status": right_status,
            "explanation": " ".join(explanation)
        }
    }

def generate_compare_markdown(diff: dict[str, Any]) -> str:
    """비교 데이터 리포트를 마크다운 형식의 한국어로 생성합니다."""
    left = diff["left_run_id"]
    right = diff["right_run_id"]
    
    md = []
    md.append(f"# Jayu Run 실행 비교 보고서")
    md.append(f"- **대상 실행**: `{left}` (이전/왼쪽) vs `{right}` (현재/오른쪽)\n")
    
    md.append("## 1. 종합 요약 (Decision & Summary)")
    md.append(f"> [!NOTE]\n> {diff['decision']['explanation']}\n")
    
    md.append("| 항목 | 이전 실행 (`{}`) | 현재 실행 (`{}`) | 변경 여부 |".format(left, right))
    md.append("| :--- | :--- | :--- | :--- |")
    md.append(f"| **실행 상태** | `{diff['decision']['left_status']}` | `{diff['decision']['right_status']}` | {'⚠️ 변경됨' if diff['decision']['left_status'] != diff['decision']['right_status'] else '동일'} |")
    md.append(f"| **설정 해시** | `{diff['config']['left_hash'][:8]}` | `{diff['config']['right_hash'][:8]}` | {'⚠️ 변경됨' if diff['config']['changed'] else '동일'} |")
    md.append(f"| **데이터 해시** | `{diff['data_quality']['left_hash'][:8]}` | `{diff['data_quality']['right_hash'][:8]}` | {'⚠️ 변경됨' if diff['data_quality']['changed'] else '동일'} |")
    md.append(f"| **리스크 판정** | `{diff['risk']['left_status']}` | `{diff['risk']['right_status']}` | {'⚠️ 변경됨' if diff['risk']['left_status'] != diff['risk']['right_status'] else '동일'} |")
    md.append(f"| **증거 완성도** | `{diff['artifacts']['left_completeness']}%` | `{diff['artifacts']['right_completeness']}%` | {'⚠️ 변경됨' if diff['artifacts']['left_completeness'] != diff['artifacts']['right_completeness'] else '동일'} |\n")
    
    md.append("## 2. 데이터 품질 상세 (Data Quality)")
    md.append(f"- **성공 데이터 소스 수**: `{diff['data_quality']['left_success_sources']}` -> `{diff['data_quality']['right_success_sources']}`")
    md.append(f"- **제공자 간 불일치(Disagreement) 수**: `{diff['data_quality']['left_disagreements']}` -> `{diff['data_quality']['right_disagreements']}`\n")
    
    md.append("## 3. 매매 신호 비교 (Signals)")
    md.append("| 구분 | 이전 실행 (`{}`) | 현재 실행 (`{}`) | 차이 |".format(left, right))
    md.append("| :--- | :---: | :---: | :---: |")
    md.append(f"| 총 신호 종목 수 | {diff['signals']['left_total']} | {diff['signals']['right_total']} | {diff['signals']['right_total'] - diff['signals']['left_total']:+d} |")
    md.append(f"| 매수(Buy) 신호 수 | {diff['signals']['left_buy']} | {diff['signals']['right_buy']} | {diff['signals']['right_buy'] - diff['signals']['left_buy']:+d} |")
    md.append(f"| 최종 승인(Eligible) 수 | {diff['signals']['left_eligible']} | {diff['signals']['right_eligible']} | {diff['signals']['right_eligible'] - diff['signals']['left_eligible']:+d} |")
    md.append(f"| 리스크 차단(Blocked) 수 | {diff['signals']['left_blocked']} | {diff['signals']['right_blocked']} | {diff['signals']['right_blocked'] - diff['signals']['left_blocked']:+d} |\n")
    
    md.append("## 4. 리스크 차단 내역 (Risk Gate Blockers)")
    left_bl = diff['risk']['left_blockers']
    right_bl = diff['risk']['right_blockers']
    md.append(f"- **이전 차단 사유**: `{', '.join(left_bl) if left_bl else '없음'}`")
    md.append(f"- **현재 차단 사유**: `{', '.join(right_bl) if right_bl else '없음'}`\n")
    
    md.append("## 5. 증거 산출물 체크 (Artifacts)")
    md.append("| 산출물 파일명 | 이전 존재 여부 | 현재 존재 여부 |")
    md.append("| :--- | :---: | :---: |")
    for fname in sorted(diff["artifacts"]["left_files"].keys()):
        left_has = "✅ 있음" if diff["artifacts"]["left_files"][fname] else "❌ 없음"
        right_has = "✅ 있음" if diff["artifacts"]["right_files"][fname] else "❌ 없음"
        md.append(f"| `{fname}` | {left_has} | {right_has} |")
        
    return "\n".join(md)
