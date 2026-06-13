"""
단타 모의투자 시뮬레이션 + 자율 진화 엔진 v3
==============================================
개선 목록 (v2 → v3):
  1. 기술 지표 확장    — MACD, Bollinger Bands, Stochastic RSI, OBV, 시장 국면
  2. 앙상블 진입       — 여러 지표 동시 충족 (단순 RSI+EMA → 다중 신호 조합)
  3. 트레일링 스톱     — 최고가 기준 동적 손절선 상향
  4. ATR 동적 손절     — 고정 % 대신 시장 변동성에 비례
  5. Kelly 포지션      — 시뮬레이션 승률/배당률 기반 최적 비중
  6. 메타 가중 샘플링  — 역대 성공률 높은 파라미터 우선 선택
  7. 토너먼트 선택     — 더 정교한 유전 부모 선택
  8. 적응형 변이율     — 수렴 감지 시 자동 재탐색 (리셋)
  9. 멀티 윈도우 검증  — 3개 기간 평균 성과 (단일 기간 과최적화 방지)
 10. Sortino/Calmar   — 하방 위험 기반 정교한 성과 지표
 11. 오늘의 실전 신호  — 현재 조건이 진입 기준 충족하는지 실시간 판단
"""

import numpy as np
import os
import pandas as pd
import random
import sys
import warnings
from datetime import datetime
from pathlib import Path

import yfinance as yf

from .backtest_core import (
    assess_candidate_selection,
    assess_validation as _assess_validation,
    backtest as _backtest,
    configure as configure_backtest_core,
    kelly_size,
    multi_window_validate as _multi_window_validate,
    oos_fold_returns,
)
from .data import DataRequest, dataframe_sha256
from .double_oos import (
    LockboxLedger,
    LockboxSplit,
    evaluate_final_lockbox,
    final_lockbox_key,
    lockbox_split,
)
from .execution import (
    AtrParticipationSlippageModel,
    ExecutionModel,
    FixedRateFeeModel,
    FixedSlippageModel,
)
from .genetic import derive_seed, should_early_stop
from .indicators import indicator_warmup_report
from .io import stable_hash
from .legacy_adapter import (
    load_json,
    migrate_gene_pool,
    migrate_history,
    migrate_json_structure,
    numpy_to_python,
    save_json,
)
from .markets import benchmarks_for_tickers, format_market_price
from .optimizer import (
    PARAM_SPACE,
    STRATEGY_SPACES,
    configure as configure_optimizer,
    crossover,
    fill_missing_params,
    mutate,
    sample_params,
    tournament_select,
    update_meta,
)
from .performance import calc_metrics, equity_curve_records
from .settings import Settings
from .signal_generation import (
    check_today_signals,
    configure as configure_signal_generation,
    strategy_is_approved,
)
from .yahoo import get_yahoo_session

warnings.filterwarnings("ignore")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 설정 ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SETTINGS = Settings()
_RUNTIME_PATHS = _DEFAULT_SETTINGS.runtime_paths(PROJECT_ROOT)

BASE_DIR = str(PROJECT_ROOT)
TICKERS = list(_DEFAULT_SETTINGS.tickers)
INITIAL_CAPITAL = _DEFAULT_SETTINGS.initial_capital
SIM_RUNS = _DEFAULT_SETTINGS.sim_runs
TRANSACTION_FEE = _DEFAULT_SETTINGS.transaction_fee
SLIPPAGE = _DEFAULT_SETTINGS.slippage

GENETIC_RATIO = 0.65
TOP_K = 15
MIN_TRADES = 5
MAX_POS = 0.30
LOG_DIR = str(_RUNTIME_PATHS.runs_dir)
BEST_FILE = str(_RUNTIME_PATHS.best_strategy_file)
HISTORY_FILE = str(_RUNTIME_PATHS.strategy_history_file)
GENE_POOL_FILE = str(_RUNTIME_PATHS.gene_pool_file)
META_FILE = str(_RUNTIME_PATHS.meta_learning_file)
SIGNAL_FILE = str(_RUNTIME_PATHS.signal_file)
_ACTIVE_EXECUTION_MODEL = ExecutionModel(
    path_mode="worst_case",
    max_participation_rate=1.0,
    fee_model=FixedRateFeeModel(TRANSACTION_FEE),
    slippage_model=AtrParticipationSlippageModel(floor=SLIPPAGE),
)
_ACTIVE_RESEARCH = _DEFAULT_SETTINGS.research


__all__ = [
    "PARAM_SPACE",
    "STRATEGY_SPACES",
    "add_indicators",
    "assess_validation",
    "backtest",
    "calc_metrics",
    "check_today_signals",
    "compute_atr",
    "compute_true_range",
    "fill_missing_params",
    "kelly_size",
    "migrate_gene_pool",
    "migrate_history",
    "migrate_json_structure",
    "multi_window_validate",
    "run",
    "sample_params",
    "save_json",
]


def _sync_backtest_core() -> None:
    configure_backtest_core(
        initial_capital=INITIAL_CAPITAL,
        transaction_fee=TRANSACTION_FEE,
        max_pos=MAX_POS,
        min_trades=MIN_TRADES,
        execution_model=_ACTIVE_EXECUTION_MODEL,
        research=_ACTIVE_RESEARCH,
    )


def backtest(*args, **kwargs):
    _sync_backtest_core()
    return _backtest(*args, **kwargs)


def multi_window_validate(*args, **kwargs):
    _sync_backtest_core()
    return _multi_window_validate(*args, **kwargs)


def assess_validation(*args, **kwargs):
    _sync_backtest_core()
    return _assess_validation(*args, **kwargs)


def configure(settings=None, paths=None):
    """Apply validated runtime settings without doing file I/O at import time."""
    global BASE_DIR, TICKERS, INITIAL_CAPITAL, SIM_RUNS, TRANSACTION_FEE, SLIPPAGE
    global LOG_DIR, BEST_FILE, HISTORY_FILE, GENE_POOL_FILE, META_FILE, SIGNAL_FILE
    global _RUNTIME_PATHS, _ACTIVE_EXECUTION_MODEL, _ACTIVE_RESEARCH

    settings = settings or Settings()
    paths = paths or settings.runtime_paths(PROJECT_ROOT)
    paths.ensure_runtime_dirs()
    _RUNTIME_PATHS = paths
    BASE_DIR = str(paths.project_root)
    TICKERS = list(settings.tickers)
    INITIAL_CAPITAL = settings.initial_capital
    SIM_RUNS = settings.sim_runs
    TRANSACTION_FEE = settings.transaction_fee
    SLIPPAGE = settings.slippage
    LOG_DIR = str(paths.runs_dir)
    BEST_FILE = str(paths.best_strategy_file)
    HISTORY_FILE = str(paths.strategy_history_file)
    GENE_POOL_FILE = str(paths.gene_pool_file)
    META_FILE = str(paths.meta_learning_file)
    SIGNAL_FILE = str(paths.signal_file)
    slippage_model = (
        FixedSlippageModel(settings.slippage)
        if settings.execution.slippage_model == "fixed"
        else AtrParticipationSlippageModel(
            floor=settings.slippage,
            maximum=settings.execution.max_slippage,
            atr_weight=settings.execution.atr_slippage_weight,
            participation_weight=settings.execution.participation_impact_weight,
        )
    )
    _ACTIVE_EXECUTION_MODEL = ExecutionModel(
        path_mode=settings.execution.path_mode,
        max_participation_rate=settings.execution.max_participation_rate,
        fee_model=FixedRateFeeModel(settings.transaction_fee),
        slippage_model=slippage_model,
    )
    _ACTIVE_RESEARCH = settings.research
    configure_optimizer(top_k=TOP_K)
    _sync_backtest_core()
    configure_signal_generation(tickers=TICKERS)
    return paths


# ── 파라미터 공간 및 기술 지표 ───────────────────────────────────
# PARAM_SPACE and STRATEGY_SPACES are imported from optimizer as compatibility views.


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(com=period - 1, min_periods=period).mean()
    al = loss.ewm(com=period - 1, min_periods=period).mean()
    rsi = 100 - (100 / (1 + ag / al.replace(0, np.nan)))
    return rsi.fillna(50.0)


def compute_macd(series, fast=12, slow=26, signal=9):
    ef = series.ewm(span=fast).mean()
    es = series.ewm(span=slow).mean()
    line = ef - es
    sig = line.ewm(span=signal).mean()
    hist = line - sig
    return line, sig, hist


def compute_bbands(series, period=20, n_std=2.0):
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = sma + n_std * std
    lower = sma - n_std * std
    pct_b = (series - lower) / (upper - lower + 1e-10)  # 0=하단, 1=상단
    width = (upper - lower) / sma.replace(0, np.nan)  # 밴드폭 (변동성)
    return pct_b.fillna(0.5), width.fillna(0.0)


def compute_stoch_rsi(rsi, period=14, smooth=3):
    lo = rsi.rolling(period).min()
    hi = rsi.rolling(period).max()
    stoch = (rsi - lo) / (hi - lo + 1e-10)
    return stoch.rolling(smooth).mean().fillna(0.5)


def compute_obv(close, volume):
    direction = np.sign(close.diff())
    return (direction * volume).cumsum()


def compute_true_range(df):
    h_l = df["High"] - df["Low"]
    h_pc = (df["High"] - df["Close"].shift(1)).abs()
    l_pc = (df["Low"] - df["Close"].shift(1)).abs()
    return pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)


def compute_atr(df, period=14):
    return (
        compute_true_range(df)
        .ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        )
        .mean()
    )


def compute_adx(df, period=14):
    tr = compute_true_range(df)

    up_move = df["High"] - df["High"].shift(1)
    down_move = df["Low"].shift(1) - df["Low"]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_smooth = pd.Series(tr).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_dm_smooth = (
        pd.Series(plus_dm, index=df.index)
        .ewm(alpha=1.0 / period, adjust=False, min_periods=period)
        .mean()
    )
    minus_dm_smooth = (
        pd.Series(minus_dm, index=df.index)
        .ewm(alpha=1.0 / period, adjust=False, min_periods=period)
        .mean()
    )

    plus_di = 100 * (plus_dm_smooth / tr_smooth.replace(0, np.nan)).fillna(0.0)
    minus_di = 100 * (minus_dm_smooth / tr_smooth.replace(0, np.nan)).fillna(0.0)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = (
        dx.fillna(0.0).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().fillna(0.0)
    )
    return adx


def add_indicators(df):
    df = df.copy()
    # 기존
    df["rsi"] = compute_rsi(df["Close"])
    df["rsi2"] = compute_rsi(df["Close"], period=2)
    df["sma5"] = df["Close"].rolling(5).mean()
    df["sma200"] = df["Close"].rolling(200).mean()
    df["ema10"] = df["Close"].ewm(span=10).mean()
    df["ema20"] = df["Close"].ewm(span=20).mean()
    df["ema50"] = df["Close"].ewm(span=50).mean()
    df["ema200"] = df["Close"].ewm(span=200).mean()
    df["vol_ratio"] = df["Volume"] / df["Volume"].rolling(20).mean()
    df["gap"] = df["Open"] / df["Close"].shift(1) - 1
    df["atr"] = compute_atr(df)
    df["atr_pct"] = df["atr"] / df["Close"]
    df["dollar_volume"] = df["Close"] * df["Volume"]
    df["dollar_volume_ma20"] = df["dollar_volume"].rolling(20).mean().fillna(100_000_000)
    df["volume_ma20"] = df["Volume"].rolling(20).mean().fillna(10_000_000)
    for n in [5, 10, 15, 20]:
        df[f"high_max_{n}"] = df["High"].shift(1).rolling(n).max()
    # 신규
    ml, ms, mh = compute_macd(df["Close"])
    df["macd_line"] = ml
    df["macd_sig"] = ms
    df["macd_hist"] = mh
    df["macd_cross"] = (mh > 0) & (mh.shift(1) <= 0)  # 상향 교차
    df["bb_pct"], df["bb_width"] = compute_bbands(df["Close"])
    df["stoch_rsi"] = compute_stoch_rsi(df["rsi"])
    df["obv"] = compute_obv(df["Close"], df["Volume"])
    df["obv_trend"] = df["obv"].ewm(span=10).mean() > df["obv"].ewm(span=30).mean()
    df["adx"] = compute_adx(df)
    # 래리 윌리엄스 변동성 돌파용 지표
    df["noise_ratio_day"] = 1.0 - (df["Close"] - df["Open"]).abs() / (
        df["High"] - df["Low"]
    ).replace(0, np.nan)
    df["noise_ratio"] = df["noise_ratio_day"].rolling(20).mean().fillna(0.5)
    df["k_dynamic"] = 0.3 + df["noise_ratio"] * 0.3
    df["prev_range"] = df["High"].shift(1) - df["Low"].shift(1)
    # 시장 국면: 200일 EMA 기준
    df["regime"] = np.where(
        df["Close"] > df["ema200"] * 1.02,
        "bull",
        np.where(df["Close"] < df["ema200"] * 0.98, "bear", "sideways"),
    )
    before = len(df)
    result = df.dropna()
    result.attrs["warmup_rows_dropped"] = before - len(result)
    result.attrs["minimum_warmup_rows"] = 200
    result.attrs["indicator_warmup_rows"] = indicator_warmup_report()
    return result


# ── Kelly Criterion 포지션 사이징 ────────────────────────────────
def _fetch_market_data(data_service, ticker, period):
    if data_service is None:
        return yf.download(
            ticker,
            period=period,
            auto_adjust=True,
            progress=False,
            session=get_yahoo_session(),
        )
    return data_service.fetch(
        DataRequest(ticker=ticker, period=period, interval="1d", adjusted=True)
    )


def _minimum_development_rows(settings: Settings) -> int:
    research = settings.research
    return (
        research.train_months * 21
        + research.validation_months * 21 * research.walk_forward_windows
        + research.purge_days
        + research.embargo_days * (research.walk_forward_windows - 1)
    )


def _partition_research_data(
    frame: pd.DataFrame,
    settings: Settings,
) -> tuple[pd.DataFrame, LockboxSplit | None]:
    research = settings.research
    if not research.final_lockbox_enabled:
        return frame, None
    split = lockbox_split(
        len(frame),
        lockbox_fraction=research.final_lockbox_fraction,
        purge_rows=research.purge_days,
        embargo_rows=research.embargo_days,
        minimum_dev_rows=_minimum_development_rows(settings),
        minimum_lockbox_rows=research.final_lockbox_min_rows,
    )
    if split is None:
        raise ValueError("insufficient data for isolated development and final lockbox regions")
    return frame.iloc[split.development_start : split.development_end], split


def run(
    settings=None,
    paths=None,
    *,
    data_service=None,
    optimize=True,
    notify=False,
    run_context=None,
    require_approved=True,
):
    settings = settings or Settings()
    paths = configure(settings, paths)
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    run_time = now.strftime("%Y-%m-%d %H:%M")

    print(f"\n{'=' * 68}")
    print(f"  🔬 단타 시뮬레이션 v4  |  {run_time}")
    print(f"  종목: {TICKERS}")
    print(
        f"  {SIM_RUNS}회/종목/국면 | 유전({int(GENETIC_RATIO * 100)}%)+메타가중 / 랜덤({int((1 - GENETIC_RATIO) * 100)}%)"
    )
    print("  Walk-Forward: 멀티윈도우 3구간 | ADX 스위칭 필터 | 국면별 독립 파라미터")
    print(f"{'=' * 68}")
    if run_context:
        run_context.logger.info(
            "simulation started",
            extra={"run_id": run_context.run_id, "event": "simulation_start"},
        )

    # VIX 지수 사전 수집
    vix_val = 0.0
    try:
        vix_df = _fetch_market_data(data_service, "^VIX", "5d")
        if not vix_df.empty:
            vix_val = float(vix_df["Close"].dropna().iloc[-1])
            print(f"  📉 현재 VIX 지수: {vix_val:.2f}")
    except Exception as e:
        print(f"  ⚠ VIX 지수 조회 실패: {e}")

    # 설정된 미국/한국 종목에 필요한 시장·섹터 지수만 수집
    market_trends = {}
    for index_ticker in benchmarks_for_tickers(TICKERS):
        try:
            raw_idx = _fetch_market_data(data_service, index_ticker, "5y")
            if not raw_idx.empty:
                if isinstance(raw_idx.columns, pd.MultiIndex):
                    raw_idx.columns = raw_idx.columns.get_level_values(0)
                # 20일 EMA 계산
                raw_idx["ema20"] = raw_idx["Close"].ewm(span=20).mean()
                # 날짜별 트렌드 (종가 > ema20) 판정
                market_trends[index_ticker] = (raw_idx["Close"] > raw_idx["ema20"]).to_dict()
                print(f"  📈 지수 {index_ticker} 모멘텀 수집 완료")
        except Exception as e:
            print(f"  ⚠ 지수 {index_ticker} 수집 실패: {e}")

    best_all = migrate_json_structure(load_json(BEST_FILE))
    history = migrate_history(load_json(HISTORY_FILE))
    gene_pool = migrate_gene_pool(load_json(GENE_POOL_FILE))
    meta = load_json(META_FILE)

    today_results = {}
    improved_tickers = []
    df_latest = {}  # 오늘의 신호용
    lockbox_ledger = LockboxLedger(paths.state_dir / "final_lockbox_ledger.json")

    for ticker in TICKERS:
        print(f"\n[{ticker}] 데이터 로드 중...")
        ticker_data_hash = ""
        ticker_lockbox_split = None
        research_df = None
        try:
            raw = _fetch_market_data(data_service, ticker, "5y")

            if raw.empty or len(raw) < 250:
                print("  ⚠ 데이터 부족")
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()

            # 데이터 무결성 검증 (0 이하 값, NaN 및 Inf 값 정비)
            raw = raw[
                (raw["Open"] > 0)
                & (raw["High"] > 0)
                & (raw["Low"] > 0)
                & (raw["Close"] > 0)
                & (raw["Volume"] >= 0)
            ]
            raw = raw.replace([np.inf, -np.inf], np.nan).dropna()

            if len(raw) < 200:
                print(f"  ⚠ 유효 데이터 부족 ({len(raw)}행)")
                continue

            ticker_data_hash = dataframe_sha256(raw)
            df = add_indicators(raw)
            df_latest[ticker] = df
            research_df = df
            if optimize:
                research_df, ticker_lockbox_split = _partition_research_data(df, settings)
            warmup_rows = int(df.attrs.get("warmup_rows_dropped", 0))
            print(
                f"  {len(df)}행 | 워밍업 제외 {warmup_rows}행 | "
                "지표: RSI/EMA/MACD/BB/StochRSI/OBV/ADX/Regime"
            )
            if run_context:
                run_context.logger.info(
                    "indicators calculated",
                    extra={
                        "run_id": run_context.run_id,
                        "ticker": ticker,
                        "event": "indicator_warmup",
                        "warmup_rows": warmup_rows,
                        "detail": df.attrs.get("indicator_warmup_rows", {}),
                    },
                )
        except Exception as e:
            if run_context:
                run_context.logger.exception(
                    "ticker data failed",
                    extra={
                        "run_id": run_context.run_id,
                        "ticker": ticker,
                        "event": "data_failure",
                    },
                )
            print(f"  ✗ {e}")
            continue

        if not optimize:
            continue
        if research_df is None:
            continue

        # 국면별로 나누어 진화 최적화 진행
        best_all.setdefault(ticker, {})
        gene_pool.setdefault(ticker, {})
        history.setdefault(ticker, {})

        for regime in ["bull", "bear", "sideways"]:
            print(f"  └ [{regime.upper()} 국면] 최적화 진화...")

            pool = gene_pool[ticker].setdefault(regime, [])
            prev_data = best_all[ticker].setdefault(regime, {})
            if prev_data is None:
                prev_data = {}
                best_all[ticker][regime] = prev_data

            if strategy_is_approved(
                prev_data,
                require_final_lockbox=settings.research.final_lockbox_enabled,
                require_selection_bias=settings.research.selection_bias_enabled,
            ):
                prev_val_metrics = prev_data.get("val_metrics") or {}
                prev_metrics = prev_data.get("metrics") or {}
                prev_fitness = prev_val_metrics.get(
                    "fitness",
                    prev_val_metrics.get(
                        "sharpe", prev_metrics.get("fitness", prev_metrics.get("sharpe", -999))
                    ),
                )
            else:
                prev_fitness = -999

            best_run = None
            best_fitness = prev_fitness
            valid_n = 0
            no_improve = 0  # 적응형 변이율용
            regime_seed = derive_seed(settings.random_seed, ticker, regime)
            random.seed(regime_seed)
            np.random.seed(regime_seed)
            evaluated_runs = 0
            early_stopped = False
            candidate_oos_returns: dict[str, list[float]] = {}

            print(f"    {SIM_RUNS}회 시뮬레이션 (유전자풀 {len(pool)}개)...", end="", flush=True)

            for run_i in range(SIM_RUNS):
                evaluated_runs = run_i + 1
                if should_early_stop(
                    evaluated_runs=run_i,
                    no_improvement_runs=no_improve,
                    minimum_runs=min(SIM_RUNS, settings.research.ga_min_runs),
                    patience=settings.research.ga_early_stop_patience,
                ):
                    early_stopped = True
                    break
                try:
                    # 적응형 변이율: 개선 없으면 높임
                    mut_rate = 0.35 if no_improve > 80 else 0.25

                    # 파라미터 생성
                    if pool and random.random() < GENETIC_RATIO:  # nosec B311
                        if len(pool) >= 2 and random.random() < 0.35:  # nosec B311
                            p1 = tournament_select(pool)
                            p2 = tournament_select(pool)
                            p = crossover(p1["params"], p2["params"])
                        else:
                            parent = tournament_select(pool)
                            p = mutate(parent["params"], rate=mut_rate)
                    else:
                        # 메타 가중 샘플링
                        use_meta = random.random() < 0.7  # nosec B311
                        p = sample_params(meta, use_meta=use_meta)
                    p["ticker"] = ticker

                    # 멀티 윈도우 Walk-Forward 검증 (특정 국면으로 제한)
                    tr_m, val_m = multi_window_validate(
                        research_df,
                        p,
                        market_trends,
                        target_regime=regime,
                    )
                    if tr_m is None:
                        no_improve += 1
                        continue
                    valid_n += 1
                    candidate_key = stable_hash(
                        {
                            "ticker": ticker,
                            "regime": regime,
                            "params": p,
                            "fitness_version": settings.research.fitness_version,
                        }
                    )
                    fold_returns = oos_fold_returns(val_m or {})
                    if len(fold_returns) == int((val_m or {}).get("windows", 0)):
                        candidate_oos_returns[candidate_key] = fold_returns

                    success = (
                        tr_m["win_rate"] >= 48
                        and tr_m["profit_factor"] >= 1.2
                        and tr_m["total_return"] > 0
                    )
                    update_meta(meta, p, success)
                    if not success:
                        no_improve += 1
                        continue

                    eval_fitness = val_m["fitness"] if val_m else tr_m["fitness"]
                    if val_m and val_m.get("total_return", 0) <= 0:
                        no_improve += 1
                        continue

                    if eval_fitness > best_fitness:
                        # Kelly 값은 참고용으로만 저장한다. 검증 뒤 params를 바꾸면
                        # 검증한 전략과 실제 실행 전략이 달라진다.
                        kelly_position = kelly_size(
                            tr_m["win_rate"], tr_m["avg_win"], tr_m["avg_loss"]
                        )
                        best_fitness = eval_fitness
                        no_improve = 0
                        best_run = {
                            "ticker": ticker,
                            "regime": regime,
                            "params": p,
                            "metrics": tr_m,
                            "val_metrics": val_m,
                            "updated": today,
                            "run_time": run_time,
                            "kelly_pos": kelly_position,
                            "tested_pos_size": p.get("pos_size"),
                            "selection_candidate_key": candidate_key,
                            "engine_version": 6,
                            "fitness_version": settings.research.fitness_version,
                            "random_seed": regime_seed,
                            "execution_model": settings.execution.model_dump(),
                        }
                    else:
                        no_improve += 1
                except Exception as sim_err:
                    no_improve += 1
                    if run_i < 3:  # 처음 3회만 에러 로깅 (반복 에러 방지)
                        print(
                            f"\n    ⚠ 시뮬레이션 {run_i + 1}회 오류: {type(sim_err).__name__}: {sim_err}"
                        )
                    continue

            print(
                f" 완료 (유효 {valid_n}회, 평가 {evaluated_runs}회"
                f"{', 조기종료' if early_stopped else ''})"
            )

            try:
                if best_run:
                    best_run["evaluated_runs"] = evaluated_runs
                    best_run["early_stopped"] = early_stopped
                    best_run = numpy_to_python(best_run)
                    m = best_run["metrics"]
                    vm = best_run.get("val_metrics") or {}
                    p = best_run["params"]
                    validation = assess_validation(m, vm)
                    selection_key = best_run.get("selection_candidate_key")
                    selected_returns = candidate_oos_returns.get(str(selection_key), [])
                    selection_bias = assess_candidate_selection(
                        list(candidate_oos_returns.values()),
                        selected_returns,
                        evaluated_trials=evaluated_runs,
                    )
                    best_run["selection_bias"] = selection_bias
                    validation["selection_bias"] = selection_bias
                    if not selection_bias["approved"]:
                        validation["approved"] = False
                        validation["reasons"].extend(selection_bias["reasons"])
                    if validation["approved"] and settings.research.final_lockbox_enabled:
                        if ticker_lockbox_split is None:
                            validation["approved"] = False
                            validation["reasons"].append("missing_final_lockbox_split")
                        else:
                            ledger_key = final_lockbox_key(
                                data_hash=ticker_data_hash,
                                ticker=ticker,
                                regime=regime,
                                params=p,
                                split=ticker_lockbox_split,
                                fitness_version=settings.research.fitness_version,
                                evaluation_context={
                                    "engine_version": 6,
                                    "initial_capital": settings.initial_capital,
                                    "transaction_fee": settings.transaction_fee,
                                    "slippage": settings.slippage,
                                    "execution": settings.execution.model_dump(),
                                },
                            )

                            def evaluate_lockbox(frame):
                                trades, capital, capital_history = backtest(
                                    frame,
                                    p,
                                    market_trends,
                                    target_regime=regime,
                                    initial_skip=0,
                                )
                                return calc_metrics(
                                    trades,
                                    capital,
                                    capital_history,
                                    min_trades=1,
                                    fitness_version=settings.research.fitness_version,
                                )

                            final_lockbox = evaluate_final_lockbox(
                                df,
                                split=ticker_lockbox_split,
                                development_metrics=vm,
                                evaluate_fn=evaluate_lockbox,
                                ledger=lockbox_ledger,
                                ledger_key=ledger_key,
                                metric_key="annualized_return",
                                minimum_retention=settings.research.final_lockbox_min_retention,
                                require_positive_return=(
                                    settings.research.final_lockbox_require_positive_return
                                ),
                            )
                            best_run["final_lockbox"] = final_lockbox
                            validation["final_lockbox"] = final_lockbox
                            if not final_lockbox["approved"]:
                                validation["approved"] = False
                                validation["reasons"].extend(final_lockbox["reasons"])
                    best_run["validation"] = validation
                    best_run["validation_status"] = (
                        "approved" if validation["approved"] else "rejected"
                    )
                    if not validation["approved"]:
                        print(
                            f"    ⚠ [{regime.upper()}] OOS 재검증 거부: "
                            f"{', '.join(validation['reasons'])}"
                        )
                        today_results.setdefault(ticker, {})[regime] = best_run
                        continue
                    if run_context:
                        trade_log, _, equity_history = backtest(
                            research_df,
                            p,
                            market_trends,
                            target_regime=regime,
                            initial_skip=0,
                        )
                        trade_path = run_context.run_dir / "trades" / f"{ticker}_{regime}.json"
                        trade_path.parent.mkdir(parents=True, exist_ok=True)
                        save_json(trade_log, str(trade_path))
                        run_context.record_artifact(trade_path)
                        equity_path = run_context.run_dir / "equity" / f"{ticker}_{regime}.json"
                        equity_path.parent.mkdir(parents=True, exist_ok=True)
                        save_json(
                            equity_curve_records(trade_log, equity_history),
                            str(equity_path),
                        )
                        run_context.record_artifact(equity_path)
                        best_run["trade_log_file"] = str(
                            trade_path.relative_to(run_context.run_dir)
                        )
                        best_run["equity_curve_file"] = str(
                            equity_path.relative_to(run_context.run_dir)
                        )
                        best_run["trade_log_count"] = len(trade_log)
                    print(f"    ✅ [{regime.upper()}] 전략 개선!")
                    print(
                        f"       [학습] 수익 {m['total_return']}% | Sharpe {m['sharpe']} | Sortino {m.get('sortino', '?')}"
                    )
                    print(
                        f"       [검증] 수익 {vm.get('total_return', '?')}% | Sharpe {vm.get('sharpe', '?')} ({vm.get('windows', '?')}구간)"
                    )
                    print(
                        f"       ADX필터 {'ON' if p.get('use_adx_filter') else 'OFF'}(임계치:{p.get('adx_threshold')}) | Kelly {float(p['pos_size']) * 100:.0f}%"
                    )

                    best_all[ticker][regime] = best_run
                    today_results.setdefault(ticker, {})[regime] = best_run
                    if ticker not in improved_tickers:
                        improved_tickers.append(ticker)

                    pool.append({"params": p, "sharpe": best_fitness, "fitness": best_fitness})
                    pool.sort(key=lambda x: x.get("fitness", x.get("sharpe", -999)), reverse=True)
                    gene_pool[ticker][regime] = pool[:TOP_K]

                    if regime not in history[ticker]:
                        history[ticker][regime] = []
                    history[ticker][regime].append(
                        {
                            "date": today,
                            "metrics": m,
                            "val_metrics": vm,
                            "params": p,
                            "selection_bias": best_run.get("selection_bias"),
                            "final_lockbox": best_run.get("final_lockbox"),
                        }
                    )
                else:
                    prev = best_all.get(ticker, {}).get(regime, {})
                    pm = prev.get("val_metrics") or prev.get("metrics", {})
                    print(
                        f"    → [{regime.upper()}] 기존 유지 (Sharpe {pm.get('sharpe', '?')} | 수익 {pm.get('total_return', '?')}%)"
                    )
            except Exception as e:
                print(f"    ✗ 결과 처리 오류: {e}")

    # 오늘의 신호 생성
    try:
        signals = check_today_signals(
            df_latest,
            best_all,
            vix_val,
            market_trends,
            require_approved=require_approved,
            require_final_lockbox=settings.research.final_lockbox_enabled,
            require_selection_bias=settings.research.selection_bias_enabled,
            require_cost_survival=settings.research.cost_survival_enabled,
            round_trip_cost_bps_value=(settings.transaction_fee + settings.slippage)
            * 2.0
            * 10_000.0,
        )
        save_json(signals, SIGNAL_FILE)
    except Exception as e:
        signals = {}
        print(f"  ⚠ 신호 생성 오류: {e}")

    # 저장
    save_json(best_all, BEST_FILE)
    save_json(history, HISTORY_FILE)
    save_json(gene_pool, GENE_POOL_FILE)
    save_json(meta, META_FILE)
    log = (
        str(run_context.run_dir / "result.json")
        if run_context
        else os.path.join(LOG_DIR, f"sim_{today}_{now.strftime('%H%M')}.json")
    )
    save_json(
        {
            "run_time": run_time,
            "improved": improved_tickers,
            "results": today_results,
            "signals": signals,
        },
        log,
    )
    if run_context:
        run_context.record_artifact(Path(log))
        validation_path = run_context.run_dir / "validation_report.json"
        save_json(
            {
                ticker: {regime: result.get("validation", {}) for regime, result in regimes.items()}
                for ticker, regimes in today_results.items()
            },
            str(validation_path),
        )
        run_context.record_artifact(validation_path)
        selection_path = run_context.run_dir / "selection_bias_report.json"
        save_json(
            {
                ticker: {
                    regime: result.get("selection_bias")
                    for regime, result in regimes.items()
                    if result.get("selection_bias") is not None
                }
                for ticker, regimes in today_results.items()
            },
            str(selection_path),
        )
        run_context.record_artifact(selection_path)
        lockbox_path = run_context.run_dir / "final_lockbox_report.json"
        save_json(
            {
                ticker: {
                    regime: result.get("final_lockbox")
                    for regime, result in regimes.items()
                    if result.get("final_lockbox") is not None
                }
                for ticker, regimes in today_results.items()
            },
            str(lockbox_path),
        )
        run_context.record_artifact(lockbox_path)

    # 최종 리포트
    print(f"\n{'=' * 68}")
    print("  📊 최적 전략 현황 (국면별)")
    print(f"{'=' * 68}")
    kakao_lines = []
    for t in TICKERS:
        print(f"\n  [{t}]")
        sig_data = signals.get(t, {})
        sig = sig_data.get("signal", "?")
        today_reg = sig_data.get("regime", "?")
        print(f"   오늘의 국면: {today_reg.upper()} | 신호: {sig}")

        for regime in ["bull", "bear", "sideways"]:
            data = best_all.get(t, {}).get(regime)
            if not data or not data.get("params"):
                continue
            m = data.get("val_metrics") or data.get("metrics", {})
            p = data["params"]
            tag = "[검증]" if data.get("val_metrics") else "[학습]"
            star = "⭐" if regime == today_reg else "  "
            print(
                f"   {star} [{regime.upper()}] {tag} | 수익 {m.get('total_return', '?')}% | Sharpe {m.get('sharpe', '?')} | Sortino {m.get('sortino', '?')}"
            )
            print(
                f"       손절 {'ATR×' + str(p.get('atr_mult_stop')) if p.get('use_atr_stop') else str(float(p.get('stop_pct', 0)) * 100) + '%'}"
            )
            print(
                f"       목표 +{float(p.get('target_pct', 0)) * 100:.1f}% | ADX필터 {'ON' if p.get('use_adx_filter') else 'OFF'} | Kelly {float(p.get('pos_size', 0.2)) * 100:.0f}%"
            )

        # 오늘 활성 국면 정보로 카카오 전송용 요약 작성
        active_data = best_all.get(t, {}).get(today_reg, {})
        if active_data:
            m = active_data.get("val_metrics") or active_data.get("metrics", {})
            kakao_lines.append(
                f"{t}({today_reg.upper()}): 승률{m.get('win_rate', '?')}% 수익{m.get('total_return', '?')}% {sig}"
            )
        else:
            kakao_lines.append(f"{t}: 설정없음 {sig}")

    print(f"\n{'=' * 68}")
    print("  🎯 오늘의 진입 신호")
    print(f"{'=' * 68}")
    for t, sig_data in signals.items():
        print(
            f"  [{t}] {sig_data.get('signal', '?')} "
            f"(국면: {sig_data.get('regime', '?').upper()}) | "
            f"현재가: {format_market_price(t, sig_data.get('price'))}"
        )
        for cond_name, cond_val in sig_data.get("conditions", {}).items():
            print(f"       {cond_name}: {cond_val}")

    print(f"\n  로그: {log}")
    print(f"{'=' * 68}\n")

    if notify:
        try:
            from .notifications import KakaoNotifier, build_simulation_message

            notifier = KakaoNotifier(settings, paths)
            res = notifier.send(
                build_simulation_message(
                    run_time=run_time,
                    vix_value=vix_val,
                    improved_tickers=improved_tickers,
                    summary_lines=kakao_lines,
                )
            )
            print(f"  카카오톡 전송 결과: {res}")
        except Exception as e:
            if run_context:
                run_context.logger.exception(
                    "notification failed",
                    extra={
                        "run_id": run_context.run_id,
                        "event": "notification_failure",
                    },
                )
            print(f"  ⚠ 카카오톡 알림 전송 실패: {e}")

    if run_context:
        run_context.logger.info(
            "simulation completed",
            extra={
                "run_id": run_context.run_id,
                "event": "simulation_complete",
                "status": "success",
            },
        )

    return best_all, kakao_lines, improved_tickers, signals


if __name__ == "__main__":
    run()
