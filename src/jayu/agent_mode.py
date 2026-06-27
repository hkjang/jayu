from __future__ import annotations

import subprocess
import sys
from typing import Any


class JayuAgentMode:
    """Natural Language Agent CLI Shell for Jayu.
    
    Parses Korean natural language requests, plans commands, prints safety guides, and executes them.
    """

    def parse_request(self, request_text: str) -> list[dict[str, Any]]:
        """Formulate a step-by-step execution plan based on the Korean request."""
        req = request_text.lower()
        plan = []

        # 1. Status / Health Check
        if any(kw in req for kw in ["상태", "점검", "진단", "에러", "오류"]):
            plan.append({
                "step": len(plan) + 1,
                "command": "status",
                "args": [],
                "description": "시스템 전체 상태 및 데이터 정합성 자율 점검",
            })

        # 2. Portfolio / Toss Holdings
        if any(kw in req for kw in ["포트폴리오", "잔고", "보유", "토스", "계좌", "자산"]):
            plan.append({
                "step": len(plan) + 1,
                "command": "toss",
                "args": ["holdings"],
                "description": "토스 실계좌 보유 잔고 및 자산 평가액 안전 조회 (Read-Only)",
            })

        # 3. Signals Generation / Sim
        if any(kw in req for kw in ["신호", "시뮬레이션", "매수", "매도", "시그널"]):
            plan.append({
                "step": len(plan) + 1,
                "command": "signal",
                "args": ["generate"],
                "description": "오늘 자 전략 진입 및 청산 매수/매도 신호 생성 및 리스크 통제 검증",
            })

        # 4. Report Building
        if any(kw in req for kw in ["보고서", "리포트", "빌드", "생성"]):
            plan.append({
                "step": len(plan) + 1,
                "command": "report",
                "args": ["build"],
                "description": "종합 성과 지표 및 운영 SLO 스코어 포함 대시보드 리포트 빌드",
            })

        # Default fallback if no keyword matches: status check
        if not plan:
            plan.append({
                "step": len(plan) + 1,
                "command": "status",
                "args": [],
                "description": "기본 시스템 건전성 상태 조회 및 요약",
            })

        return plan

    def run_plan(self, request_text: str, auto_approve: bool = True) -> None:
        """Run the generated plan. 
        
        Prints preview, safety warnings, and executes commands.
        """
        plan = self.parse_request(request_text)

        print("=" * 60)
        print("🤖 JAYU INVESTMENT AGENT - 실행 계획 수립 (Plan Planner)")
        print(f"사용자 지시어: \"{request_text}\"")
        print("=" * 60)
        print("\n[수행 예정 명령어 시퀀스 미리보기]")
        for step in plan:
            args_str = " " + " ".join(step["args"]) if step["args"] else ""
            print(f"  Step {step['step']}: `jayu {step['command']}{args_str}`")
            print(f"          ➔ {step['description']}")

        print("\n" + "!" * 60)
        print("⚠️ 안전 및 리스크 가이드 (Safety Guide)")
        print("1. 다중 브로커 주문 제출 모듈은 연동 안전을 위해 **100% 읽기 전용(Read-Only)** 상태로 잠겨 있습니다.")
        print("2. 어떠한 경우에도 자동 주문 실행이나 자산의 강제 출금/이체가 발생하지 않습니다.")
        print("3. 로컬 시뮬레이션 및 데이터 캐싱은 기존 운영 데이터베이스에 덮어쓰지 않고 안전하게 격리되어 백업됩니다.")
        print("!" * 60 + "\n")

        if not auto_approve:
            # Under normal CLI, we would ask for y/n. But to prevent freezing tests or automated runs,
            # we support an auto_approve flag.
            confirm = input("위 실행 계획을 집행하시겠습니까? (y/N): ")
            if confirm.lower() != 'y':
                print("❌ 사용자에 의해 실행 계획이 중단되었습니다.")
                return

        print("🚀 실행 계획 집행을 시작합니다...")
        
        results = []
        for step in plan:
            print(f"\n[집행 시작] Step {step['step']}: `jayu {step['command']}` ...")
            try:
                cmd = [sys.executable, "-m", "jayu.cli", step["command"]] + step["args"]
                res = subprocess.run(cmd, capture_code=True, text=True, capture_output=True, check=True)
                results.append({
                    "step": step["step"],
                    "command": step["command"],
                    "success": True,
                    "output": res.stdout,
                })
                print(f"✅ Step {step['step']} 완료.")
            except subprocess.CalledProcessError as e:
                results.append({
                    "step": step["step"],
                    "command": step["command"],
                    "success": False,
                    "error": e.stderr or e.stdout,
                })
                print(f"❌ Step {step['step']} 실패: {e.stderr or e.stdout}")
                # Break execution chain on failure to prevent cascading errors
                break

        print("\n" + "=" * 60)
        print("📊 JAYU INVESTMENT AGENT - 집행 결과 종합 요약")
        print("=" * 60)
        
        all_ok = all(r["success"] for r in results)
        if all_ok:
            print("🎉 모든 계획된 작업이 성공적으로 완수되었습니다.")
        else:
            print("⚠️ 일부 작업 도중 에러가 발생하여 계획이 중단되었습니다.")

        for r in results:
            status_symbol = "✅" if r["success"] else "❌"
            print(f"\n{status_symbol} Step {r['step']} [jayu {r['command']}] 요약:")
            if r["success"]:
                # Print first few lines of stdout for neatness
                lines = [line for line in r["output"].split("\n") if line.strip()]
                for line in lines[:8]:
                    print(f"  {line}")
                if len(lines) > 8:
                    print("  ...")
            else:
                print(f"  오류 발생: {r['error']}")
        print("=" * 60)
