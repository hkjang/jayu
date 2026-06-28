# Jayu (자유) 투자 운영 OS 전체 메뉴 사용자 매뉴얼

본 매뉴얼은 실계좌 기반 투자 의사결정 및 배당 관리 플랫폼인 **Jayu (자유)**의 전체 21개 메뉴 구성, 상세 조작 방법, 정책 설정 가이드를 설명합니다. 본 화면들은 개인정보 보호를 위해 주요 잔고 및 수치 영역이 자동으로 블러(Blur) 처리되어 있습니다.

---

## 목차
1. [개요 및 시스템 아키텍처](#1-개요-및-시스템-아키텍처)
2. [메뉴별 기능 및 화면 설명](#2-메뉴별-기능-및-화면-설명)
   * [Group 1: 운영 현황 & 분석](#group-1-운영-현황--분석)
   * [Group 2: 투자 실행 & 리스크](#group-2-투자-실행--리스크)
   * [Group 3: Toss 증권 연동](#group-3-toss-증권-연동)
   * [Group 4: 개인 자산 & 재무 계획](#group-4-개인-자산--재무-계획)
   * [Group 5: 시스템 로그 & 설정](#group-5-시스템-로그--설정)
3. [개인 투자 원칙 설정 및 관리](#3-개인-투자-원칙-설정-및-관리)
4. [MCP 및 에이전트 보안 가이드라인 (Agent Guardrail)](#4-mcp-및-에이전트-보안-가이드라인-agent-guardrail)

---

## 1. 개요 및 시스템 아키텍처

Jayu는 단순한 주식 시뮬레이터나 자동 매수·매도 봇이 아닙니다. 토스(Toss)의 **Read-Only API**를 활용하여 사용자의 실계좌 데이터를 안전하게 조회하고, 다중 데이터 소스 교차 검증, 개인 투자 정책 심사(Risk Gate), 예상-실제 배당 대사, 신호 사후 성과 추적을 원스톱으로 지원하는 **실계좌 의사결정 지원 시스템(OS)**입니다.

---

## 2. 메뉴별 기능 및 화면 설명

### Group 1: 운영 현황 & 분석

#### 01. 개요 (Overview)
*   **기능**: 포트폴리오의 실시간 평가액, 자산 변동 기여도 분석, 오늘의 투자 브리핑 요약 및 핵심 운영 지표를 한눈에 모니터링합니다.
*   ![개요](images/jayu_dashboard_overview.png)

#### 02. 주식 & 경제 분석 (Analysis)
*   **기능**: 선택한 종목의 차트 분석, 기술적 지표 추이 및 거시 경제 데이터와의 상관관계를 시각화하여 제공합니다.
*   ![주식 & 경제 분석](images/jayu_dashboard_analysis.png)

#### 03. 포트폴리오 허브 (Portfolio Hub)
*   **기능**: 단기 및 장기 투자 자산 비중, 섹터별 노출도, 리밸런싱 필요 종목 판정 등 포트폴리오 자산 배분을 관리합니다.
*   ![포트폴리오 허브](images/jayu_dashboard_portfolio_hub.png)

#### 04. Ask Jayu - AI (Ask Jayu)
*   **기능**: 포트폴리오 상태 및 위험 요인에 대해 AI 투자 비서에게 자연어로 질문하고 설명 리포트를 생성받습니다.
*   ![Ask Jayu - AI](images/jayu_dashboard_ask_jayu.png)

---

### Group 2: 투자 실행 & 리스크

#### 05. 리스크 게이트 (Risk Gate)
*   **기능**: 최대 레버리지 한도(15%), 최소 현금 비율(10%), 단일 종목 한도(25%) 등 설정된 리스크 통제 준수 여부를 검증합니다.
*   ![리스크 게이트](images/jayu_dashboard_risk.png)

#### 06. 신호 (Signals)
*   **기능**: 오늘 발생한 매수/매도 시그널 목록과 진입 가격, 포지션 크기 및 신호 발생 근거를 제공합니다.
*   ![신호](images/jayu_dashboard_signals.png)

#### 07. Trader Lens (Trader Lens)
*   **기능**: 최근 체결된 주문들의 실행 품질, 시장 충격 및 체결 단가 적정성을 다각도로 분석합니다.
*   ![Trader Lens](images/jayu_dashboard_trader_lens.png)

#### 08. Shadow 승격 (Promotion)
*   **기능**: 가상 모의투자(Shadow Trading)에서 우수한 성과를 보인 전략을 실계좌 운영용으로 승격하기 위한 진단 기준을 제시합니다.
*   ![Shadow 승격](images/jayu_dashboard_promotion.png)

#### 09. 자동매매 준비 (Autotrading)
*   **기능**: 실전 매매 구동 전 시스템 잠금장치, API 토큰 유효성, Toss 계좌 가용성 상태를 최종 체크합니다.
*   ![자동매매 준비](images/jayu_dashboard_autotrading.png)

---

### Group 3: Toss 증권 연동

#### 10. Toss Account (Toss Account)
*   **기능**: Toss API와 연동된 실계좌 잔고, 예수금 상태, 주식 평가 금액 등 상세 자산 현황을 조회합니다.
*   ![Toss Account](images/jayu_dashboard_toss_account.png)

#### 11. Toss Market (Toss Market)
*   **기능**: Toss 증권에서 제공하는 종목 기준 정보 마스터 데이터 및 실시간 호가/시세를 모니터링합니다.
*   ![Toss Market](images/jayu_dashboard_toss.png)

---

### Group 4: 개인 자산 & 재무 계획

#### 12. 투자 목표 & 계획 (Goal Planner)
*   **기능**: 개인 투자 목표 금액 설정, 달성률 추이 및 매월 필요한 적립액을 시뮬레이션하고 관리합니다.
*   ![투자 목표 & 계획](images/jayu_dashboard_goal_planner.png)

#### 13. 현금흐름 배분 (Cashflow)
*   **기능**: 매월 입금되는 투자 원금을 규칙에 따라 여러 계좌 및 전략으로 자동 배분하는 가이드를 제공합니다.
*   ![현금흐름 배분](images/jayu_dashboard_cashflow.png)

#### 14. 배당 관리 (Dividend)
*   **기능**: 월별 세후 예상 배당금 일정과 실제 입금 내역을 비교하여 누락이나 오차를 대조 및 매칭합니다.
*   ![배당 관리](images/jayu_dashboard_dividend.png)

#### 15. 투자 코치 & 다이어트 (Investor Coach)
*   **기능**: 매매 빈도, 과도한 회전율, 손절 원칙 미준수 항목을 자가 진단하여 투자 점수와 가이드를 제시합니다.
*   ![투자 코치 & 다이어트](images/jayu_dashboard_investor_coach.png)

#### 16. 투자 캘린더 (Invest Calendar)
*   **기능**: 주요 경제 지표 발표 일정, 배당락일, 포트폴리오 리밸런싱 주기 등 스케줄을 통합 관리합니다.
*   ![투자 캘린더](images/jayu_dashboard_invest_calendar.png)

---

### Group 5: 시스템 로그 & 설정

#### 17. 데이터 품질 (Data Quality)
*   **기능**: Yahoo Finance, Tiingo, Toss 시세 데이터 간의 괴리율 및 비동기 캐시 상태의 무결성을 진단합니다.
*   ![데이터 품질](images/jayu_dashboard_data_quality.png)

#### 18. API 모니터링 (API Monitoring)
*   **기능**: 외부 정보 제공사들의 호출 성공률, 평균 응답 시간(SLA) 및 장애 탐지 로그를 제공합니다.
*   ![API 모니터링](images/jayu_dashboard_api_monitoring.png)

#### 19. 시뮬레이션 로그 (Simulation Log)
*   **기능**: 백테스트 및 Walk-Forward 최적화 엔진의 연산 과정과 실시간 유전 알고리즘 수렴 현황을 기록합니다.
*   ![시뮬레이션 로그](images/jayu_dashboard_simulation_log.png)

#### 20. 실행 이력 & 로그 (Run History)
*   **기능**: 매일 기동된 일일 배치 작업의 성공 여부, 증거 파일(Evidence) 유무 및 예외 로그를 아카이빙합니다.
*   ![실행 이력 & 로그](images/jayu_dashboard_run_history.png)

#### 21. 설정 검증 (Settings)
*   **기능**: 전체 환경 설정 변수 및 스토어 파일들의 무결성을 검증하고, 스키마 버전 마이그레이션을 실행합니다.
*   ![설정 검증](images/jayu_dashboard_settings.png)

---

## 3. 개인 투자 원칙 설정 및 관리

사용자의 투자 정책 가이드라인은 `configs/investment_policy.yaml` 파일에서 안전하게 관리됩니다.

```yaml
policy:
  asset_allocation:
    max_leverage_ratio: 0.15          # 최대 레버리지 ETF 비중 한도
    min_cash_ratio: 0.10              # 최소 안전 현금 보유 비중
    max_single_position_ratio: 0.25   # 단일 종목 최대 보유 한도
  trading_restrictions:
    max_daily_trades: 5               # 일일 최대 주문 횟수
    cool_down_days_after_loss: 5      # 손절 후 동일 종목 재진입 제한 일수
    max_monthly_loss_krw: 2000000     # 월간 누적 최대 손실 한도
  dividend_quality:
    min_dividend_trust_score: 80.0    # 최소 준수 배당 신뢰 점수
```

---

## 4. MCP 및 에이전트 보안 가이드라인 (Agent Guardrail)

Jayu는 자연어 에이전트 및 MCP(Model Context Protocol) 환경에서 계좌 데이터를 안전하게 질의할 수 있도록 강력한 **보안 가이드라인(Guardrail)**이 장착되어 있습니다.

1.  **읽기 전용 권한 매트릭스 (Read-Only Matrix)**:
    - 에이전트가 `write_to_file`, `run_command` 등 쓰기/삭제/실행 관련 도구를 무단 호출하는 것을 원천 차단합니다.
2.  **명령어 인젝션 차단**:
    - 도구 인수에 `rm`, `bash`, `sh`, `powershell`, `curl`, `wget` 등의 위험한 shell 명령어 키워드가 포함될 경우 필터 단계에서 차단 에러를 반환합니다.
3.  **근거 Citation 필수 정책**:
    - 에이전트가 포트폴리오 및 자산 현황에 대해 답변할 때, 반드시 근거가 되는 로컬 아티팩트 링크(`file:///...`)를 마크다운에 명시하도록 검증합니다.
