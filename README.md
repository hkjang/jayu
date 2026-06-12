# 📈 주식 자동화 자율 진화 단타 시스템 (Stock Automation Engine)

본 시스템은 **3대 시장 국면별 독립 유전 알고리즘(GA) 진화 모델**과 **래리 코너스의 RSI(2) 하이브리드 전략**, 그리고 자본 소실을 원천 방어하는 **초보수적 자본 보존(Capital Preservation)** 가드가 결합된 24시간 백그라운드 구동형 미국 주식 단타 투자 자동화 솔루션입니다.

---

## 🗺️ 상세 문서 맵 (Documentation Index)

프로젝트 루트의 파일 정리 및 구조화 정책에 따라, 모든 상세 매뉴얼과 기술 명세서는 **`docs/`** 디렉토리 하위에서 중앙 집중식으로 관리됩니다.

1. **[SYSTEM_README.md (docs/SYSTEM_README.md)](file:///c:/Users/gagag/Claude/Projects/주식 자동화/docs/SYSTEM_README.md)**
   - 시스템 전체 파일 맵, config.json 격리 정보, 윈도우 스케줄러 등록 정보 수록.
2. **[SIMULATION.md (docs/SIMULATION.md)](file:///c:/Users/gagag/Claude/Projects/주식 자동화/docs/SIMULATION.md)**
   - 자율 진화 GA 파이프라인, Fitness Score 수식, Kelly 및 분할 베팅 비중 공식 명세.
3. **[STRATEGY.md (docs/STRATEGY.md)](file:///c:/Users/gagag/Claude/Projects/주식 자동화/docs/STRATEGY.md)**
   - 래리 코너스 하이브리드 규칙, 본전 손절(Break-Even) 및 VIX 22.0 가드 등 매매 전략 가이드.
   - **세부 전략별 공식 명세서**:
     - [래리 윌리엄스 변동성 돌파 전략 명세 (docs/STRATEGY_WILLIAMS_BREAKOUT.md)](file:///c:/Users/gagag/Claude/Projects/주식 자동화/docs/STRATEGY_WILLIAMS_BREAKOUT.md)
     - [래리 코너스 RSI(2) 하이브리드 전략 명세 (docs/STRATEGY_CONNORS_RSI2.md)](file:///c:/Users/gagag/Claude/Projects/주식 자동화/docs/STRATEGY_CONNORS_RSI2.md)
     - [ADX 기반 추세/횡보 동적 스위칭 전략 명세 (docs/STRATEGY_ADX_SWITCHING.md)](file:///c:/Users/gagag/Claude/Projects/주식 자동화/docs/STRATEGY_ADX_SWITCHING.md)
4. **[DEVELOPER_GUIDE.md (docs/DEVELOPER_GUIDE.md)](file:///c:/Users/gagag/Claude/Projects/주식 자동화/docs/DEVELOPER_GUIDE.md)**
   - 파이썬 7대 소스코드 모듈의 기능별/역할별 책임 한계, 의존 관계도 및 장애 대처법 수록.
5. **[포트폴리오_전략.md (docs/포트폴리오_전략.md)](file:///c:/Users/gagag/Claude/Projects/주식 자동화/docs/포트폴리오_전략.md)**
   - 장기 10x 포트폴리오(삼성전자, PLTR, RKLB, IONQ) 집중 투자 원칙서.
6. **[DEEP_TRADING_STRATEGY.md (docs/DEEP_TRADING_STRATEGY.md)](file:///c:/Users/gagag/Claude/Projects/주식 자동화/docs/DEEP_TRADING_STRATEGY.md)**
   - 기하평균 성장률 공식, 3x 레버리지 변동성 잠식(Volatility Drag) 제어 공식 및 래리 코너스 RSI(2)의 통계적 기대값 미시 분석 명세.

---

## ⚡ 퀵 스타트 및 실행 가이드

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. 환경 설정 (`config.json` 신규 작성)
프로젝트 루트 경로에 `config.json` 파일을 생성하고 아래 양식에 맞추어 API 키와 시드를 주입합니다.
```json
{
  "BASE_DIR": "C:\\Users\\gagag\\Claude\\Projects\\주식 자동화",
  "TICKERS": ["SOXL", "TQQQ", "TSLA", "IONQ", "NVDL", "QBTS"],
  "INITIAL_CAPITAL": 10000000,
  "SIM_RUNS": 500,
  "TRANSACTION_FEE": 0.0015,
  "SLIPPAGE": 0.0005,
  "MASSIVE_API_KEY": "YOUR_MASSIVE_NEWS_API_KEY",
  "KAKAO_ACCESS_TOKEN": "YOUR_KAKAO_ACCESS_TOKEN"
}
```

### 3. 유닛 테스트 및 정합성 검증
모든 연산 및 가드 모듈(20개 테스트)이 무결하게 작동하는지 검증합니다.
```bash
py -3.12 -m unittest test_simulation.py
```

### 4. Windows 자동 기동 스케줄러 등록
4시간 주기로 시뮬레이션 및 알림 발송이 백그라운드 운용되도록 윈도우 작업 스케줄러에 등록합니다. (관리자 권한 실행 필요)
```powershell
.\register_task.ps1
```

---

## 📂 프로젝트 주요 파일 현황

*   `danta_simulation.py`: 최적 단타 매개변수 유전 탐색 엔진.
*   `stock_kakao.py`: 매일 아침/저녁 거시 시황 및 시그널 알림 전송기.
*   `test_simulation.py`: 수치/예외 15대 테스트 케이스 모음.
*   `toss_portfolio.csv` / `build_portfolio.py`: 보유 종목 실시간 평가액 집계 모듈.
*   `best_strategy.json` / `today_signals.json`: 시뮬레이션 진화 상태 및 실시간 당일 매수 추천 신호.
