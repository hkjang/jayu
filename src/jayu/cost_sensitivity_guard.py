"""cost_sensitivity_guard.py — 거래 제비용(수수료, 슬리피지, 세금, 환전 등) 민감도 분석 및 경고 모듈.

잦은 단타나 소액 매매에서 기대 수익 대비 거래 비용이 너무 커 실익이 없는 경우를 감지하여
경고를 부여하거나 신호의 우선순위를 강등한다.
"""

from __future__ import annotations

from typing import Any

def evaluate_cost_sensitivity(
    ticker: str,
    expected_return_pct: float,
    portfolio_type: str,
    trade_amount_krw: float = 1_000_000.0,
    settings: Any = None
) -> dict[str, Any]:
    """수수료, 슬리피지, 거래세, 환전 비용을 고려한 제비용 비율을 계산하고 경고 여부를 결정한다.
    
    Returns:
        {
            "total_cost_pct": float,
            "expected_return_pct": float,
            "cost_to_gain_ratio_pct": float,
            "warning_msg": str | None,
            "priority_downgrade": bool
        }
    """
    ticker = ticker.upper()
    is_us_stock = not (ticker.endswith(".KS") or ticker.endswith(".KQ"))

    # 1. 제비용 요율 산정 (기본값)
    # 수수료 및 슬리피지 (Settings에서 동적으로 가져오거나 기본 비율 적용)
    fee_rate = 0.0015  # 0.15%
    slippage_rate = 0.0005  # 0.05%
    
    if settings:
        fee_rate = getattr(settings, "transaction_fee", fee_rate)
        slippage_rate = getattr(settings, "slippage", slippage_rate)

    # 한국 주식과 미국 주식의 세금 및 환전 구조 분리
    if is_us_stock:
        # 미국주식: 거래세(SEC fee 등 미미하므로 무시), 왕복 수수료, 왕복 환전 수수료(약 0.1% 수준 스프레드 반영)
        exchange_cost_rate = 0.0010  # 편도 0.1%, 왕복 0.2%
        tax_rate = 0.0  # 매도 시 양도세는 연간 공제 기준이므로 개별 제비용에서는 생략
        round_trip_cost = (fee_rate + slippage_rate + exchange_cost_rate) * 2.0
    else:
        # 한국주식: 거래세(약 0.18%), 왕복 수수료, 환전 없음
        tax_rate = 0.0018  # 0.18%
        round_trip_cost = (fee_rate + slippage_rate) * 2.0 + tax_rate

    # 퍼센트로 변환
    total_cost_pct = round(round_trip_cost * 100.0, 3)

    # 2. 비용 민감도 심사
    # 기대 수익률이 없거나 너무 낮게 잡힌 경우 기본 2.0% 설정 (단타용)
    expected_gain = expected_return_pct if expected_return_pct > 0 else (1.5 if portfolio_type == "short_term" else 5.0)

    # 기대수익 대비 비용 비중 계산
    ratio = round((total_cost_pct / expected_gain) * 100.0, 1)

    warning_msg = None
    priority_downgrade = False

    # 특히 단타의 경우, 거래비용이 기대 수익의 20%를 넘거나 소액 거래로 마찰비용이 커지는 경우 경고
    if ratio >= 25.0:
        priority_downgrade = True
        warning_msg = (
            f"⚠️ 거래 비용 부담 과다: 이 신호의 예상 거래 비용은 약 {total_cost_pct:.2f}%로, "
            f"기대 수익률({expected_gain:.1f}%) 대비 제비용 비율이 {ratio}%에 달합니다. "
            "잦은 거래 시 수수료와 슬리피지로 인해 실익이 거의 남지 않는 '배보다 배꼽이 큰' 상태입니다."
        )
    elif ratio >= 15.0:
        warning_msg = (
            f"ℹ️ 비용 주의: 기대 수익({expected_gain:.1f}%) 대비 제비용 비중({ratio}%)이 다소 높은 편입니다. "
            "매매 규모가 너무 작지 않은지 점검하십시오."
        )

    return {
        "total_cost_pct": total_cost_pct,
        "expected_return_pct": expected_gain,
        "cost_to_gain_ratio_pct": ratio,
        "warning_msg": warning_msg,
        "priority_downgrade": priority_downgrade
    }
