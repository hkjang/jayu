"""behavior_guard.py — 투자자 심리적 실수를 미연에 방지하는 행동 주의 경고 모듈.

단일 종목 과다 비중(집중 투자), 단타 중독, 손실 후 보복 매수, 손절선 무시, 배당률 착시,
환율 왜곡 등의 개인 투자 패턴을 분석해 한국어로 친숙한 경고를 제공한다.
"""

from __future__ import annotations

from typing import Any

def check_behavioral_risk(
    ticker: str,
    signal: dict[str, Any],
    portfolio_type: str,
    current_exposure_pct: float = 0.0,
    consecutive_losses: int = 0,
    is_below_prev_stop_loss: bool = False,
    is_leverage: bool = False
) -> list[str]:
    """종목 신호 및 현재 계좌 상태를 분석하여 감지된 심리/행동 위험에 대한 한국어 경고를 반환한다."""
    warnings = []

    # 1. 단일 종목 집중 투자 경고 (비중 15% 초과 검출)
    if current_exposure_pct >= 0.15:
        warnings.append(
            f"⚠️ 단일 종목 집중 경고: '{ticker}'의 포트폴리오 비중이 {current_exposure_pct * 100:.1f}%로 매우 높습니다. "
            "이 종목의 급등락이 전체 계좌 잔고를 크게 흔들 수 있습니다."
        )

    # 2. 연속 손실 후 진입 (보복 매수 심리 차단)
    if consecutive_losses >= 3:
        warnings.append(
            f"⚠️ 냉각 권장: 최근 '{portfolio_type}' 타입에서 3회 연속 손실이 발생한 후 다시 신규 진입을 시도하고 있습니다. "
            "뇌동매매나 손실 복구 심리에 쫓기지 않는지 돌아보고 쿨다운(쉬어 가기) 기간을 가지는 것을 권장합니다."
        )

    # 3. 손절 무시 (이전 손절가 밑에서 억지 물타기 경고)
    if is_below_prev_stop_loss:
        warnings.append(
            f"⚠️ 손절 기준 무시: '{ticker}'은(는) 이전 분석에서 설정된 손절 기준 가격을 이미 하향 이탈한 종목입니다. "
            "손절 약속을 어기고 감정적으로 매수 대응(물타기)을 반복하는지 점검해야 합니다."
        )

    # 4. 배당 착시 경고
    if portfolio_type == "dividend":
        div_yield = signal.get("key_metrics", {}).get("dividend_yield")
        if div_yield and div_yield > 10.0:
            warnings.append(
                f"⚠️ 고배당 착시 주의: '{ticker}'의 배당수익률이 {div_yield:.1f}%로 비정상적으로 높습니다. "
                "배당의 지속 가능성을 엄격히 재평가해야 하며, 단순히 높은 배당률만 보고 진입해서는 안 됩니다."
            )

    # 5. 레버리지 단타 과다 경고
    if portfolio_type == "short_term" and is_leverage:
        warnings.append(
            f"⚠️ 레버리지 변동성 노출: 레버리지 종목('{ticker}')은 단기 시장 충격을 배로 받습니다. "
            "방향성이 어긋나면 단 며칠 만에 치명적인 MDD를 맞을 수 있으므로 소액으로 제한하십시오."
        )

    return warnings
