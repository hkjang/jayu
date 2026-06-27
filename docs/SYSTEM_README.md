# 🖥️ 주식 자동화 및 자율 진화 시스템 종합 명세서 (SYSTEM_README)

> **구조 변경 안내**: 현재 운영 기준은 루트 `README.md`와 `src/jayu/`입니다.
> 실행 상태는 `state/`, 신호는 `signals/`, 실행별 산출물은 `runs/`에 저장되며
> 이 디렉터리는 Git에서 제외됩니다. 아래 문서의 루트 JSON 경로 설명은 역사적
> 설계 참고용입니다.

> **마지막 업데이트**: 2026-06-13
> **운영 환경**: Windows 11 / Python 3.12 / PowerShell 5.1+
> **핵심 설계**: 초보수적 자본 보존(Capital Preservation) & 다중 국면 자율 진화(Genetic Optimization)

---

## 📁 디렉토리 구조 및 파일 역할 명세

```
주식 자동화/
│
├── 📄 SYSTEM_README.md          ← [현재 파일] 전체 시스템 아키텍처 및 설정 명세
├── 📄 SIMULATION.md             ← 자율 진화 엔진(GA) 및 시뮬레이션 백테스트 엔진 기술 명세
├── 📄 STRATEGY.md               ← 실전 매매 가이드라인 (래리 코너스 및 초보수적 리스크 가드)
├── 📄 포트폴리오_전략.md         ← 장기 10x 포트폴리오 집중 관리 전략 가이드
├── 📄 requirements.txt          ← 파이썬 가상환경 의존성 패키지 목록
├── 📄 .gitignore                ← API 키 및 로컬 상태 파일 보안용 Git 제외 리스트
│
├── 📂 docs/
│   └── 📄 agent_platform.md     ← [최신] 투자 에이전트 플랫폼 상세 설계 및 운용 가이드
│
├── 📂 src/jayu/
│   ├── 🐍 broker_interface.py    ← 다중 브로커 표준 인터페이스 및 Toss read-only 어댑터
│   ├── 🐍 strategy_dsl.py       ← YAML 기반 선언적 트레이딩 전략 DSL 파서
│   ├── 🐍 strategy_card_registry.py ← 전략 속성 및 성과 카드 레지스트리
│   ├── 🐍 local_knowledge_index.py ← 로컬 문서 및 산출물 RAG (지식 색인/검색)
│   ├── 🐍 llm_explainer.py      ← AI / Rule-based 이중 결합 한국어 설명 레이어
│   ├── 🐍 notebook_export.py     ← 실행 결과 주피터 노트북(.ipynb) 내보내기 엔진
│   ├── 🐍 notification_deeplink.py ← 알림톡 원클릭 이동용 SPA 앵커 링크 구성 모듈
│   ├── 🐍 jayu_mcp_server.py    ← 외부 AI 에이전트 연동용 Model Context Protocol 서버
│   └── 🐍 agent_mode.py         ← 터미널 자연어(한글) 지시 실행 계획 수립 및 집행 에이전트
│
├── 🐍 danta_simulation.py       ← 시스템 핵심. 자율 진화 및 백테스팅 통합 엔진
├── 🐍 test_simulation.py        ← 엔진 안정성을 보증하는 15대 통합 유닛 테스트 스위트
├── 🐍 stock_kakao.py            ← 매일 주가 지수 + 뉴스 카톡 전송
├── 🐍 build_portfolio.py        ← 포트폴리오 티커+현재가+평가금 조회
├── 🐍 analyze_portfolio.py      ← 포트폴리오 섹터별 분석
├── 🐍 fix_tickers.py            ← 실패 티커 대안 탐색
├── 🐍 check_csv.py              ← CSV 검증
├── ⚙️ register_task.ps1         ← Windows 작업 스케줄러 등록 자동화 파워쉘 스크립트
│
├── 📊 toss_portfolio.csv        ← 보유 종목 현황 데이터 (244개 종목)
├── 🔑 config.json               ← [보안] API Key, 카카오 Access Token, 자본금 등 통합 설정 파일
│
├── 🧬 best_strategy.json        ← [로컬 상태] 3대 국면별/종목별 진화 완료된 최적 파라미터 셋
├── 🧬 gene_pool.json            ← [로컬 상태] 유전 교차용 국면별 상위 유전자 풀 (Top K=15)
├── 🔬 meta_learning.json        ← [로컬 상태] 감시 감쇄 피드백용 파라미터별 성공 성공률 이력
├── 📈 strategy_history.json     ← [로컬 상태] 자율 진화 세대 교체 누적 이력 기록
├── 📄 today_signals.json        ← [로컬 상태] 당일 데이터 기준 실시간 6종목 매수 추천 시그널
│
└── 📂 simulation_logs/          ← 시뮬레이션 회차별 JSON 포맷 상세 연산 로그 디렉토리
```

---

## ⚙️ 자동화 스케줄 및 가동 파이프라인

시스템은 수동 기동 없이 Windows의 `schtasks`를 활용해 완전 자동 백그라운드 운용을 지원합니다.

| 가동 모듈 | 실행 주기 및 시간 | 핵심 기능 | 알림 여부 |
|:---|:---|:---|:---:|
| **stock_kakao.py** | 매일 07:00, 17:00 (KST) | 한국/미국 주요 주가 지수 모멘텀 분석, 주요 금융 뉴스 요약 발송 | 카카오톡 발송 ✅ |
| **danta_simulation.py** | 매일 4시간 간격 (00:00~20:00) | 6대 대상 종목별 3대 국면 독립 GA 진화(500회) 및 실시간 진입 시그널 연산 | 카카오톡 발송 ✅ |

### 작업 스케줄러 등록 (`register_task.ps1`)
PowerShell을 관리자 권한으로 실행한 후 아래 명령을 통해 자동으로 작업에 등록할 수 있습니다.
```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\register_task.ps1
```
이 스크립트는 `danta_simulation.py`를 백그라운드 프로세스로 등록하여 콘솔 창의 방해 없이 주기적으로 실행합니다.

---

## 🔑 통합 설정 관리 및 보안 격리 (`config.json`)

시스템의 모든 민감한 API Key와 실행 인프라 환경 변수는 코드 내 하드코딩을 배제하고 `config.json`을 통해 독점 관리됩니다.

```json
{
  "TICKERS": ["SOXL", "TQQQ", "TSLA", "IONQ", "NVDL", "QBTS"],
  "INITIAL_CAPITAL": 10000000,
  "SIM_RUNS": 500,
  "TRANSACTION_FEE": 0.0015,
  "SLIPPAGE": 0.0005,
  "MASSIVE_API_KEY": null,
  "KAKAO_ACCESS_TOKEN": null
}
```

> **참고**: `BASE_DIR`은 스크립트가 자신의 위치를 기준으로 자동 결정합니다. 특별한 경우가 아니면 지정 불필요합니다.

### 🔒 Git 보안 정책 (`.gitignore`)
깃허브 등 오픈 퍼블릭 레포지토리에 개인 자산 및 API 비밀키가 누출되는 것을 원천 봉쇄하기 위해 프로젝트 루트에 `.gitignore` 파일이 구성되어 있습니다.
- **제외 대상**: `config.json`, `best_strategy.json`, `gene_pool.json`, `meta_learning.json`, `strategy_history.json`, `today_signals.json`, `simulation_logs/`, `.gemini/` 등 모든 상태 정보 및 개인 설정.

---

## 🚀 자율 진화 엔진의 핵심 기능 요약

1. **VIX & 지수 모멘텀 필터링**: 당일 VIX 변동성 지수가 **22.0**을 상회하거나 지수(SOX, IXIC)가 20일 이평선 밑에 머물면 신규 진입을 전면 금지합니다.
2. **시장 국면별(Regime-Specific) 최적화**: 시장을 **Bull(강세), Bear(약세), Sideways(횡보)** 3가지 국면으로 분류하여 최적의 파라미터를 격리해서 진화시킵니다.
3. **Kelly & 신뢰도 스케일링**: 통계적 승률 기반 Kelly 비율에 앙상블 조건 일치율(Confidence Score)과 `kelly_fraction` 비율을 곱하여 최적의 안전 자금을 동적으로 투입합니다.
4. **본전 손절선(Break-Even Stop)**: 목표가 절반 지점에 도달하면 손절선을 진입가+수수료 보전선으로 즉각 인상하여 원금 손실을 0에 수렴시킵니다.
5. **원자적 파일 보존(Atomic Write)**: 파일 기재 도중의 예외 크래시로 인한 JSON 훼손을 예방하기 위해 `.tmp` 쓰기 후 스왑 교체 정책을 채택했습니다.
