# 🏆 ADX 기반 추세/횡보 동적 스위칭 전략 명세 (STRATEGY_ADX_SWITCHING.md)

> **상세 레벨**: 실전 및 알고리즘 구현 매뉴얼  
> **최종 수정**: 2026-06-13  
> **핵심 개념**: 추세 강도(ADX) 정량 측정 + 진입 조건 다이내믹 스위칭 + 마켓 레짐 적응

---

## 1. 전략 개요 및 레짐 스위칭 이론

알고리즘 트레이딩에서 가장 흔하게 발생하는 파산 패턴은 **"추세 추종 전략을 박스권(횡보장)에서 돌려 수수료와 슬리피지로 녹아내리거나, 역추세 전략을 원웨이(추세장)에서 돌려 끝없는 손절을 겪는 것"**입니다. 

단타 고수들은 단 하나의 절대 법칙이 모든 시장 상황을 지배할 수 없음을 인정합니다. 본 전략은 웰스 와일더(Welles Wilder)가 개발한 **ADX (Average Directional Index)** 지표를 사용하여 시장의 추세 강도를 실시간으로 정량 판정하고, 추세장과 횡보장에 맞춰 진입 엔진의 속성을 180도 완전히 바꾸는 **마켓 레짐 적응형(Market Regime Adaptive) 전략**입니다.

---

## 2. ADX 국면 판정 및 스위칭 로직

ADX 지표는 가격의 방향성과 관계없이 현재 추세가 얼마나 강한지(Trending) 혹은 약한지(Range-bound)를 $0 \sim 100$ 사이의 수치로 나타냅니다.

```
       ADX 수치
 100 ┌────────────────────────────────────────┐
     │  강한 추세장 (Trending Regime)           │
     │  - 추세 추종 (EMA 돌파, MACD 골든크로스)    │
  25 ├────────────────────────────────────────┤  <-- ADX Threshold (유동적 튜닝)
     │  횡보/박스권장 (Mean-Reverting Regime)    │
     │  - 역추세 진입 (RSI 과매도, BB 하단 반등)    │
   0 └────────────────────────────────────────┘
```

### A. 강한 추세장 국면 (ADX > adx_threshold / 보통 25 이상)
시장에 명확한 방향성과 모멘텀이 실린 상태입니다. 가격이 매물대를 돌파하는 돌파 매매나 정방향 EMA 추종이 압도적인 수익률을 냅니다.
*   **필수 진입 조건 (Mandatory)**: 
    - 당일 종가가 span 지수이동평균선 위에 위치 (`Close > EMA_span`)
    - MACD 골든크로스 발생 충족 (`macd_cross == True`)
*   **선택 조건 (Optionals)**: 볼린저 밴드 상단 돌파 성향 점검, OBV 거래량 추세선 돌파 등.

### B. 횡보/박스권 국면 (ADX < 20 이하)
추세 에너지가 없으며 주가가 일정 밴드 내에서 평균 회귀(Mean Reverting)하는 패턴을 보입니다. 이때 추세 추종을 쓰면 휩소에 다 털리므로, 철저하게 눌림목/과매도 반등을 낚아채야 합니다.
*   **필수 진입 조건 (Mandatory)**:
    - RSI가 저가 임계 영역 내에 존재 (`rsi_lo <= RSI <= rsi_hi`)
    - 주가가 볼린저 밴드 하단 영역에 안착 (`bb_pct < 0.40` 이내)
*   **선택 조건 (Optionals)**: EMA선 위일 필요가 없으며, Stochastic RSI의 과매도 해소 흐름 점검.

---

## 3. 상세 스위칭 매커니즘 코드 예시

백테스트 및 실시간 신호 판단 시 다음과 같이 분기가 작동하여 진입에 필요한 조건을 완전히 스왑(Swap)합니다.

```python
# ADX 및 기술지표 로드
adx_val = float(row['adx'])
use_adx = p.get('use_adx_filter', False)
adx_threshold = p.get('adx_threshold', 25)

if use_adx and adx_val > adx_threshold:
    # ── [추세 모드 가동] ──
    # EMA 위에 정배열되어 있으며 MACD 상향 돌파 시 필수 진입 허용
    mandatory = mandatory and conds['ema']
    if p['require_macd']:
        mandatory = mandatory and conds['macd']
    optionals = [conds['rsi'], conds['bb'], conds['regime'], conds['obv'], conds['stoch']]

elif use_adx and adx_val < 20:
    # ── [횡보 모드 가동] ──
    # EMA 정배열 여부는 상관 없음. RSI 과매도와 BB 하단이 필수 진입선
    mandatory = mandatory and conds['rsi']
    if p['require_bb']:
        mandatory = mandatory and conds['bb']
    optionals = [conds['ema'], conds['macd'], conds['regime'], conds['obv'], conds['stoch']]

else:
    # ── [기본 모드] ──
    mandatory = mandatory and conds['rsi'] and conds['ema']
    optionals = [conds['macd'], conds['bb'], conds['regime'], conds['obv'], conds['stoch']]
```

---

## 4. 실전 변수 튜닝 및 리스크 관리

1.  **adx_threshold (20, 25, 30)**
    - 추세를 판정하는 절대 기준선입니다. 변동성이 원래 극도로 높은 3배 레버리지 상품(SOXL)은 기준선을 `30`으로 타이트하게 잡아야 신뢰도 높은 추세가 가려지며, 종합 주가지수 ETF(TQQQ)나 중대형 개별주(TSLA)는 `25` 수준이 가장 적합합니다.
2.  **포지션 비중 및 손절 조절과의 유기적 연동**
    - 횡보 국면에서의 손절선은 좁게 잡고 익절선도 밴드폭에 맞춰 좁게 잡는 것이 현명합니다.
    - 반면 추세 국면에서는 익절 목표폭(`target_pct` 또는 `atr_mult_target`)을 횡보 국면의 2배 이상으로 스케일링하거나, 손절 시그널이 도달하기 전까지는 트레일링 스톱(Trailing Stop)을 활용해 수익을 무제한으로 열어두고 따라붙어야 합니다.
3.  **거래대금 가드와 결합 효과**
    - 특히 ADX가 극단적으로 낮아 횡보하는 시기에는 거래대금이 마른 상태일 가능성이 높습니다. 거래대금 MA20 가드를 함께 켜두어야만 "거래가 아예 소멸해 호가가 마른 좀비 횡보 상태"의 진입을 안전하게 우회하고 "유동성은 살아있으나 박스권을 그리는 건강한 횡보 상태"만 걸러 매매할 수 있습니다.
