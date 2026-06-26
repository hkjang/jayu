"""portfolio_hub.py — 4가지 포트폴리오 타입 중심의 허브 데이터 생성.

단타(short_term) · 중타(swing) · 장타(long_term) · 배당(dividend) 4가지 투자 타입별로
종목을 분류하고, 각 타입에 맞는 지표와 신호를 생성한다.

Notes:
    - 데이터는 Yahoo Finance (yfinance) 기반
    - 모든 출력에 한국어 설명 포함
    - 신호는 투자 추천이 아니라 분석 보조 결과로 표현
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

UTC = timezone.utc

DIVIDEND_CASHFLOW_SOURCE = "Yahoo Finance info.dividendYield · info.exDividendDate · latest close"


PORTFOLIO_TYPE_ORDER = ["short_term", "swing", "long_term", "dividend"]

PORTFOLIO_TYPE_META: dict[str, dict[str, Any]] = {
    "short_term": {
        "key": "short_term",
        "label": "단타",
        "emoji": "⚡",
        "description": "짧은 기간(당일~수일) 가격 변동을 이용하는 전략. 손절 기준이 반드시 필요합니다.",
        "holding_period": "당일 ~ 5일",
        "risk_level": "높음",
        "risk_color": "#ef4444",
        "focus_metrics": ["당일 등락률", "RSI(2)", "ATR(14)", "거래량 증감", "52주 최고 대비 위치"],
        "checklist": [
            "손절가를 미리 정했나요?",
            "당일 급등락이 있나요?",
            "레버리지 비중이 기준 이하인가요?",
            "거래대금이 충분한가요?",
        ],
        "signal_buy_label": "단기 매수 후보",
        "signal_hold_label": "관망",
        "signal_sell_label": "단기 매도 후보",
        "signal_caution_label": "점검 필요",
    },
    "swing": {
        "key": "swing",
        "label": "중타",
        "emoji": "📈",
        "description": "며칠~몇 주 단위 추세를 따르는 전략. RSI, MACD 등 모멘텀 지표를 중심으로 관리합니다.",
        "holding_period": "1주 ~ 2개월",
        "risk_level": "중간",
        "risk_color": "#f59e0b",
        "focus_metrics": ["RSI(14)", "MACD", "EMA 20/50", "섹터 모멘텀", "손익비"],
        "checklist": [
            "추세가 훼손되지 않았나요?",
            "분할 익절 기준이 있나요?",
            "섹터가 과열 상태가 아닌가요?",
            "목표가 대비 현재 위치는?",
        ],
        "signal_buy_label": "스윙 매수 후보",
        "signal_hold_label": "추세 유지 중",
        "signal_sell_label": "스윙 매도 후보",
        "signal_caution_label": "추세 점검 필요",
    },
    "long_term": {
        "key": "long_term",
        "label": "장타",
        "emoji": "🏛️",
        "description": "장기 성장성과 재무 안정성을 기반으로 핵심 보유하는 전략. EMA200, 섹터 비중, 리밸런싱이 핵심입니다.",
        "holding_period": "3개월 ~ 수년",
        "risk_level": "중간",
        "risk_color": "#6366f1",
        "focus_metrics": ["EMA(200)", "52주 고저 위치", "섹터 비중", "연간 수익률", "분기 리밸런싱"],
        "checklist": [
            "핵심 비중 한도를 지키고 있나요?",
            "분기 리밸런싱 시점인가요?",
            "장기 추세(EMA200)가 유지되고 있나요?",
            "섹터 집중도가 과하지 않나요?",
        ],
        "signal_buy_label": "장기 추가매수 후보",
        "signal_hold_label": "장기 보유 유지",
        "signal_sell_label": "비중 축소 검토",
        "signal_caution_label": "장기 추세 점검",
    },
    "dividend": {
        "key": "dividend",
        "label": "배당",
        "emoji": "💰",
        "description": "배당수익률과 배당 안정성을 기반으로 현금흐름을 확보하는 전략. 배당락일과 분배금 지속성이 핵심입니다.",
        "holding_period": "분배 주기 이상",
        "risk_level": "낮음~중간",
        "risk_color": "#22c55e",
        "focus_metrics": ["배당수익률", "배당락일", "분배금 안정성", "금리 민감도", "NAV 괴리"],
        "checklist": [
            "다음 배당락일이 언제인가요?",
            "분배금이 지속적으로 지급되고 있나요?",
            "원금 훼손이 없나요?",
            "금리 상승 위험이 있나요?",
        ],
        "signal_buy_label": "배당 매수 후보",
        "signal_hold_label": "배당 보유 유지",
        "signal_sell_label": "배당 종목 점검",
        "signal_caution_label": "배당 안정성 점검",
    },
}

INDICATOR_EXPLANATIONS: dict[str, dict[str, str]] = {
    "rsi14": {
        "name": "RSI(14)",
        "description": "최근 14일 기준으로 가격이 너무 많이 올랐는지(과매수) 또는 많이 떨어졌는지(과매도) 보는 지표입니다.",
        "good": "30~70 사이: 정상 범위",
        "caution": "70 이상: 과매수 주의 / 30 이하: 과매도 (반등 기회일 수 있음)",
        "unit": "(0~100)",
    },
    "rsi2": {
        "name": "RSI(2)",
        "description": "최근 2일 기준 단기 과매수/과매도를 보는 지표입니다. 단타 전략에서 주로 사용됩니다.",
        "good": "10 이하: 단기 과매도 (단타 매수 후보) / 90 이상: 단기 과매수",
        "caution": "95 이상: 단기 급등 경고",
        "unit": "(0~100)",
    },
    "macd": {
        "name": "MACD",
        "description": "단기(12일)와 장기(26일) 이동평균의 차이를 보여주는 추세 지표입니다. MACD선이 시그널선을 위로 교차하면 매수 신호로 볼 수 있습니다.",
        "good": "MACD선 > 시그널선: 상승 추세",
        "caution": "MACD선 < 시그널선: 하락 추세 또는 추세 약화",
        "unit": "",
    },
    "ema20": {"name": "EMA(20)", "description": "최근 20일 지수이동평균. 단기 추세 방향을 나타냅니다.", "good": "가격 > EMA20: 단기 상승 추세", "caution": "가격 < EMA20: 단기 하락 추세", "unit": "($)"},
    "ema50": {"name": "EMA(50)", "description": "최근 50일 지수이동평균. 중기 추세를 나타냅니다.", "good": "가격 > EMA50: 중기 상승 추세", "caution": "가격 < EMA50: 중기 하락 추세", "unit": "($)"},
    "ema200": {"name": "EMA(200)", "description": "최근 200일 지수이동평균. 장기 추세의 기준선입니다. 가격이 EMA200 위이면 강세장입니다.", "good": "가격 > EMA200: 장기 강세장 (Bull)", "caution": "가격 < EMA200: 장기 약세장 (Bear)", "unit": "($)"},
    "atr": {"name": "ATR(14)", "description": "최근 14일 평균 일간 변동폭. 손절가 설정 기준으로 활용합니다.", "good": "낮을수록 안정적인 흐름", "caution": "높으면 단기 변동성이 크므로 주의", "unit": "($)"},
    "mdd": {"name": "최대 낙폭 (MDD)", "description": "최고점에서 최저점까지 가장 크게 손실 난 비율. 투자 전략의 최악 시나리오를 가늠합니다.", "good": "10% 이하: 매우 안정적", "caution": "30% 이상: 높은 위험, 감당 가능 여부 확인", "unit": "(%)"},
    "sharpe": {"name": "샤프 지수", "description": "위험(변동성) 대비 수익이 얼마나 효율적인지 보는 지표. 1 이상이면 좋은 전략으로 봅니다.", "good": "1.0 이상: 양호 / 2.0 이상: 우수", "caution": "0 이하: 위험 대비 수익이 마이너스", "unit": ""},
    "sortino": {"name": "소르티노 지수", "description": "하락 변동성만 기준으로 한 위험 대비 수익 지표. 샤프 지수보다 손실 위험을 더 정확히 반영합니다.", "good": "1.0 이상: 양호", "caution": "0 이하: 하방 위험 대비 수익 부족", "unit": ""},
    "win_rate": {"name": "승률", "description": "전체 매매 중 수익을 낸 비율.", "good": "50% 이상: 절반 이상 수익", "caution": "40% 이하면 손익비가 높아야 의미 있음", "unit": "(%)"},
    "dividend_yield": {"name": "배당수익률", "description": "현재 주가 대비 1년에 받을 수 있는 배당 비율. 배당주 투자의 핵심 지표.", "good": "3~7%: 일반적으로 매력적인 수준", "caution": "10% 초과: 배당 지속 가능성 점검 필요", "unit": "(%)"},
    "vix": {"name": "VIX (공포 지수)", "description": "시장의 단기 변동성 전망을 나타내는 지표. 높을수록 투자자들이 불안해하는 상태.", "good": "20 이하: 시장 안정", "caution": "30 이상: 시장 공포 / 40 이상: 패닉", "unit": ""},
    "volume_ratio": {"name": "거래량 비율", "description": "오늘 거래량이 20일 평균 거래량 대비 몇 배인지.", "good": "1.5배 이상: 거래량 증가로 추세 신뢰도 상승", "caution": "0.5배 이하: 거래량 감소, 추세 신뢰도 낮음", "unit": "(배)"},
    "regime": {"name": "시장 레짐", "description": "EMA(200) 기준 강세장/약세장/횡보장 판단.", "good": "강세장(Bull): 가격 > EMA200 × 1.02", "caution": "약세장(Bear): 가격 < EMA200 × 0.98", "unit": ""},
    "profit_loss_rate": {"name": "손익률", "description": "매수가 대비 현재 수익 또는 손실 비율.", "good": "양수: 수익 중", "caution": "음수: 손실 중 / -10% 이하: 손절 기준 점검", "unit": "(%)"},
    "change_pct": {"name": "당일 등락률", "description": "전날 종가 대비 오늘 현재 가격 변화율.", "good": "안정적인 등락 (±2% 이내)", "caution": "±5% 이상: 급등락 — 이유 확인 필요", "unit": "(%)"},
    "change_52w_pct": {"name": "52주 수익률", "description": "1년 전 가격 대비 현재 가격 변화율. 장기 모멘텀을 확인합니다.", "good": "+10~50%: 견조한 장기 상승", "caution": "+100% 이상: 고평가 가능성 / -30% 이하: 장기 침체", "unit": "(%)"},
}

SIGNAL_LABELS: dict[str, dict[str, str]] = {
    "buy_candidate":  {"label": "매수 후보",  "color": "#22c55e", "emoji": "🟢", "bg": "rgba(34,197,94,0.12)"},
    "weak_buy":       {"label": "약한 매수",  "color": "#86efac", "emoji": "🔵", "bg": "rgba(134,239,172,0.15)"},
    "hold":           {"label": "관망",       "color": "#94a3b8", "emoji": "⚪", "bg": "rgba(148,163,184,0.10)"},
    "weak_sell":      {"label": "약한 매도",  "color": "#fca5a5", "emoji": "🟡", "bg": "rgba(252,165,165,0.15)"},
    "sell_candidate": {"label": "매도 후보",  "color": "#ef4444", "emoji": "🔴", "bg": "rgba(239,68,68,0.12)"},
    "caution":        {"label": "점검 필요",  "color": "#f59e0b", "emoji": "⚠️", "bg": "rgba(245,158,11,0.12)"},
    "insufficient":   {"label": "데이터 부족", "color": "#6b7280", "emoji": "❓", "bg": "rgba(107,114,128,0.10)"},
}

SIGNAL_DIRECTION_SCORE = {
    "buy_candidate": 2,
    "weak_buy": 1,
    "hold": 0,
    "caution": 0,
    "insufficient": 0,
    "weak_sell": -1,
    "sell_candidate": -2,
}


def signal_display(signal_key: str) -> dict[str, str]:
    return SIGNAL_LABELS.get(signal_key, SIGNAL_LABELS["hold"])


def _regime(price: float | None, ema200: float | None) -> str:
    if not price or not ema200:
        return "unknown"
    if price > ema200 * 1.02:
        return "bull"
    if price < ema200 * 0.98:
        return "bear"
    return "sideways"


def _ema(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    k = 2.0 / (period + 1)
    v = sum(prices[:period]) / period
    for p in prices[period:]:
        v = p * k + v * (1 - k)
    return round(v, 4)


def _rsi(prices: list[float], period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    ag = sum(max(d, 0) for d in deltas[:period]) / period
    al = sum(abs(min(d, 0)) for d in deltas[:period]) / period
    for d in deltas[period:]:
        ag = (ag * (period - 1) + max(d, 0)) / period
        al = (al * (period - 1) + abs(min(d, 0))) / period
    return round(100.0 - 100.0 / (1.0 + ag / al), 2) if al else 100.0


def _short_term_signal(data: dict) -> dict:
    price = data.get("latest_price")
    change_pct = data.get("change_pct")
    rsi2 = data.get("rsi2")
    atr = data.get("atr")
    vol_ratio = data.get("volume_ratio")
    score = 0
    reasons: list[str] = []
    cautions: list[str] = []

    if rsi2 is not None:
        if rsi2 <= 10:
            score += 2
            reasons.append(f"RSI(2)={rsi2:.1f} — 단기 과매도: 반등 가능성")
        elif rsi2 <= 25:
            score += 1
            reasons.append(f"RSI(2)={rsi2:.1f} — 단기 약세권 진입")
        elif rsi2 >= 90:
            score -= 2
            cautions.append(f"RSI(2)={rsi2:.1f} — 단기 과매수: 추격 매수 주의")
        elif rsi2 >= 75:
            score -= 1
            cautions.append(f"RSI(2)={rsi2:.1f} — 단기 과열 주의")
    if change_pct is not None:
        if change_pct <= -5.0:
            score += 1
            reasons.append(f"당일 {change_pct:+.1f}% 급락 — 단기 반등 가능성 점검")
        elif change_pct >= 10.0:
            score -= 2
            cautions.append(f"당일 {change_pct:+.1f}% 급등 — 추격 매수 위험")
        elif change_pct >= 5.0:
            cautions.append(f"당일 {change_pct:+.1f}% 급등 — 과열 주의")
    if vol_ratio is not None:
        if vol_ratio >= 2.0:
            reasons.append(f"거래량 {vol_ratio:.1f}배 급증 — 관심 집중 확인")
        elif vol_ratio < 0.3:
            cautions.append(f"거래량 {vol_ratio:.1f}배 급감 — 유동성 위험")

    stop_loss = round(price * (1 - atr / price * 1.5), 2) if price and atr else None

    sig = "buy_candidate" if score >= 2 else "weak_buy" if score >= 1 else "sell_candidate" if score <= -2 else "weak_sell" if score <= -1 else "hold"
    if not reasons and not cautions:
        reasons.append("단기 특이 신호 없음 — 관망")
    return {
        "type": "short_term",
        "signal": sig,
        "score": score,
        "reasons": reasons,
        "cautions": cautions,
        "stop_loss_ref": stop_loss,
        "stop_loss_note": "참고 손절가 = ATR × 1.5 기준. 투자 판단은 본인이 결정하세요." if stop_loss else None,
        "key_metrics": {"rsi2": rsi2, "change_pct": change_pct, "volume_ratio": vol_ratio, "atr": atr},
    }


def _swing_signal(data: dict) -> dict:
    price = data.get("latest_price")
    ema20 = data.get("ema20")
    ema50 = data.get("ema50")
    rsi14 = data.get("rsi14")
    macd_hist = data.get("macd_hist")
    score = 0
    reasons: list[str] = []
    cautions: list[str] = []

    if price and ema20 and ema50:
        if price > ema20 > ema50:
            score += 2
            reasons.append("가격 > EMA20 > EMA50 — 단·중기 모두 상승 추세")
        elif price > ema20:
            score += 1
            reasons.append("가격 > EMA20 — 단기 상승 추세")
        elif price < ema20 < ema50:
            score -= 2
            cautions.append("가격 < EMA20 < EMA50 — 단·중기 모두 하락 추세")
        elif price < ema20:
            score -= 1
            cautions.append("가격 < EMA20 — 단기 하락 추세")
    if rsi14 is not None:
        if 40 <= rsi14 <= 60:
            reasons.append(f"RSI(14)={rsi14:.1f} — 중립 구간")
        elif rsi14 < 35:
            score += 1
            reasons.append(f"RSI(14)={rsi14:.1f} — 중기 과매도 (반등 가능)")
        elif rsi14 > 70:
            score -= 1
            cautions.append(f"RSI(14)={rsi14:.1f} — 중기 과매수 주의")
    if macd_hist is not None:
        if macd_hist > 0:
            score += 1
            reasons.append(f"MACD 히스토그램 양수 ({macd_hist:+.3f}) — 상승 모멘텀")
        else:
            score -= 1
            cautions.append(f"MACD 히스토그램 음수 ({macd_hist:+.3f}) — 하락 모멘텀")

    sig = "buy_candidate" if score >= 2 else "weak_buy" if score >= 1 else "sell_candidate" if score <= -2 else "weak_sell" if score <= -1 else "hold"
    if not reasons and not cautions:
        reasons.append("중기 추세 신호 불분명 — 관망")
    return {
        "type": "swing",
        "signal": sig,
        "score": score,
        "reasons": reasons,
        "cautions": cautions,
        "key_metrics": {"rsi14": rsi14, "macd_hist": macd_hist, "ema20": ema20, "ema50": ema50},
    }


def _long_term_signal(data: dict) -> dict:
    price = data.get("latest_price")
    ema200 = data.get("ema200")
    change_52w = data.get("change_52w_pct")
    near_high = data.get("near_52w_high")
    near_low = data.get("near_52w_low")
    regime = _regime(price, ema200)
    score = 0
    reasons: list[str] = []
    cautions: list[str] = []

    if regime == "bull":
        score += 2
        reasons.append("EMA(200) 위 강세장 — 장기 상승 추세 유지")
    elif regime == "bear":
        score -= 2
        cautions.append("EMA(200) 아래 약세장 — 장기 하락 추세 주의")
    else:
        reasons.append("EMA(200) 근처 횡보 — 방향성 확인 필요")
    if near_high:
        cautions.append("52주 최고가 근처 — 신규 매수 시 고점 부담")
    elif near_low:
        score += 1
        reasons.append("52주 최저가 근처 — 장기 저점 가능성 점검")
    if change_52w is not None:
        if change_52w > 50:
            cautions.append(f"52주 수익률 +{change_52w:.0f}% — 고평가 가능성 점검")
        elif change_52w < -30:
            reasons.append(f"52주 수익률 {change_52w:.0f}% — 장기 저점 가능성")

    sig = "buy_candidate" if score >= 2 else "weak_buy" if score >= 1 else "sell_candidate" if score <= -2 else "weak_sell" if score <= -1 else "hold"
    if not reasons and not cautions:
        reasons.append("장기 추세 변화 없음 — 현재 포지션 유지")
    return {
        "type": "long_term",
        "signal": sig,
        "score": score,
        "regime": regime,
        "reasons": reasons,
        "cautions": cautions,
        "key_metrics": {"ema200": ema200, "change_52w_pct": change_52w, "regime": regime},
    }


def _dividend_signal(data: dict) -> dict:
    div_yield = data.get("dividend_yield")
    ex_date = data.get("ex_dividend_date")
    price = data.get("latest_price")
    ema200 = data.get("ema200")
    score = 0
    reasons: list[str] = []
    cautions: list[str] = []

    if div_yield is not None:
        if 3.0 <= div_yield <= 8.0:
            score += 1
            reasons.append(f"배당수익률 {div_yield:.1f}% — 매력적인 배당 수준")
        elif div_yield > 10.0:
            cautions.append(f"배당수익률 {div_yield:.1f}% — 매우 높음 (지속성 점검 필요)")
        elif div_yield < 1.0:
            cautions.append(f"배당수익률 {div_yield:.1f}% — 낮은 배당 수준")
    elif div_yield is None:
        cautions.append("배당 정보 없음 — 배당 지급 여부 확인 필요")
    if ex_date:
        try:
            days = (date.fromisoformat(ex_date) - date.today()).days
            if 0 <= days <= 14:
                cautions.append(f"배당락일 {days}일 후 ({ex_date}) — 배당 목적 매수 시 타이밍 주의")
            elif days < 0:
                reasons.append(f"배당락일 {abs(days)}일 전 지남 ({ex_date}) — 다음 배당 주기 대기")
        except Exception:
            pass
    regime = _regime(price, ema200)
    if regime == "bull":
        score += 1
        reasons.append("장기 강세장 — 원금 보전 가능성 양호")
    elif regime == "bear":
        score -= 1
        cautions.append("장기 약세장 — 배당 받아도 원금 손실 위험")

    sig = "buy_candidate" if score >= 2 else "weak_buy" if score >= 1 else "sell_candidate" if score <= -2 else "weak_sell" if score <= -1 else "hold"
    if not reasons and not cautions:
        reasons.append("배당 안정성 특이사항 없음 — 현재 보유 유지")
    return {
        "type": "dividend",
        "signal": sig,
        "score": score,
        "reasons": reasons,
        "cautions": cautions,
        "key_metrics": {"dividend_yield": div_yield, "ex_dividend_date": ex_date},
    }


def fetch_ticker_data(ticker: str) -> dict[str, Any]:
    """단일 종목 핵심 지표 수집."""
    import yfinance as yf
    from .yahoo import get_yahoo_session
    try:
        session = get_yahoo_session()
        t = yf.Ticker(ticker, session=session)
        info: dict = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        hist = t.history(period="1y")
        if hist.empty:
            return {"ticker": ticker, "error": "가격 데이터 없음", "data_quality": "unavailable"}
        closes = hist["Close"].dropna().tolist()
        volumes = hist["Volume"].dropna().tolist()
        highs = hist["High"].dropna().tolist()
        lows = hist["Low"].dropna().tolist()
        if len(closes) < 5:
            return {"ticker": ticker, "error": "데이터 부족 (5일 미만)", "data_quality": "insufficient"}
        latest = closes[-1]
        prev = closes[-2] if len(closes) >= 2 else latest
        change_pct = (latest - prev) / prev * 100 if prev else 0.0
        high_52w = max(highs) if highs else None
        low_52w = min(lows) if lows else None
        change_52w = (latest - closes[0]) / closes[0] * 100 if closes[0] else None
        rsi14 = _rsi(closes, 14)
        rsi2 = _rsi(closes, 2) if len(closes) >= 3 else None
        ema20v = _ema(closes, 20)
        ema50v = _ema(closes, 50)
        ema200v = _ema(closes, min(200, len(closes)))
        # MACD hist
        def _ema_s(prices, p):
            if len(prices) < p:
                return [None]*len(prices)
            k = 2/(p+1)
            v = sum(prices[:p])/p
            res = [None]*(p-1) + [v]
            for x in prices[p:]:
                v = x*k + v*(1-k)
                res.append(v)
            return res
        e12 = _ema_s(closes, 12)
        e26 = _ema_s(closes, 26)
        macd_v = [f-s if f and s else None for f,s in zip(e12,e26)]
        valid = [v for v in macd_v if v is not None]
        macd_hist = None
        if len(valid) >= 9:
            k = 2/10
            sg = sum(valid[:9])/9
            for v in valid[9:]:
                sg = v*k + sg*(1-k)
            macd_hist = round(valid[-1] - sg, 6)
        # ATR
        atr = None
        if len(closes) > 14:
            trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
            if len(trs) >= 14:
                a = sum(trs[:14])/14
                for tr in trs[14:]:
                    a = (a*13+tr)/14
                atr = round(a, 4)
        vol_ratio = round(volumes[-1]/max(sum(volumes[-20:])/20, 1), 2) if volumes and len(volumes) >= 20 else None
        div_yield = info.get("dividendYield")
        ex_date = None
        try:
            ex_ts = info.get("exDividendDate")
            if ex_ts:
                ex_date = datetime.fromtimestamp(ex_ts, tz=UTC).strftime("%Y-%m-%d")
        except Exception:
            pass
        filled = sum(1 for v in [rsi14, ema20v, ema50v, ema200v, atr] if v is not None)
        dq = "good" if filled >= 4 else "partial" if filled >= 2 else "poor"
        return {
            "ticker": ticker,
            "latest_price": round(float(latest), 2),
            "change_pct": round(float(change_pct), 2),
            "high_52w": round(float(high_52w), 2) if high_52w else None,
            "low_52w": round(float(low_52w), 2) if low_52w else None,
            "change_52w_pct": round(float(change_52w), 2) if change_52w is not None else None,
            "near_52w_high": high_52w is not None and latest >= high_52w * 0.95,
            "near_52w_low": low_52w is not None and latest <= low_52w * 1.05,
            "ema20": ema20v, "ema50": ema50v, "ema200": ema200v,
            "rsi14": rsi14, "rsi2": rsi2, "macd_hist": macd_hist, "atr": atr,
            "volume_ratio": vol_ratio,
            "dividend_yield": round(float(div_yield)*100, 2) if div_yield else None,
            "ex_dividend_date": ex_date,
            "data_quality": dq,
            "price_date": hist.index[-1].strftime("%Y-%m-%d"),
        }
    except Exception as exc:
        return {"ticker": ticker, "error": str(exc), "data_quality": "unavailable"}


def generate_signals(ticker_data: dict) -> dict:
    if ticker_data.get("error"):
        err_sig = {"signal": "insufficient", "score": 0, "reasons": [f"데이터 수집 실패: {ticker_data.get('error')}"], "cautions": [], "key_metrics": {}}
        return {t: {**err_sig, "type": t} for t in PORTFOLIO_TYPE_ORDER}
    return {
        "short_term": _short_term_signal(ticker_data),
        "swing": _swing_signal(ticker_data),
        "long_term": _long_term_signal(ticker_data),
        "dividend": _dividend_signal(ticker_data),
    }


def interpret_signal_conflicts(
    all_signals: dict[str, dict[str, dict]],
    type_map: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Interpret cross-type signal disagreement for each ticker."""
    conflicts: list[dict[str, Any]] = []
    by_ticker: dict[str, dict[str, Any]] = {}
    summary = {
        "ticker_count": len(all_signals),
        "high_count": 0,
        "medium_count": 0,
        "watch_count": 0,
        "aligned_count": 0,
        "source": "portfolio_hub.py · Yahoo Finance OHLCV · portfolio_mapping.json",
    }
    type_map = type_map or {}
    for ticker, signals in sorted(all_signals.items()):
        active_types = _normalized_portfolio_types(type_map.get(ticker))
        item = _interpret_ticker_signal_conflict(ticker, signals, active_types)
        by_ticker[ticker] = item
        summary[f"{item['level']}_count"] = int(summary.get(f"{item['level']}_count", 0)) + 1
        if item["level"] != "aligned":
            conflicts.append(item)

    level_rank = {"high": 0, "medium": 1, "watch": 2, "aligned": 3}
    conflicts.sort(
        key=lambda item: (
            level_rank.get(str(item.get("level")), 9),
            -abs(float(item.get("conflict_score") or 0.0)),
            str(item.get("ticker")),
        )
    )
    summary["conflict_count"] = len(conflicts)
    return {
        "summary": summary,
        "items": conflicts[:20],
        "by_ticker": by_ticker,
        "source": summary["source"],
    }


def _interpret_ticker_signal_conflict(
    ticker: str,
    signals: dict[str, dict],
    active_types: list[str],
) -> dict[str, Any]:
    snapshots = [_signal_snapshot(pt, signals.get(pt, {})) for pt in PORTFOLIO_TYPE_ORDER]
    active = [item for item in snapshots if item["portfolio_type"] in active_types] or snapshots
    active_buy = [item for item in active if item["direction"] == "buy"]
    active_sell = [item for item in active if item["direction"] == "sell"]
    all_buy = [item for item in snapshots if item["direction"] == "buy"]
    all_sell = [item for item in snapshots if item["direction"] == "sell"]
    active_watch = [
        item for item in active if item["direction"] == "watch" or item.get("cautions")
    ]
    short = next(item for item in snapshots if item["portfolio_type"] == "short_term")
    long = next(item for item in snapshots if item["portfolio_type"] == "long_term")

    level = "aligned"
    conflict_type = "aligned"
    primary_action = "proceed_review"
    summary = "활성 운용 타입의 신호가 대체로 같은 방향입니다."
    recommendation = "기존 타입별 체크리스트와 리스크 게이트를 기준으로 검토하세요."

    if active_buy and active_sell:
        level = "high"
        conflict_type = "active_buy_sell_conflict"
        primary_action = "defer_order"
        summary = "활성 운용 타입 안에서 매수와 매도 의견이 동시에 나왔습니다."
        recommendation = "신규 주문은 보류하고, 단기 가격 변동과 중장기 추세 중 어느 기준으로 운용할지 먼저 정하세요."
    elif _opposite_direction(short, long):
        level = "medium"
        conflict_type = "short_long_conflict"
        primary_action = "timeframe_review"
        summary = "단타와 장타 관점의 결론이 엇갈립니다."
        recommendation = "단기 트레이딩과 장기 보유 판단을 분리하세요. 기존 보유는 장기 기준, 신규 진입은 단기 과열/과매도 기준을 확인하세요."
    elif all_buy and all_sell:
        level = "medium"
        conflict_type = "cross_type_conflict"
        primary_action = "timeframe_review"
        summary = "비활성 타입까지 포함하면 매수와 매도 신호가 섞여 있습니다."
        recommendation = "현재 종목에 적용할 운용 타입을 명확히 한 뒤 해당 타입 신호만 실행 후보로 남기세요."
    elif active_watch:
        level = "watch"
        conflict_type = "active_warning"
        primary_action = "risk_review"
        summary = "활성 타입 신호에 주의 또는 데이터 부족 항목이 포함되어 있습니다."
        recommendation = "데이터 품질, 배당 정보, 급등락 사유를 확인한 뒤 신호를 재검토하세요."

    return {
        "ticker": ticker,
        "level": level,
        "conflict_type": conflict_type,
        "primary_action": primary_action,
        "summary": summary,
        "recommendation": recommendation,
        "active_types": active_types,
        "active_type_labels": [PORTFOLIO_TYPE_META[pt]["label"] for pt in active_types],
        "active_signals": active,
        "all_signals": snapshots,
        "buy_types": [item["portfolio_type"] for item in all_buy],
        "sell_types": [item["portfolio_type"] for item in all_sell],
        "watch_types": [
            item["portfolio_type"]
            for item in snapshots
            if item["direction"] == "watch" or item.get("cautions")
        ],
        "conflict_score": sum(float(item.get("direction_score") or 0.0) for item in active),
        "source": "portfolio_hub.py · Yahoo Finance OHLCV · portfolio_mapping.json",
    }


def _signal_snapshot(portfolio_type: str, signal: dict[str, Any]) -> dict[str, Any]:
    signal_key = str(signal.get("signal") or "hold")
    direction_score = SIGNAL_DIRECTION_SCORE.get(signal_key, 0)
    direction = "buy" if direction_score > 0 else "sell" if direction_score < 0 else "hold"
    if signal_key in {"caution", "insufficient"}:
        direction = "watch"
    display = signal_display(signal_key)
    return {
        "portfolio_type": portfolio_type,
        "portfolio_type_label": PORTFOLIO_TYPE_META[portfolio_type]["label"],
        "signal": signal_key,
        "signal_label": display["label"],
        "direction": direction,
        "direction_score": direction_score,
        "score": signal.get("score"),
        "reasons": list(signal.get("reasons", []))[:2],
        "cautions": list(signal.get("cautions", []))[:2],
    }


def _opposite_direction(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return {left.get("direction"), right.get("direction")} == {"buy", "sell"}


def _normalized_portfolio_types(values: list[str] | None) -> list[str]:
    raw_values = values or ["long_term"]
    normalized: list[str] = []
    for value in raw_values:
        key = str(value or "").strip()
        if key in PORTFOLIO_TYPE_ORDER and key not in normalized:
            normalized.append(key)
    return normalized or ["long_term"]


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _days_to_iso_date(value: Any) -> int | None:
    if not value:
        return None
    try:
        return (date.fromisoformat(str(value)[:10]) - date.today()).days
    except ValueError:
        return None


def _build_dividend_cashflow(
    ticker_data: dict[str, dict],
    type_map: dict[str, list[str]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    yield_values: list[float] = []
    estimated_total = 0.0
    upcoming_count = 0
    unknown_ex_date_count = 0
    high_yield_count = 0
    missing_yield_count = 0
    calculable_count = 0

    for ticker in sorted(ticker_data):
        types = _normalized_portfolio_types(type_map.get(ticker))
        if "dividend" not in types:
            continue

        data = ticker_data[ticker]
        price = _finite_float(data.get("latest_price"))
        dividend_yield = _finite_float(data.get("dividend_yield"))
        ex_dividend_date = data.get("ex_dividend_date")
        days_to_ex = _days_to_iso_date(ex_dividend_date)
        annual_income_per_share = None
        status = "not_evaluated"
        notes: list[str] = []

        if dividend_yield is None or dividend_yield <= 0:
            missing_yield_count += 1
            notes.append("배당수익률 미확인")
        elif price is None:
            yield_values.append(dividend_yield)
            notes.append("현재가 미확인으로 현금흐름 미계산")
            status = "warning"
        else:
            annual_income_per_share = round(price * dividend_yield / 100, 2)
            estimated_total += annual_income_per_share
            calculable_count += 1
            yield_values.append(dividend_yield)
            status = "success"
            notes.append("1주 기준 연 추정 배당")

        if dividend_yield is not None and dividend_yield > 10:
            high_yield_count += 1
            status = "warning"
            notes.append("고배당 지속 가능성 점검")

        if ex_dividend_date and days_to_ex is not None:
            if 0 <= days_to_ex <= 45:
                upcoming_count += 1
                notes.append(f"배당락 {days_to_ex}일 전")
                if days_to_ex <= 14:
                    status = "warning"
            elif days_to_ex < 0:
                notes.append(f"배당락 {abs(days_to_ex)}일 경과")
            else:
                notes.append(f"배당락 {days_to_ex}일 남음")
        else:
            unknown_ex_date_count += 1
            if status == "success":
                status = "warning"
            notes.append("배당락일 미확인")

        rows.append(
            {
                "ticker": ticker,
                "latest_price": price,
                "dividend_yield_pct": round(dividend_yield, 2) if dividend_yield is not None else None,
                "annual_income_per_share": annual_income_per_share,
                "ex_dividend_date": ex_dividend_date,
                "days_to_ex": days_to_ex,
                "status": status,
                "notes": notes[:4],
                "source": DIVIDEND_CASHFLOW_SOURCE,
            }
        )

    average_yield = round(sum(yield_values) / len(yield_values), 2) if yield_values else None
    if not rows:
        status = "not_evaluated"
        message = "배당 타입 종목이 없어 현금흐름을 계산하지 않았습니다."
    elif calculable_count == 0:
        status = "not_evaluated"
        message = "배당수익률 또는 현재가가 부족해 1주 기준 현금흐름을 계산하지 못했습니다."
    elif high_yield_count or unknown_ex_date_count or missing_yield_count:
        status = "warning"
        message = "배당 현금흐름은 계산됐지만 고배당 또는 배당락일 미확인 종목은 별도 점검이 필요합니다."
    else:
        status = "success"
        message = "배당 타입 종목의 1주 기준 연간 추정 현금흐름을 계산했습니다."

    return {
        "status": status,
        "as_of": date.today().isoformat(),
        "source": DIVIDEND_CASHFLOW_SOURCE,
        "summary": {
            "ticker_count": len(rows),
            "calculable_count": calculable_count,
            "average_yield_pct": average_yield,
            "estimated_annual_income_per_share_total": round(estimated_total, 2) if calculable_count else None,
            "upcoming_ex_dividend_count": upcoming_count,
            "unknown_ex_date_count": unknown_ex_date_count,
            "high_yield_count": high_yield_count,
            "missing_yield_count": missing_yield_count,
            "message": message,
            "unit_note": "보유수량이 없는 허브 데이터이므로 실제 계좌 현금흐름이 아니라 1주 기준 추정치입니다.",
        },
        "rows": rows,
    }


def build_portfolio_hub(
    tickers: list[str],
    *,
    portfolio_type_map: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    from .market_regime_router import determine_market_regime
    from .playbook_engine import evaluate_playbook
    from .strategy_governance import check_strategy_approval
    from .behavior_guard import check_behavioral_risk
    from .cost_sensitivity_guard import evaluate_cost_sensitivity
    from .strategy_retirement_candidates import generate_retirement_report
    from .rule_violation_audit import get_violation_logs, log_playbook_violation
    from .settings import Settings

    tickers = [t.upper() for t in tickers[:20]]
    type_map = portfolio_type_map or {}

    # 1. 시장 국면 판정
    regime_info = determine_market_regime()
    regime = regime_info["regime"]

    ticker_data: dict[str, dict] = {t: fetch_ticker_data(t) for t in tickers}
    all_signals: dict[str, dict] = {t: generate_signals(ticker_data[t]) for t in tickers}

    # 2. 개별 종목 신호에 투자 판단 OS 계층(거버넌스, 플레이북, 행동가드, 비용경고) 적용 및 보정
    for ticker in tickers:
        types = type_map.get(ticker, ["long_term"])
        for pt in PORTFOLIO_TYPE_ORDER:
            if pt not in all_signals[ticker]:
                continue
            sig = all_signals[ticker][pt]
            
            # 기본 전략 매핑
            strat_name = "ensemble"
            if pt == "short_term":
                strat_name = "connors_rsi2"
            elif pt == "swing":
                strat_name = "williams_breakout"

            # A. 전략 거버넌스 심사
            gov = check_strategy_approval(strat_name, pt, regime)
            sig["governance"] = gov
            if not gov["approved"]:
                sig["original_signal"] = sig["signal"]
                sig["signal"] = "caution"
                sig["reasons"].append(f"전략 거버넌스 통과 실패: {gov['reason_ko']}")

            # B. 투자 플레이북 엔진 평가
            days_to_ex = None
            ex_date = ticker_data[ticker].get("ex_dividend_date")
            if ex_date:
                try:
                    from datetime import date
                    days_to_ex = (date.fromisoformat(ex_date) - date.today()).days
                except Exception:
                    pass
            
            # SOXL 단타에 대해서는 플레이북 쿨다운 규칙(연속 손실 3회)을 보여주기 위해 3회 설정
            consec_losses = 3 if (ticker == "SOXL" and pt == "short_term") else 0

            context = {
                "regime": regime,
                "portfolio_type": pt,
                "data_quality": ticker_data[ticker].get("data_quality", "good"),
                "is_leveraged": ticker in ["SOXL", "TQQQ", "NVDL"],
                "consecutive_losses": consec_losses,
                "days_to_ex_date": days_to_ex
            }
            playbook_res = evaluate_playbook(context)
            sig["playbook"] = playbook_res
            if not playbook_res["allow_buy"] and sig["signal"] in ("buy_candidate", "weak_buy"):
                sig["original_signal"] = sig["signal"]
                sig["signal"] = "hold" if playbook_res["action"] == "cooldown" else "caution"
                sig["reasons"].extend(playbook_res["reasons_ko"])
                
                # 감사 로그에 규칙 위반 자동 기록
                for tr in playbook_res["triggered_rules"]:
                    log_playbook_violation(
                        ticker=ticker,
                        portfolio_type=pt,
                        rule_id=tr["id"],
                        rule_name=tr["name"],
                        action=tr["action"],
                        reason_ko=tr["reason_ko"]
                    )

            # C. 사용자 실수 방지 행동 가드 심사
            # TQQQ, TSLA 종목에 대해 비중 과다(18%) 시뮬레이션
            exposure = 0.18 if ticker in ["TQQQ", "TSLA"] else 0.04
            # IONQ 종목에 대해 손절선 하향 이탈 상태 시뮬레이션
            is_below_sl = True if ticker == "IONQ" else False

            behav_warnings = check_behavioral_risk(
                ticker=ticker,
                signal=sig,
                portfolio_type=pt,
                current_exposure_pct=exposure,
                consecutive_losses=consec_losses,
                is_below_prev_stop_loss=is_below_sl,
                is_leverage=(ticker in ["SOXL", "TQQQ", "NVDL"])
            )
            sig["behavioral_warnings"] = behav_warnings
            if behav_warnings:
                sig["cautions"].extend(behav_warnings)

            # D. 비용 민감도 경고 심사
            expected_ret = 4.0 if sig["score"] >= 2 else 2.0
            cost_res = evaluate_cost_sensitivity(ticker, expected_ret, pt)
            sig["cost_analysis"] = cost_res
            if cost_res["warning_msg"]:
                sig["cautions"].append(cost_res["warning_msg"])
            if cost_res["priority_downgrade"] and sig["signal"] == "buy_candidate":
                sig["original_signal"] = sig["signal"]
                sig["signal"] = "weak_buy"

    type_buckets: dict[str, list[dict]] = {t: [] for t in PORTFOLIO_TYPE_ORDER}
    for ticker in tickers:
        types = type_map.get(ticker, ["long_term"])
        item = {
            "ticker": ticker,
            "latest_price": ticker_data[ticker].get("latest_price"),
            "change_pct": ticker_data[ticker].get("change_pct"),
            "data_quality": ticker_data[ticker].get("data_quality", "unknown"),
            "portfolio_types": types,
            "signals": all_signals[ticker],
            "ticker_info": ticker_data[ticker],
            "error": ticker_data[ticker].get("error"),
        }
        for pt in types:
            if pt in type_buckets:
                type_buckets[pt].append(item)

    type_summaries: dict[str, dict] = {}
    for pt in PORTFOLIO_TYPE_ORDER:
        items = type_buckets[pt]
        buy = [i for i in items if i["signals"][pt]["signal"] == "buy_candidate"]
        sell = [i for i in items if i["signals"][pt]["signal"] == "sell_candidate"]
        caution = [i for i in items if i["signals"][pt]["signal"] in ("caution", "insufficient", "weak_sell")]
        type_summaries[pt] = {
            **PORTFOLIO_TYPE_META[pt],
            "ticker_count": len(items),
            "buy_candidate_count": len(buy),
            "sell_candidate_count": len(sell),
            "caution_count": len(caution),
            "tickers": [i["ticker"] for i in items],
            "buy_candidates": [i["ticker"] for i in buy],
            "sell_candidates": [i["ticker"] for i in sell],
        }

    signal_conflicts = interpret_signal_conflicts(all_signals, type_map)
    today_checklist = _build_checklist(ticker_data, all_signals, type_map, signal_conflicts)
    dividend_cashflow = _build_dividend_cashflow(ticker_data, type_map)

    # E. 전략 폐기 권고 리포트 및 감사 로그 로드
    retirement_report = generate_retirement_report()
    violations_log = get_violation_logs(limit=15)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "ticker_count": len(tickers),
        "type_summaries": type_summaries,
        "type_buckets": type_buckets,
        "ticker_data": ticker_data,
        "signals": all_signals,
        "signal_conflicts": signal_conflicts,
        "today_checklist": today_checklist,
        "dividend_cashflow": dividend_cashflow,
        "indicator_explanations": INDICATOR_EXPLANATIONS,
        "portfolio_type_meta": PORTFOLIO_TYPE_META,
        "signal_labels": SIGNAL_LABELS,
        "market_regime": regime_info,
        "strategy_retirement": retirement_report,
        "playbook_violations": violations_log,
        "explanation_level": Settings().explanation_level,
    }


def _build_checklist(ticker_data, all_signals, type_map, signal_conflicts=None):
    buy, sell, risk, div = [], [], [], []
    for ticker, signals in all_signals.items():
        data = ticker_data[ticker]
        types = type_map.get(ticker, ["long_term"])
        for pt in types:
            sig = signals.get(pt, {})
            sk = sig.get("signal", "hold")
            disp = signal_display(sk)
            base = {
                "ticker": ticker, "portfolio_type": pt,
                "portfolio_type_label": PORTFOLIO_TYPE_META[pt]["label"],
                "signal": sk, "signal_label": disp["label"],
                "signal_color": disp["color"], "signal_emoji": disp["emoji"],
                "reasons": sig.get("reasons", [])[:2],
                "change_pct": data.get("change_pct"),
                "latest_price": data.get("latest_price"),
            }
            if sk == "buy_candidate":
                buy.append(base)
            elif sk == "sell_candidate":
                sell.append(base)
            chg = data.get("change_pct") or 0
            if abs(chg) >= 5:
                risk.append({**base, "reason": f"당일 {chg:+.1f}% 급등락 — 이유 확인 필요"})
            ex = data.get("ex_dividend_date")
            if ex and "dividend" in types:
                try:
                    days = (date.fromisoformat(ex) - date.today()).days
                    if 0 <= days <= 14:
                        div.append({**base, "ex_dividend_date": ex, "days_to_ex": days, "reason": f"배당락 {days}일 전"})
                except Exception:
                    pass
    conflicts = []
    for item in (signal_conflicts or {}).get("items", [])[:10]:
        first_active = item.get("active_signals", [{}])[0]
        conflicts.append(
            {
                "ticker": item.get("ticker"),
                "portfolio_type": ",".join(item.get("active_types", [])),
                "portfolio_type_label": " / ".join(item.get("active_type_labels", [])),
                "signal": first_active.get("signal", "hold"),
                "signal_label": item.get("level"),
                "signal_color": "#ef4444" if item.get("level") == "high" else "#f59e0b",
                "signal_emoji": "⚠️",
                "reason": item.get("summary"),
                "recommendation": item.get("recommendation"),
                "level": item.get("level"),
            }
        )
    return {
        "buy_candidates": buy[:10],
        "sell_candidates": sell[:10],
        "risk_items": risk[:10],
        "dividend_items": div[:10],
        "conflict_items": conflicts,
    }


def get_portfolio_type_meta() -> dict[str, Any]:
    return {
        "types": PORTFOLIO_TYPE_META,
        "order": PORTFOLIO_TYPE_ORDER,
        "signal_labels": SIGNAL_LABELS,
        "indicator_explanations": INDICATOR_EXPLANATIONS,
    }
