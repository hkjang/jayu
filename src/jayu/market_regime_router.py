"""market_regime_router.py — 시장 국면 판단 및 포트폴리오 타입별 우선순위(가중치) 조정.

KOSPI, KOSDAQ, S&P500, Nasdaq, VIX 및 거래량/금리/환율 정보를 기반으로
현재 시장 국면을 상승장(bull), 하락장(bear), 횡보장(sideways), 고변동성(volatile), 위험회피(risk_off)로 판정한다.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger("jayu.market_regime_router")

RegimeType = Literal["bull", "bear", "sideways", "volatile", "risk_off"]

# 국면별 포트폴리오 타입 우선순위 가중치 승수
REGIME_WEIGHTS: dict[RegimeType, dict[str, float]] = {
    "bull": {
        "short_term": 1.2,   # 적극 검토
        "swing": 1.5,        # 우선 검토
        "long_term": 1.2,     # 유지 및 확대
        "dividend": 0.8,     # 보통
    },
    "bear": {
        "short_term": 0.5,   # 제한
        "swing": 0.3,        # 축소
        "long_term": 0.5,     # 분할 관찰
        "dividend": 1.5,     # 우선 방어 (배당 최우선)
    },
    "sideways": {
        "short_term": 1.0,   # 일부 가능
        "swing": 1.0,        # 선별 검토
        "long_term": 0.8,     # 관망
        "dividend": 1.2,     # 안정 후보 우선
    },
    "volatile": {
        "short_term": 0.3,   # 매우 제한
        "swing": 0.5,        # 제한
        "long_term": 0.6,     # 관찰
        "dividend": 1.0,     # 방어 우선
    },
    "risk_off": {
        "short_term": 0.1,   # 금지에 가까움
        "swing": 0.2,        # 축소
        "long_term": 0.3,     # 신규 제한
        "dividend": 1.4,     # 현금 및 배당 중심
    }
}

REGIME_DESCRIPTIONS: dict[RegimeType, str] = {
    "bull": "시장 전반이 장기 이동평균선 위에 위치하는 안정적인 강세장입니다. 성장주 및 모멘텀 기반 스윙 전략을 적극 검토합니다.",
    "bear": "장기 하락 추세가 지배적인 약세장입니다. 단기 매매와 중기 추세 전략을 축소하고, 배당 방어주와 현금 비중을 극대화할 시기입니다.",
    "sideways": "명확한 추세 없이 박스권에서 움직이는 횡보장입니다. 단기 가격 밴드 하단에서의 매수 및 고배당 수익률 전략이 유리합니다.",
    "volatile": "시장의 일간 등락폭이 커진 변동성 장세입니다. 예측 불확실성이 높으므로 레버리지 투자를 피하고 매매 횟수를 제약해야 합니다.",
    "risk_off": "VIX 공포 지수가 급등하고 환율이 요동치는 위험 회피 국면입니다. 신규 매수를 최대한 유보하고 보수적인 태도를 취하십시오."
}

def _calculate_ema(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    k = 2.0 / (period + 1)
    v = sum(prices[:period]) / period
    for p in prices[period:]:
        v = p * k + v * (1 - k)
    return v

def determine_market_regime() -> dict[str, Any]:
    """주요 글로벌 시장 지표를 yfinance로 조회하여 현재 시장 국면을 동적으로 판정한다.
    
    오프라인 상태이거나 통신 장애 시에는 보수적인 'sideways'를 기본값으로 안전하게 폴백한다.
    """
    import yfinance as yf
    from .yahoo import get_yahoo_session

    logger.info("시장 국면 판정 시작...")
    
    # 분석할 대표 티커: S&P 500(SPY), KOSPI(^KS11), NASDAQ(QQQ), VIX(^VIX), 원달러환율(USDKRW=X)
    tickers = {
        "spy": "SPY",
        "kospi": "^KS11",
        "qqq": "QQQ",
        "vix": "^VIX",
        "usdkrw": "USDKRW=X"
    }

    results: dict[str, Any] = {}
    session = get_yahoo_session()

    # 1. 지수 데이터 수집
    for key, sym in tickers.items():
        try:
            t = yf.Ticker(sym, session=session)
            # 최근 250영업일 데이터 (EMA 200 계산용)
            hist = t.history(period="1y")
            if not hist.empty:
                results[key] = hist
        except Exception as e:
            logger.warning(f"티커 {sym} 수집 실패: {e}")

    # 기본값 설정 (장애 대응)
    regime: RegimeType = "sideways"
    spy_status = "unknown"
    kospi_status = "unknown"
    vix_value = 18.0
    exchange_rate = 1350.0

    # 2. 개별 지수 상태 판정
    # SPY 판정 (EMA200 기준)
    if "spy" in results and len(results["spy"]) >= 200:
        spy_hist = results["spy"]
        spy_closes = spy_hist["Close"].dropna().tolist()
        spy_latest = spy_closes[-1]
        spy_ema200 = _calculate_ema(spy_closes, 200)
        if spy_ema200:
            if spy_latest > spy_ema200 * 1.02:
                spy_status = "bull"
            elif spy_latest < spy_ema200 * 0.98:
                spy_status = "bear"
            else:
                spy_status = "sideways"

    # KOSPI 판정
    if "kospi" in results and len(results["kospi"]) >= 200:
        kospi_hist = results["kospi"]
        kospi_closes = kospi_hist["Close"].dropna().tolist()
        kospi_latest = kospi_closes[-1]
        kospi_ema200 = _calculate_ema(kospi_closes, 200)
        if kospi_ema200:
            if kospi_latest > kospi_ema200 * 1.02:
                kospi_status = "bull"
            elif kospi_latest < kospi_ema200 * 0.98:
                kospi_status = "bear"
            else:
                kospi_status = "sideways"

    # VIX 지수 값 확인
    if "vix" in results:
        vix_closes = results["vix"]["Close"].dropna().tolist()
        if vix_closes:
            vix_value = round(vix_closes[-1], 2)

    # 환율 값 확인
    if "usdkrw" in results:
        krw_closes = results["usdkrw"]["Close"].dropna().tolist()
        if krw_closes:
            exchange_rate = round(krw_closes[-1], 2)

    # 3. 종합 국면 라우팅 규칙 적용
    # VIX 기반 위험회피 / 고변동성 우선 감지
    if vix_value >= 28.0:
        regime = "risk_off"
    elif vix_value >= 22.0:
        regime = "volatile"
    else:
        # 미국과 한국 시장 상태를 종합
        statuses = {spy_status, kospi_status}
        if "bear" in statuses and "bull" not in statuses:
            regime = "bear"
        elif "bull" in statuses and "bear" not in statuses:
            regime = "bull"
        else:
            regime = "sideways"

    # 환율이 급격히 높을 때(예: 1400원 이상) 리스크 오프 성격 가중치 부여 가능
    if exchange_rate >= 1410.0 and regime not in ("risk_off", "bear"):
        regime = "volatile"

    weights = REGIME_WEIGHTS[regime]
    description = REGIME_DESCRIPTIONS[regime]

    logger.info(f"종합 국면 판정 완료: {regime.upper()} (VIX: {vix_value}, 환율: {exchange_rate})")

    return {
        "regime": regime,
        "description": description,
        "weights": weights,
        "metrics": {
            "vix": vix_value,
            "usdkrw": exchange_rate,
            "spy_trend": spy_status,
            "kospi_trend": kospi_status,
        }
    }
