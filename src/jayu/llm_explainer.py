from __future__ import annotations

import json
import urllib.request
from typing import Any


class LlmExplainer:
    """Explains complex trading signals, risk gates, and data anomalies in natural Korean."""

    def __init__(self, ollama_url: str = "http://localhost:11434/api/generate") -> None:
        self.ollama_url = ollama_url

    def _query_local_llm(self, prompt: str) -> str | None:
        """Attempt to query a local Ollama instance. Returns None on failure."""
        try:
            data = {
                "model": "llama3",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                }
            }
            req = urllib.request.Request(
                self.ollama_url,
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            # Short timeout to prevent hanging CLI if Ollama is not running
            with urllib.request.urlopen(req, timeout=3.0) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                return str(resp_data.get("response", "")).strip()
        except Exception:
            return None

    def explain_signal(self, signal: dict[str, Any]) -> str:
        """Translate a trading signal decision into a clear Korean explanation."""
        ticker = signal.get("ticker", "알 수 없음")
        action = signal.get("action", "HOLD")
        price = signal.get("price")
        strategy = signal.get("strategy_name", signal.get("strategy", "앙상블"))
        reason = signal.get("reason", "")
        
        prompt = (
            f"주식 자동화 시스템에서 생성된 거래 신호입니다.\n"
            f"종목: {ticker}\n"
            f"액션: {action}\n"
            f"예상 가격: {price}\n"
            f"적용 전략: {strategy}\n"
            f"신호 생성 이유: {reason}\n\n"
            f"이 신호에 대해 한국어로 투자자가 이해하기 쉽게 3문장 이내로 친절하게 설명해줘. 격식체로 종결어미는 '~입니다'로 작성해줘."
        )

        llm_response = self._query_local_llm(prompt)
        if llm_response:
            return llm_response

        # Rich Rule-based Fallback
        action_k = "매수" if action.upper() == "BUY" else "매도" if action.upper() == "SELL" else "관망(대기)"
        price_str = f"{price}달러 선에서 " if price else ""
        
        explanation = (
            f"[{ticker}] 종목에 대한 {action_k} 신호가 {strategy} 전략에 의해 포착되었습니다. "
        )
        if action.upper() == "BUY":
            explanation += (
                f"현재 가격 및 기술적 지표가 설정한 진입 조건을 충족하였으며, {price_str}매수 진입하기에 유리한 국면으로 판단됩니다. "
            )
        elif action.upper() == "SELL":
            explanation += (
                f"보유 중인 종목이 목표 익절가 또는 손절 한도에 도달했거나 청산 조건을 충족하여, 자산 보호를 위한 {price_str}매도 청산 결정을 내렸습니다. "
            )
        else:
            explanation += "현재 시장 상황에서는 확실한 추세 전환 또는 진입 근거가 부족하여 추가적인 가격 확인이 필요합니다. 안전한 자산 운용을 위해 관망을 권장합니다. "

        if reason:
            explanation += f"판단 근거는 다음과 같습니다: '{reason}'."
            
        return explanation

    def explain_risk_block(self, risk: dict[str, Any]) -> str:
        """Translate a risk gate blocking decision into a clear Korean explanation."""
        ticker = risk.get("ticker", "알 수 없음")
        rule_name = risk.get("rule_name", risk.get("check_name", "리스크 한도 초과"))
        threshold = risk.get("threshold", "N/A")
        value = risk.get("value", "N/A")
        reason = risk.get("reason", "")

        prompt = (
            f"주식 자동화 시스템에서 리스크 게이트에 의해 거래가 차단되었습니다.\n"
            f"종목: {ticker}\n"
            f"리스크 규칙: {rule_name}\n"
            f"허용 임계치: {threshold}\n"
            f"현재 측정값: {value}\n"
            f"차단 상세 사유: {reason}\n\n"
            f"이 리스크 차단 사유를 한국어로 투자자가 이해하기 쉽게 3문장 이내로 자산 보호 관점에서 친절하게 설명해줘. 격식체로 종결어미는 '~입니다'로 작성해줘."
        )

        llm_response = self._query_local_llm(prompt)
        if llm_response:
            return llm_response

        # Rich Rule-based Fallback
        explanation = (
            f"자산 보호를 위해 [{ticker}] 종목의 주문 집행이 **리스크 통제 엔진에 의해 사전에 감지 및 자동 차단**되었습니다. "
            f"세부적으로는 '{rule_name}' 기준을 위반하였으며, 허용 임계치인 {threshold} 대비 현재 값이 {value}로 제한 범위를 초과하였습니다. "
        )
        if reason:
            explanation += f"원인은 다음과 같습니다: {reason}."
        else:
            explanation += "시장 변동성이 급증했거나 전략 위험 노출 한도가 초과되어 안전을 위해 선제적으로 포지션을 통제했습니다."
            
        return explanation

    def explain_disagreement(self, report: dict[str, Any]) -> str:
        """Translate a data provider disagreement report into a clear Korean explanation."""
        field = report.get("field", "가격/거래량")
        difference = report.get("difference", "N/A")
        sources = report.get("sources", ["데이터 소스A", "데이터 소스B"])
        
        prompt = (
            f"주식 자동화 시스템에서 데이터 제공처 간 정보 불일치가 발견되었습니다.\n"
            f"비교 필드: {field}\n"
            f"차이 수준: {difference}\n"
            f"비교 대상 소스: {', '.join(sources)}\n\n"
            f"이 불일치 리포트에 대해 한국어로 3문장 이내로 친절하게 위험성과 대응 방향을 설명해줘. 격식체로 종결어미는 '~입니다'로 작성해줘."
        )

        llm_response = self._query_local_llm(prompt)
        if llm_response:
            return llm_response

        # Rich Rule-based Fallback
        explanation = (
            f"신호 생성의 정밀성을 위협하는 **데이터 신뢰성 불일치 문제**가 발견되었습니다. "
            f"데이터 소스인 {', '.join(sources)} 간의 '{field}' 필드 데이터에서 {difference} 수준의 비정상적인 괴리가 감지되었습니다. "
            f"시스템은 잘못된 데이터로 인한 오작동을 피하기 위해 해당 소스의 실시간 신호 연산을 잠정 보류하고 정합성을 재검증할 것을 권장합니다."
        )
        return explanation
