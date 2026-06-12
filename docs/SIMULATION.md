# 🧬 단타 시뮬레이션 및 자율 진화 엔진 기술 명세서 (SIMULATION.md)

> **파일**: `danta_simulation.py`  
> **버전**: v4.5 (다중 국면 독립 진화 + 초보수적 자본 보호 패키지)  
> **마지막 업데이트**: 2026-06-13

---

## 🏗️ 자율 진화 파이프라인 (Execution Flow)

```
yfinance (2년치 일봉 데이터 수집)
    ↓
데이터 무결성 검증 (0 이하 가격, NaN, Inf 행 전처리 및 200행 미만 차단)
    ↓
기술 지표 연산 (RSI2, SMA5/200, EMA10/20/50/200, MACD, BB, StochRSI, OBV, ADX)
    ↓
시장 국면 분류 (Bull, Bear, Sideways - 당일 종가와 EMA200의 이격도로 판정)
    ↓
[3대 국면별 독립 유전 알고리즘 루프 구동]
    ├── 1. 부모 선택: 상위 유전자 풀(Top 15) 내 토너먼트 선택 (k=3)
    ├── 2. 유전 연산: 교차(Crossover, 50% 확률) 및 변이(Mutation, 25% 확률)
    ├── 3. 메타 샘플링: 역대 누적 성공률(meta_learning.json) 기반 가중치 부여
    └── 4. 랜덤 탐색: 탐색 공간 확보를 위한 35% 비율의 순수 랜덤 샘플링
    ↓
멀티 윈도우 Walk-Forward 백테스팅 (0, 1, 2개월 오프셋 적용 3개 윈도우 교차 검증)
    ├── 학습셋: 단기 과최적화 감지 및 필터링 (승률, PF 기준 충족 확인)
    └── 검증셋: 미래 데이터에서의 평균 수익률 및 피트니스 스코어로 검증
    ↓
초보수적 자본 보존 및 성과 계산
    ├── 1. Fractional Kelly: Kelly 비율 대비 25%~50% 수준의 보수적 배팅
    ├── 2. Break-Even Stop: 1차 수익 도달 시 손절선을 본전+수수료 보전선으로 이동
    └── 3. MDD Penalty: 최대 낙폭이 커질수록 피트니스 스코어를 최대 90%까지 급격히 감점
    ↓
합격 기준 최종 통과 여부 검사
    ├── Yes → 원자적 파일 저장(Atomic Save)으로 best_strategy.json 및 유전자 풀 교체
    └── No  → 기존 전략 유지 및 메타 성공률 데이터 업데이트
```

---

## 📐 핵심 수학 및 기술적 구현 명세

### 1. 종합 피트니스 평가식 (Fitness Score with MDD Penalty)
단일 샤프 지수의 왜곡을 방어하기 위해 Sharpe, Sortino, Calmar 비율을 결합하고, 최대 낙폭(MDD)에 따른 기하급수적 감점 패널티를 곱하여 최종 성능을 측정합니다.

$$\text{Base Fitness} = \text{Sharpe} \times 0.5 + \text{Sortino} \times 0.3 + \text{Calmar} \times 0.2$$
$$\text{MDD Penalty} = \max\left(0.1, 1.0 - \frac{\text{MDD}}{10.0}\right)$$
$$\text{Fitness Score} = \text{Base Fitness} \times \text{MDD Penalty}$$

*   **Sharpe Ratio**: 전체 수익률의 위험 대비 초과수익 측정 (클리핑 상한 20.0).
*   **Sortino Ratio**: 하방 변동성(Negative Deviation)만을 분모로 삼아 실제 손실 위험 대비 효율 측정 (클리핑 상한 30.0).
*   **Calmar Ratio**: 연수익률 대비 최대 낙폭(MDD)의 비율로 하방 리스크의 극단적 회복력 측정 (클리핑 상한 50.0).
*   **MDD Penalty**: MDD가 10%에 도달하는 순간 피트니스 스코어는 기본 점수의 10% 수준으로 하락하여, MDD가 깊은 전략은 진화 계통에서 즉시 강제 퇴출됩니다.

### 2. 적응형 Kelly 공식 및 신뢰도 스케일링
포지션 배팅 비율은 시뮬레이션 승률과 평균 손익비를 기준으로 계산하되, 신뢰도 및 분할 비중을 반영해 계산합니다.

$$K = \frac{p \cdot b - q}{b}$$
$$\text{Confidence Score} = \frac{\text{만족한 옵션 조건 수}}{\text{전체 옵션 조건 수}} \quad (\text{최소 } 0.2 \sim \text{최대 } 1.0)$$
$$\text{Actual Position Size} = K \times \text{Confidence Score} \times \text{kelly\_fraction} \times 0.5$$

*   $p$: 백테스트 승률 ($q = 1 - p$).
*   $b$: 평균 손익비 ($\text{평균 수익} / |\text{평균 손실}|$).
*   `kelly_fraction`: 파라미터 공간에서 무작위 샘플링되는 스케일 계수 ($0.25, 0.50, 1.00$).
*   최종 베팅은 안정성을 위해 **Half-Kelly** 모델 ($0.5$ 곱하기)에 `kelly_fraction` 비율을 중첩 반영해 시드머니 침식을 철저히 헷지합니다.

### 3. 본전 손절선(Break-Even Stop) 알고리즘
진입 이후 1차 목표 수익 영역에 접근하면 손절선을 본전+수수료 선으로 인상하여 손실 발생을 원천 차단합니다.

```python
# 백테스트 루프 내부 연산
if p.get('use_breakeven_stop', False) and not breakeven_activated:
    trigger_price = entry + (target_dist * p.get('breakeven_trigger_pct', 0.5))
    if hi >= trigger_price:
        breakeven_activated = True
        # 기존 stop_price를 본전 + 왕복 수수료선으로 강제 인상
        stop_price = max(stop_price, entry * (1.0 + TRANSACTION_FEE * 2))
```

---

## 📊 기술 지표 정의 및 연산 공식

지표 연산은 외부 TA-Lib 의존성을 배제하고 Pandas 및 Numpy 벡터 연산으로 자체 구현되어 작동 속도가 매우 빠르고 이식성이 좋습니다.

1. **2일 RSI (`rsi2`)**:
   - 단기 극단 과매수/과매도 포착을 위한 지표. 래리 코너스 전략의 핵심 조건.
2. **Wilder's ADX (`adx`)**:
   - 추세 강도 측정 지표. ADX > 25 일 때 추세 추종 모드로 스위칭되고, ADX < 20 일 때 역추세(평균회귀) 모드로 자동 스위칭됩니다.
3. **볼린저 밴드 %B (`bb_pct`)**:
   - 밴드 하단 부근(0.4 이하) 진입 판정용.
4. **Stochastic RSI (`stoch_rsi`)**:
   - RSI의 상대적 위치를 측정해 0.8 이하의 과열되지 않은 자리에서만 진입하도록 제한.
5. **OBV 이평선 추세 (`obv_trend`)**:
   - 온밸런스 볼륨의 10일 이평선이 30일 이평선을 상향 중일 때 수급 유입으로 판정.

---

## 🔒 원자적 파일 저장 시스템 (Atomic Save)
시뮬레이션 완료 시점에 설정 파일을 기재하다 크래시가 나면 전략 전체가 증발할 수 있습니다. 이를 막기 위해 임시 파일 스왑 아키텍처를 구현했습니다.

```python
def save_json(obj, path):
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(numpy_to_python(obj), f, ensure_ascii=False, indent=2)
        if os.path.exists(tmp_path):
            os.replace(tmp_path, path) # 원자적 스왑 (OS 레벨 보증)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise e
```
