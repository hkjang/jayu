# Jayu 주식 전략 연구 자동화

[![ci](https://github.com/hkjang/jayu/actions/workflows/ci.yml/badge.svg)](https://github.com/hkjang/jayu/actions/workflows/ci.yml)

미국·한국 주식 전략 탐색, 당일 신호 생성, 포트폴리오 위험 심사, 카카오 알림을 분리된 CLI로 실행하는 Python 3.12 프로젝트입니다. 한국 종목은 Yahoo 형식의 `.KS`·`.KQ` 티커를 사용하며 KRX 거래일과 KOSPI·KOSDAQ 벤치마크로 검증합니다. 생성된 매수 신호는 보유 계좌의 레버리지, 기초자산, 섹터, 팩터, 현금 및 손실 한도를 통과해야 `eligible=true`가 됩니다.

## 설치

```powershell
uv sync --extra dev --frozen
Copy-Item configs\config.sample.json config.json
```

비밀값은 `config.json`보다 환경변수를 우선 사용합니다.

```powershell
$env:JAYU_MASSIVE_API_KEY = "..."
$env:JAYU_TIINGO_API_KEY = "..."
$env:JAYU_SEC_USER_AGENT = "Jayu research contact@example.com"
$env:JAYU_FRED_API_KEY = "..."
$env:JAYU_OPENFIGI_API_KEY = "..."
$env:JAYU_ALPHA_VANTAGE_API_KEY = "..."
$env:JAYU_FINNHUB_API_KEY = "..."
$env:JAYU_KAKAO_ACCESS_TOKEN = "..."
$env:JAYU_KAKAO_REFRESH_TOKEN = "..."
$env:JAYU_KAKAO_REST_API_KEY = "..."
$env:JAYU_KAKAO_CLIENT_SECRET = "..."
```

sample config의 strict 가격 검증에는 최소 `JAYU_TIINGO_API_KEY`가 필요합니다.

```powershell
uv run jayu validate-config --config config.json --mode shadow
```

## 주요 명령

```powershell
uv run jayu simulate --mode research --ticker SOXL --runs 500 --seed 42
uv run jayu signal --mode shadow --date today --seed 42
uv run jayu signal --date 2026-06-12 --replay --seed 42
uv run jayu notify --channel kakao
uv run jayu portfolio build
uv run jayu portfolio analyze --details
uv run jayu report build --run runs/<run_id>
uv run jayu report signal-performance --price-json tests/fixtures/signal_prices.json
uv run jayu report shadow-performance --price-json tests/fixtures/signal_prices.json
uv run jayu experiments --limit 20
uv run jayu experiments compare --left <RUN_ID> --right <RUN_ID> --output comparison.json
uv run jayu promotion check
uv run jayu status
uv run jayu status --brief
uv run jayu status --output state/operational_status.json --markdown-output state/operational_status.md
uv run jayu status --fail-on-not-ready
uv run jayu validate-config --mode shadow
uv run jayu dashboard --host 127.0.0.1 --port 8765
```

## Read-only operations dashboard

`jayu dashboard` serves a local, read-only operations console for run status,
provider disagreement, signals, risk-gate evidence, shadow promotion, and
settings validation. It does not expose order creation or execution controls.

```powershell
uv run jayu dashboard --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`. The current implementation covers Overview,
Data Quality, Signal, Risk Gate, Shadow Promotion, and Settings Validation.
The complete screen and API design is documented in [UX_UI_SPEC.md](docs/UX_UI_SPEC.md).

## 프로세스 종료 코드

배치 작업과 스케줄러는 failure taxonomy와 함께 다음 종료 코드를 사용할 수 있습니다.

| 종료 코드 | 범주 | 대표 failure code |
|---:|---|---|
| `0` | 성공 | 없음 |
| `2` | CLI 사용 오류 | 잘못된 옵션 또는 인자 |
| `10` | 설정 오류 | `CONFIG_FAILURE` |
| `20` | 데이터 오류 | `DATA_FAILURE`, `DATA_CONTRACT_FAILED`, `DATA_DISAGREEMENT` |
| `30` | 백테스트 오류 | `BACKTEST_FAILURE` |
| `40` | 안전·승격 게이트 차단 | `SAFETY_VERDICT_BLOCKED`, `SHADOW_PROMOTION_FAILED` |
| `50` | 알림 오류 | `NOTIFICATION_FAILURE` |
| `70` | 내부 오류 | `INTERNAL_FAILURE`, 분류되지 않은 오류 |

sample config의 기본 실행 모드는 `shadow`이며 안전 프로필은 `safe`입니다.
`signal`, `shadow`, `paper`, `live`는 서로 다른 가격 provider 2개 이상,
`cross_validation_mode=strict`, `price_disagreement_policy=block`을 강제합니다.
`paper`와 `live`는 `jayu promotion check` 결과가 `eligible=true`여야 합니다.
`simulate`는 `universe.policy=strict`인 point-in-time universe만 허용합니다.

## 안전한 실행 순서

1. `uv run jayu validate-config --config config.json --mode shadow`
2. `uv run jayu simulate --mode research --runs 500`
3. `uv run jayu report build --run runs/<run_id>`
4. `uv run jayu signal --mode shadow --date today`
5. `uv run jayu promotion check`
6. `uv run jayu status`
7. `uv run jayu signal --mode paper --date today`
8. `uv run jayu signal --mode live --date today --notify`

연구 전에는 상장폐지 종목을 포함하는 시점별 universe를 준비해야 합니다. 공급자가
상장폐지 이력을 제공하지 않는다면 `universe.exception_reason`에 데이터셋, 누락 범위,
보완 절차를 감사 가능한 문장으로 기록해야 합니다. 예외 사유는 편향을 제거하지 않으며
결과 해석의 제한을 공개하는 용도입니다.

`simulate`는 유전 탐색과 검증을 수행합니다. `signal`은 승인된 기존 전략으로 당일 신호만 계산합니다. 같은 코드, 설정, 데이터와 `--seed`를 사용하면 탐색 난수 흐름을 재현할 수 있습니다.

Go 진입점은 동일한 Python CLI에 종료 코드와 표준 입출력을 그대로 전달합니다.

```powershell
go build -o bin\jayu.exe .\cmd\jayu
.\bin\jayu.exe simulate --ticker SOXL --runs 500 --seed 42
```

Docker 이미지는 UID/GID `10001`의 비루트 `app` 사용자로 실행됩니다. API key와
토큰은 이미지에 복사하지 말고 런타임 환경변수 또는 외부 secrets file로만 주입합니다.
`data`, `runs`, `state`, `signals`는 쓰기 가능한 volume으로 마운트합니다.
컨테이너 루트 파일시스템은 read-only로 실행할 수 있으며 임시 파일만 `/tmp` tmpfs에
기록합니다.

```powershell
docker build -t jayu-stock .
docker run --rm jayu-stock --help
docker run --rm --read-only --tmpfs /tmp jayu-stock --help
docker run --rm `
  --env-file .env `
  -v ${PWD}\data:/app/data `
  -v ${PWD}\state:/app/state `
  -v ${PWD}\signals:/app/signals `
  -v ${PWD}\runs:/app/runs `
  jayu-stock signal --mode shadow --date today
```

`live`는 엄격한 데이터·승격·위험 심사를 거친 운영 신호와 알림 모드일 뿐입니다.
Jayu는 브로커 주문 제출 API를 포함하지 않으며 실제 주문을 생성하거나 전송하지 않습니다.

## 실행 산출물

| 경로 | Git 추적 | 용도 |
|---|---:|---|
| `src/jayu/` | 예 | 설정, 데이터, 백테스트, 위험, 알림, CLI |
| `src/jayu/backtest_core.py` | 예 | 백테스트 체결/검증 핵심 |
| `src/jayu/signal_generation.py` | 예 | 당일 신호 생성과 action schema 적용 |
| `src/jayu/optimizer.py` | 예 | GA 파라미터 샘플링/변이/교차 |
| `src/jayu/legacy_adapter.py` | 예 | 구버전 상태 JSON 마이그레이션 |
| `src/jayu/provider_core.py` | 예 | provider category registry, HTTP 정책, JSON 캐시 |
| `src/jayu/supplemental_data.py` | 예 | SEC, FRED, OpenFIGI, 뉴스·이벤트 point-in-time 수집 |
| `configs/config.sample.json` | 예 | 설정 예시 |
| `configs/portfolio_mapping.json` | 예 | 포트폴리오 티커, 통화, 섹터, 팩터, 레버리지 매핑 |
| `configs/strategy_spaces/` | 예 | 전략 모드별 탐색 공간 |
| `docs/generated/` | 예 | 설정 및 파라미터 자동 생성 문서 |
| `state/` | 아니오 | 전략 상태, 실험 DB, health, 토큰, 위험 스냅샷 |
| `signals/` | 아니오 | 최신 당일 신호 |
| `runs/<run_id>/` | 아니오 | 실행 설정, 환경, 데이터 품질, 결과, JSONL 로그 |
| `data/cache/` | 아니오 | OHLCV Parquet와 공시·거시·뉴스·기준정보 JSON 캐시 |

실행 ID에는 시각, 명령, 티커, seed가 포함됩니다. `manifest.json`과 `state/experiments.sqlite`에는 Git 커밋과 dirty 여부, 설정 해시, seed, Python 및 패키지 버전, 데이터 해시, 결과 또는 실패 코드가 기록됩니다. `data_sources.json`은 provider별 성공·실패·기간·행 수·해시를, `provider_disagreement_report.json`은 가격 불일치를 기록합니다. 승인 후보의 표준 거래 로그는 `trades/`, 일별 equity curve는 `equity/`에 저장됩니다.

## 전략 공간

전략은 `strategy_mode` 하나만 사용합니다.

- `ensemble`
- `connors_rsi2`
- `williams_breakout`
- `volume_breakout`

구버전의 `use_connors_rsi2`, `use_williams_breakout`, `use_volume_breakout` 상태 파일은 기존 분기 우선순위를 보존해 자동 변환됩니다. ATR 손절, ATR 목표가, 트레일링, 본전 손절, 변동성 사이징의 종속 파라미터는 기능이 활성화된 후보에서만 샘플링됩니다.

자세한 값은 [파라미터 참조](docs/generated/PARAMETERS.md)에서 확인합니다.

## 체결과 데이터

- ATR과 ADX는 공통 True Range 계산을 사용합니다.
- 같은 일봉에서 손절과 목표가가 모두 닿으면 설정된 `path_mode`로 체결 순서를 결정합니다.
- 시가가 손절가를 갭 하락하면 손절가가 아니라 시가로 청산합니다.
- 주문 크기는 평균 거래대금 참여율 제한을 받습니다.
- 수수료와 슬리피지는 독립 모델이며 슬리피지는 고정 또는 ATR·참여율 기반으로 선택합니다.
- Yahoo, Massive, Tiingo 일봉은 같은 `DataRequest`와 OHLCV 스키마를 사용합니다.
- `data.cross_validation_mode=strict`에서는 `cross_validation_providers`가 비어 있거나 실제 사용 가능한 provider가 2개 미만이면 실행을 중단합니다.
- provider 비교는 행 수, 날짜 인덱스, OHLCV 상대 오차와 해시를 검사합니다. 임계값을 넘은 날짜, 필드, provider별 값과 원인을 `provider_disagreement_report.json`에 기록합니다.
- `price_disagreement_policy=block`에서는 불일치 데이터를 canonical 캐시나 운영 신호에 사용하지 않으며 명령 실패는 `DATA_FAILURE`로 기록합니다. 세부 원인은 `DATA_DISAGREEMENT`로 보존합니다.
- 가격은 Parquet로 캐시하며 현재 provider 검증 정책과 캐시 정책 서명이 다르면 다시 수집합니다.
- SEC facts는 CIK 매핑과 submissions의 acceptance time을 결합해 저장하며 발표 전 값은 point-in-time 조회에서 제외합니다.
- FRED는 initial-release vintage를 발표 가능일 기준으로 거래일에 forward fill하고, 거시 regime은 별도 OOS gate를 통과해야 전략 조건으로 승격할 수 있습니다.
- OpenFIGI 충돌은 기본적으로 신호를 차단하며, Alpha Vantage·Finnhub 뉴스·내부자·실적 이벤트는 매수 조건이 아니라 `risk_notes`로만 첨부합니다.
- 요청 티커 중 검증된 가격 데이터가 하나라도 없으면 CLI 실행은 `DATA_FAILURE`로 종료됩니다.
- `signals/today_signals.json`은 run artifact와 safety verdict가 완성된 뒤에만 원자적으로
  출판됩니다. `signals/today_signals.status.json`의 상태가 오늘 날짜의 `published`가
  아니거나 내용 hash가 다르면 standalone 알림은 차단됩니다.
- signal/shadow/paper/live 실행은 `state/operational_run.lock` 단일 실행 잠금을 사용합니다.
  중복 실행은 종료 코드 `40`으로 차단되며, 중단된 잠금은
  `operational_lock_timeout_minutes` 이후에만 회수됩니다.

Tiingo 교차검증을 활성화하려면 환경변수를 설정한 뒤 다음 값을 사용합니다.

```json
{
  "mode": "shadow",
  "data": {
    "cross_validation_providers": ["tiingo"],
    "cross_validation_mode": "strict",
    "minimum_valid_price_sources": 2,
    "price_disagreement_policy": "block"
  }
}
```

보조 데이터는 `data.supplemental_providers`에 `sec_edgar`, `fred`, `openfigi`, `alpha_vantage_news`, `finnhub_events`를 선택해 활성화합니다. provider별 `timeout_seconds`, `retries`, `rate_limit_per_minute`, `cache_ttl_seconds`는 `data.provider_policies`에서 조정합니다.

## 연구 검증

- 학습과 검증 구간 사이에 purge 기간을 두고, 검증 구간끼리는 embargo를 포함해 완전히 분리합니다.
- 모든 OOS fold를 평가하며 최소 통과 개수와 양수 수익 fold 비율을 함께 검사합니다.
- OOS fold 수익률의 Probabilistic Sharpe Ratio(PSR)를 계산하고 `research.min_oos_psr` 미만인 후보는 승인하지 않습니다.
- 같은 국면에서 평가한 후보들의 OOS fold 벡터로 Deflated Sharpe Ratio(DSR)와 Probability of Backtest Overfitting(PBO)를 계산해 다중 탐색·선택 편향을 심사합니다.
- 최신 데이터의 final lockbox는 GA와 walk-forward 탐색에서 제외하고, OOS 승인 후보를 마지막에 한 번만 평가합니다. 같은 데이터·전략의 재실행은 `state/final_lockbox_ledger.json`에 저장된 결과만 재사용합니다.
- 테스트는 미래 OHLCV를 변형한 뒤 과거 지표가 바뀌지 않는지 자동 확인합니다.
- 현재 종목 목록만 사용하면 `survivorship.json`에 강한 `SURVIVORSHIP_BIAS_RISK` 경고를 기록합니다. `universe.policy=strict`에서는 기준일과 상장폐지 종목 포함 여부가 필요하며, 상장폐지를 포함할 수 없다면 명시적 `exception_reason` 없이는 연구를 중단합니다.
- GA seed는 종목·국면별로 파생되며 최소 실행 횟수 이후 개선이 없으면 조기 종료합니다.
- fitness 버전은 결과에 저장되며 현재 버전은 `v2_daily_equity`입니다.
- Sharpe와 Sortino는 일별 equity 수익률 기준이며 거래별 Sharpe는 별도 필드입니다. Calmar는 연환산 수익률을 MDD로 나누고 MDD peak, trough, recovery와 기간을 저장합니다.

## 포트폴리오 위험

기본 `balanced` 설정은 다음 항목을 심사합니다.

- 레버리지 조정 기초자산, 섹터, 팩터별 노출
- 레버리지 ETF 평가금과 총 조정 노출
- 최소 현금 비중과 최대 투자 비중
- 일간 및 주간 손실 한도와 30일 최대 낙폭
- CSV 미매핑 티커
- 최대 보유 종목 수와 단일 종목 비중
- 최근 20일 평균 거래대금 기반 유동성

실제 현금 한도를 사용하려면 `account_value_krw` 또는 `cash_balance_krw`를 설정합니다. 계좌 스냅샷은 `state/portfolio_snapshots.jsonl`에 저장됩니다. 미매핑 티커는 `state/portfolio_unmapped_tickers.json`에 따로 저장되며, 매핑 기준은 `configs/portfolio_mapping.json`입니다.

## 리포트

각 실행 디렉터리에는 `report.html`, `report.md`, `parameter_importance.json`,
`trades/`, `equity/`가 생성됩니다.

- `report.html`: 실행 모드, config/data hash, 데이터 출처·불일치, survivorship policy, shadow promotion, risk reason codes, OOS 승인·PSR·DSR·PBO, 순비용 성과
- `report.md`: 운영 검토용 핵심 데이터 품질, promotion, 위험 차단 사유 요약
- `parameter_importance.json`: GA 결과에서 파라미터별 fitness 분산 요약
- `report signal-performance`: 실전 신호와 사후 가격 데이터를 비교해 1일, 5일, 20일 성과를 계산하고, 신호 ID별 이력을 중복 없이 누적·갱신

Rust 이전 작업은 `rust/jayu-core`에서 시작하며, `StrategyParams`, `Trade`, `Metrics`, `FillModel`, `SlippageModel`, `RiskModel` 타입을 먼저 고정했습니다. Python 기준 골든 fixture는 `tests/fixtures/rust_golden.json`입니다.

레거시 루트 스크립트의 분류(호환 shim / 중복 / 일회성 유틸 / 레거시 테스트)는 [LEGACY.md](docs/LEGACY.md), 제거 일정은 [MIGRATION.md](docs/MIGRATION.md), Go wrapper의 역할 경계는 [GO_CLI_DIRECTION.md](docs/GO_CLI_DIRECTION.md)에 정리되어 있습니다.

## 알림과 운영 상태

카카오 액세스 토큰이 만료되면 refresh token으로 한 번 갱신합니다. 429와 5xx 응답은 지수 백오프로 재시도하고, 긴 메시지는 요약한 뒤 상세 신호 파일 경로를 포함합니다. 최종 실패는 본문 대신 메시지 해시와 오류를 `state/notification_failures.jsonl`에 기록합니다.

`state/health.json`에는 마지막 실행, 마지막 성공, 마지막 실패와 실패 코드가 기록됩니다. `runs/`는 기본 30일 또는 최근 100개까지만 보존합니다.

## 운영 장애 대응

| 증상 | 자동 처리 | 운영자 조치 |
|---|---|---|
| 가격 provider 1개 이하 | `DATA_FAILURE`, 신호 생성 중단 | API key, rate limit, provider 상태 확인 |
| 가격·거래량·날짜 불일치 | `DATA_DISAGREEMENT` 세부 기록, `eligible=false` | 원시 값과 corporate action 확인 후 재수집 |
| survivorship strict 실패 | 연구·백테스트 중단 | 시점별 universe 또는 예외 사유 준비 |
| promotion 미통과 | paper/live 중단 | shadow 실행 일수와 품질 지표 보완 |
| risk reason code 발생 | 해당 매수 신호 차단 | 포지션, 현금, 섹터, 매핑, 유동성 점검 |
| health score 저하 | 알림 경고 표시 | 최근 실패 run의 manifest와 로그 확인 |

## 책임과 데이터 한계

Jayu는 연구와 운영 통제를 돕는 소프트웨어이며 투자 수익이나 손실 회피를 보장하지
않습니다. Yahoo, Tiingo, Massive 및 보조 데이터는 지연, 정정, corporate action
처리 차이, 누락, 라이선스 제한이 있을 수 있습니다. 자동 생성 신호와 리포트의 최종
검토, 주문 여부, 계좌 위험과 법적·세무 책임은 사용자에게 있습니다.

## 문서와 품질 검사

```powershell
uv run python scripts/generate_docs.py
uv run python scripts/generate_docs.py --check
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts danta_simulation.py stock_kakao.py
uv run mypy src/jayu
uv run bandit -q -r src/jayu
uv run pip-audit
uv run pytest -q
uv run pre-commit run --all-files
go test ./...
cargo test --manifest-path rust/jayu-core/Cargo.toml
```

설정 참조는 [SETTINGS.md](docs/generated/SETTINGS.md), 전략 파라미터 참조는 [PARAMETERS.md](docs/generated/PARAMETERS.md)에서 자동 생성됩니다. CI는 생성 문서, README의 CLI 진입점, 린트, 타입, 보안 및 테스트를 함께 검사합니다.

Windows 작업 스케줄러 등록은 `register_task.ps1`을 사용하며, 파일명을 직접 실행하지 않고 `.venv\Scripts\jayu.exe`를 호출합니다. Linux/macOS에서는 `scripts/jayu-cron.sh`를 crontab에 등록하거나 `scripts/jayu-systemd.service`, `scripts/jayu-systemd.timer`를 사용자 systemd timer 템플릿으로 사용할 수 있습니다.
