# Jayu 주식 전략 연구 자동화

[![ci](https://github.com/hkjang/jayu/actions/workflows/ci.yml/badge.svg)](https://github.com/hkjang/jayu/actions/workflows/ci.yml)

미국 주식 전략 탐색, 당일 신호 생성, 포트폴리오 위험 심사, 카카오 알림을 분리된 CLI로 실행하는 Python 3.12 프로젝트입니다. 생성된 매수 신호는 보유 계좌의 레버리지, 기초자산, 섹터, 팩터, 현금 및 손실 한도를 통과해야 `eligible=true`가 됩니다.

## 설치

```powershell
uv sync --extra dev --frozen
Copy-Item configs\config.sample.json config.json
uv run jayu validate-config
```

비밀값은 `config.json`보다 환경변수를 우선 사용합니다.

```powershell
$env:JAYU_MASSIVE_API_KEY = "..."
$env:JAYU_KAKAO_ACCESS_TOKEN = "..."
$env:JAYU_KAKAO_REFRESH_TOKEN = "..."
$env:JAYU_KAKAO_REST_API_KEY = "..."
$env:JAYU_KAKAO_CLIENT_SECRET = "..."
```

## 주요 명령

```powershell
uv run jayu simulate --ticker SOXL --runs 500 --seed 42
uv run jayu signal --date today --seed 42
uv run jayu notify --channel kakao
uv run jayu portfolio build
uv run jayu portfolio analyze --details
uv run jayu report build --run runs/<run_id>
uv run jayu report signal-performance --price-json tests/fixtures/signal_prices.json
uv run jayu experiments --limit 20
uv run jayu validate-config
```

`simulate`는 유전 탐색과 검증을 수행합니다. `signal`은 승인된 기존 전략으로 당일 신호만 계산합니다. 같은 코드, 설정, 데이터와 `--seed`를 사용하면 탐색 난수 흐름을 재현할 수 있습니다.

Go 진입점은 동일한 Python CLI에 종료 코드와 표준 입출력을 그대로 전달합니다.

```powershell
go build -o bin\jayu.exe .\cmd\jayu
.\bin\jayu.exe simulate --ticker SOXL --runs 500 --seed 42
```

Docker 실행은 잠금 파일 기준으로 동일한 CLI를 실행합니다.

```powershell
docker build -t jayu-stock .
docker run --rm -v ${PWD}\state:/app/state -v ${PWD}\signals:/app/signals -v ${PWD}\runs:/app/runs jayu-stock signal --date today
```

## 실행 산출물

| 경로 | Git 추적 | 용도 |
|---|---:|---|
| `src/jayu/` | 예 | 설정, 데이터, 백테스트, 위험, 알림, CLI |
| `src/jayu/backtest_core.py` | 예 | 백테스트 체결/검증 핵심 |
| `src/jayu/signal_generation.py` | 예 | 당일 신호 생성과 action schema 적용 |
| `src/jayu/optimizer.py` | 예 | GA 파라미터 샘플링/변이/교차 |
| `src/jayu/legacy_adapter.py` | 예 | 구버전 상태 JSON 마이그레이션 |
| `configs/config.sample.json` | 예 | 설정 예시 |
| `configs/portfolio_mapping.json` | 예 | 포트폴리오 티커, 통화, 섹터, 팩터, 레버리지 매핑 |
| `configs/strategy_spaces/` | 예 | 전략 모드별 탐색 공간 |
| `docs/generated/` | 예 | 설정 및 파라미터 자동 생성 문서 |
| `state/` | 아니오 | 전략 상태, 실험 DB, health, 토큰, 위험 스냅샷 |
| `signals/` | 아니오 | 최신 당일 신호 |
| `runs/<run_id>/` | 아니오 | 실행 설정, 환경, 데이터 품질, 결과, JSONL 로그 |
| `data/cache/` | 아니오 | 요청별 Parquet OHLCV 캐시와 해시 |

실행 ID에는 시각, 명령, 티커, seed가 포함됩니다. `manifest.json`과 `state/experiments.sqlite`에는 Git 커밋과 dirty 여부, 설정 해시, seed, Python 및 패키지 버전, 데이터 해시, 결과 또는 실패 코드가 기록됩니다. 승인 후보의 표준 거래 로그는 `trades/`, 일별 equity curve는 `equity/`에 저장됩니다.

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
- Yahoo 데이터는 Parquet로 캐시하며 공급자, 기간, 품질 보고서와 OHLCV 해시를 실행별로 저장합니다.

## 연구 검증

- 학습과 검증 구간 사이에 purge 기간을 두고, 검증 구간끼리는 embargo를 포함해 완전히 분리합니다.
- 모든 OOS fold를 평가하며 최소 통과 개수와 양수 수익 fold 비율을 함께 검사합니다.
- 테스트는 미래 OHLCV를 변형한 뒤 과거 지표가 바뀌지 않는지 자동 확인합니다.
- 현재 종목 목록만 사용하면 `survivorship.json`에 경고를 기록합니다. `universe.policy=strict`에서는 기준일과 상장폐지 종목 포함 여부가 없으면 실행을 거부합니다.
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

실제 현금 한도를 사용하려면 `account_value_krw` 또는 `cash_balance_krw`를 설정합니다. 계좌 스냅샷은 `state/portfolio_snapshots.jsonl`에 저장됩니다. 미매핑 티커는 `state/portfolio_unmapped_tickers.json`에 따로 저장되며, 매핑 기준은 `configs/portfolio_mapping.json`입니다.

## 리포트

각 실행 디렉터리에는 `report.html`, `parameter_importance.json`, `trades/`, `equity/`가 생성됩니다.

- `report.html`: 실행 요약, equity curve SVG, 파라미터 중요도
- `parameter_importance.json`: GA 결과에서 파라미터별 fitness 분산 요약
- `report signal-performance`: 실전 신호와 사후 가격 데이터를 비교해 1일, 5일, 20일 성과를 계산

Rust 이전 작업은 `rust/jayu-core`에서 시작하며, `StrategyParams`, `Trade`, `Metrics`, `FillModel`, `SlippageModel`, `RiskModel` 타입을 먼저 고정했습니다. Python 기준 골든 fixture는 `tests/fixtures/rust_golden.json`입니다.

레거시 루트 스크립트 제거 일정은 [MIGRATION.md](docs/MIGRATION.md), Go wrapper의 역할 경계는 [GO_CLI_DIRECTION.md](docs/GO_CLI_DIRECTION.md)에 정리되어 있습니다.

## 알림과 운영 상태

카카오 액세스 토큰이 만료되면 refresh token으로 한 번 갱신합니다. 429와 5xx 응답은 지수 백오프로 재시도하고, 긴 메시지는 요약한 뒤 상세 신호 파일 경로를 포함합니다. 최종 실패는 본문 대신 메시지 해시와 오류를 `state/notification_failures.jsonl`에 기록합니다.

`state/health.json`에는 마지막 실행, 마지막 성공, 마지막 실패와 실패 코드가 기록됩니다. `runs/`는 기본 30일 또는 최근 100개까지만 보존합니다.

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
