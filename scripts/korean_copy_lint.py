#!/usr/bin/env python3
"""korean_copy_lint.py — 한국어 투자 판단 OS 카피 품질 검증 도구.

이 스크립트는 대시보드 라벨, 메트릭 사전(metric_dictionary), 복구 가이드(recovery_guide) 등
사용자 인터페이스 문구에서 다음 항목을 점검합니다:
1. 한국어 설명 누락 (설명이 비어있거나 None인 경우)
2. 영어만 있는 문구 (한국어 문자가 하나도 없고 영문자만 있는 경우)
3. 너무 긴 문장 (100자 초과)
4. 전문용어 과다 사용 우려가 있는 경우 (한글 문장 내 영어 단어가 지나치게 섞여 있는 경우)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

# 프로젝트 루트 경로 추가
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from jayu.metric_dictionary import METRIC_DEFINITIONS
from jayu.recovery_guide import PLAYBOOKS


def has_hangul(text: str) -> bool:
    """텍스트에 한글 문자가 포함되어 있는지 판별한다."""
    return any(0xAC00 <= ord(char) <= 0xD7A3 for char in text)


def is_english_only(text: str) -> bool:
    """텍스트가 한글 없이 영어 알파벳으로만 구성되어 있는지 판별한다 (숫자/공백/기호 제외)."""
    clean_text = re.sub(r"[^a-zA-Z\uAC00-\uD7A3]", "", text)
    if not clean_text:
        return False
    return any(c.isalpha() for c in clean_text) and not has_hangul(clean_text)


def check_sentence_length(text: str, max_len: int = 100) -> list[str]:
    """문장이 최대 길이를 초과하는지 검사하고 초과된 문장 리스트를 반환한다."""
    issues = []
    # 마침표, 물음표 등으로 문장 단위 분할
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for idx, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if len(sentence) > max_len:
            issues.append(f"문장 길이 초과 ({len(sentence)}자): '{sentence[:30]}...'")
    return issues


def check_jargon_ratio(text: str) -> list[str]:
    """한글 문장 내 영어 단어 비중이 지나치게 높은지 검사한다."""
    words = text.split()
    if len(words) < 5:
        return []
    
    english_words = [w for w in words if re.match(r"^[a-zA-Z0-9_\-]+$", re.sub(r"[^\w]", "", w))]
    ratio = len(english_words) / len(words)
    if ratio > 0.4:  # 단어의 40% 이상이 영어인 경우
        return [f"전문용어/영어 비중 과다 ({ratio*100:.1f}%): '{text[:30]}...'"]
    return []


def run_lint() -> int:
    errors = 0
    warnings = 0

    print("==================================================")
    print("      Jayu 한국어 투자 판단 OS 카피 린터 작동      ")
    print("==================================================")

    # 1. 메트릭 사전 (Metric Dictionary) 검사
    print("\n[1] 메트릭 사전 (Metric Dictionary) 검증 중...")
    for idx, metric in enumerate(METRIC_DEFINITIONS):
        context = f"Metric '{metric.key}' ({metric.group})"
        
        # 필수 한글 필드 검사
        fields_to_check = {
            "label": metric.label,
            "plain_name": metric.plain_name,
            "short_description": metric.short_description,
            "good_value": metric.good_value,
            "watch_out": metric.watch_out,
            "beginner_description": metric.beginner_description,
            "expert_description": metric.expert_description,
        }

        for field_name, value in fields_to_check.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                if field_name in ("beginner_description", "expert_description"):
                    # 이 두 필드는 선택 사항(Nullable)이므로 Warning 처리
                    print(f"⚠️  [WARNING] {context} -> '{field_name}' 설명이 비어있습니다.")
                    warnings += 1
                else:
                    print(f"❌  [ERROR] {context} -> 필수 한국어 필드 '{field_name}' 설명이 누락되었습니다.")
                    errors += 1
                continue

            # 영어만 있는지 검사
            if is_english_only(value):
                print(f"❌  [ERROR] {context} -> '{field_name}' 필드가 영어로만 작성되어 있습니다: '{value}'")
                errors += 1
            
            # 길이 검사 (100자 제한)
            len_issues = check_sentence_length(value, 100)
            for issue in len_issues:
                print(f"⚠️  [WARNING] {context} -> '{field_name}' {issue}")
                warnings += 1

            # 전문용어 비중 검사
            jargon_issues = check_jargon_ratio(value)
            for issue in jargon_issues:
                print(f"⚠️  [WARNING] {context} -> '{field_name}' {issue}")
                warnings += 1

    # 2. 복구 가이드 (Recovery Guide) 검사
    print("\n[2] 복구 가이드 (Recovery Guide) 검증 중...")
    for code, playbook in PLAYBOOKS.items():
        context = f"Playbook '{code}'"

        # 타이틀, 진단 검사
        if is_english_only(playbook.title):
            print(f"❌  [ERROR] {context} -> 타이틀이 영어로만 작성되어 있습니다: '{playbook.title}'")
            errors += 1
        if is_english_only(playbook.diagnosis):
            print(f"❌  [ERROR] {context} -> 진단 내용이 영어로만 작성되어 있습니다: '{playbook.diagnosis}'")
            errors += 1

        # 글자수 길이 및 전문용어 비율 검사
        for field_name, val in [("title", playbook.title), ("diagnosis", playbook.diagnosis)]:
            len_issues = check_sentence_length(val, 100)
            for issue in len_issues:
                print(f"⚠️  [WARNING] {context} -> '{field_name}' {issue}")
                warnings += 1
            jargon_issues = check_jargon_ratio(val)
            for issue in jargon_issues:
                print(f"⚠️  [WARNING] {context} -> '{field_name}' {issue}")
                warnings += 1

        # 복구 단계(steps) 검사
        for step_idx, step in enumerate(playbook.steps):
            step_context = f"{context} Step {step_idx + 1}"
            if is_english_only(step):
                print(f"❌  [ERROR] {step_context} -> 단계 설명이 영어로만 작성되어 있습니다: '{step}'")
                errors += 1
            len_issues = check_sentence_length(step, 100)
            for issue in len_issues:
                print(f"⚠️  [WARNING] {step_context} -> {issue}")
                warnings += 1
            jargon_issues = check_jargon_ratio(step)
            for issue in jargon_issues:
                print(f"⚠️  [WARNING] {step_context} -> {issue}")
                warnings += 1

    # 3. 프론트엔드 JS 리소스 파일 검사
    print("\n[3] 프론트엔드 JavaScript UI 라벨 검증 중...")
    js_dir = ROOT_DIR / "src" / "jayu" / "dashboard_static"
    if js_dir.exists():
        for js_file in js_dir.glob("*.js"):
            file_name = js_file.name
            content = js_file.read_text(encoding="utf-8")
            
            # 한글이 포함된 문자열을 찾아 길이를 검사합니다.
            # 정규식으로 따옴표 안의 문자열 추출
            strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'', content)
            for raw_str_tuple in strings:
                # regex findall returns tuple of (double_quote_match, single_quote_match)
                raw_str = raw_str_tuple[0] or raw_str_tuple[1]
                raw_str = raw_str.strip()
                
                # 코드 조각, HTML 태그, 클래스 이름, CSS 등은 제외
                if not raw_str or len(raw_str) < 5 or "<" in raw_str or "class=" in raw_str or "div" in raw_str:
                    continue
                if not has_hangul(raw_str):
                    continue

                # 100자 초과 문장 검사
                len_issues = check_sentence_length(raw_str, 100)
                for issue in len_issues:
                    print(f"⚠️  [WARNING] {file_name} -> UI 한글 텍스트 {issue}")
                    warnings += 1
    else:
        print("⚠️  [WARNING] dashboard_static 디렉토리를 찾을 수 없습니다.")
        warnings += 1

    print("\n==================================================")
    print(f" 검증 완료: 에러 {errors}개, 경고 {warnings}개 발견")
    print("==================================================")
    
    # 크리티컬한 에러가 있으면 실패 종료, 단순 경고는 빌드 통과 허용
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(run_lint())
