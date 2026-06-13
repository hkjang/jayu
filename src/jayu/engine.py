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

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import yfinance as yf
import pandas as pd
import numpy as np
import json, os, random, copy, time
from datetime import datetime
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

from .data import DataRequest
from .execution import (
    AtrParticipationSlippageModel,
    ExecutionModel,
    FixedRateFeeModel,
    FixedSlippageModel,
)
from .genetic import derive_seed, should_early_stop
from .indicators import indicator_warmup_report
from .performance import (
    calc_metrics,
    equity_curve_records,
)
from .settings import Settings
from .strategy_space import (
    active_parameter_space,
    combined_parameter_space,
    infer_strategy_mode,
    load_strategy_spaces,
    normalize_strategy_params,
    validate_params,
)
from .validation import assert_purged_splits, purged_walk_forward_splits
from .yahoo import get_yahoo_session

# ── 설정 ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SETTINGS = Settings()
_RUNTIME_PATHS = _DEFAULT_SETTINGS.runtime_paths(PROJECT_ROOT)

BASE_DIR        = str(PROJECT_ROOT)
TICKERS         = list(_DEFAULT_SETTINGS.tickers)
INITIAL_CAPITAL = _DEFAULT_SETTINGS.initial_capital
SIM_RUNS        = _DEFAULT_SETTINGS.sim_runs
TRANSACTION_FEE = _DEFAULT_SETTINGS.transaction_fee
SLIPPAGE        = _DEFAULT_SETTINGS.slippage

GENETIC_RATIO   = 0.65
TOP_K           = 15
MIN_TRADES      = 5
MAX_POS         = 0.30
LOG_DIR         = str(_RUNTIME_PATHS.runs_dir)
BEST_FILE       = str(_RUNTIME_PATHS.best_strategy_file)
HISTORY_FILE    = str(_RUNTIME_PATHS.strategy_history_file)
GENE_POOL_FILE  = str(_RUNTIME_PATHS.gene_pool_file)
META_FILE       = str(_RUNTIME_PATHS.meta_learning_file)
SIGNAL_FILE     = str(_RUNTIME_PATHS.signal_file)
_ACTIVE_EXECUTION_MODEL = ExecutionModel(
    path_mode="worst_case",
    max_participation_rate=1.0,
    fee_model=FixedRateFeeModel(TRANSACTION_FEE),
    slippage_model=AtrParticipationSlippageModel(floor=SLIPPAGE),
)
_ACTIVE_RESEARCH = _DEFAULT_SETTINGS.research


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
    return paths

# ── 파라미터 공간 및 기술 지표 ───────────────────────────────────
STRATEGY_SPACES = load_strategy_spaces()
# Keep PARAM_SPACE as a compatibility view for meta-learning and legacy imports.
# New candidates are sampled from a single strategy mode's active space.
PARAM_SPACE = combined_parameter_space(STRATEGY_SPACES)


def compute_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    ag    = gain.ewm(com=period-1, min_periods=period).mean()
    al    = loss.ewm(com=period-1, min_periods=period).mean()
    rsi = 100 - (100 / (1 + ag / al.replace(0, np.nan)))
    return rsi.fillna(50.0)

def compute_macd(series, fast=12, slow=26, signal=9):
    ef = series.ewm(span=fast).mean()
    es = series.ewm(span=slow).mean()
    line = ef - es
    sig  = line.ewm(span=signal).mean()
    hist = line - sig
    return line, sig, hist

def compute_bbands(series, period=20, n_std=2.0):
    sma  = series.rolling(period).mean()
    std  = series.rolling(period).std()
    upper = sma + n_std * std
    lower = sma - n_std * std
    pct_b = (series - lower) / (upper - lower + 1e-10)  # 0=하단, 1=상단
    width = (upper - lower) / sma.replace(0, np.nan)     # 밴드폭 (변동성)
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
    h_l = df['High'] - df['Low']
    h_pc = (df['High'] - df['Close'].shift(1)).abs()
    l_pc = (df['Low'] - df['Close'].shift(1)).abs()
    return pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)


def compute_atr(df, period=14):
    return compute_true_range(df).ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def compute_adx(df, period=14):
    tr = compute_true_range(df)

    up_move = df['High'] - df['High'].shift(1)
    down_move = df['Low'].shift(1) - df['Low']

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_smooth = pd.Series(tr).ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()
    plus_dm_smooth = pd.Series(plus_dm, index=df.index).ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()
    minus_dm_smooth = pd.Series(minus_dm, index=df.index).ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()

    plus_di = 100 * (plus_dm_smooth / tr_smooth.replace(0, np.nan)).fillna(0.0)
    minus_di = 100 * (minus_dm_smooth / tr_smooth.replace(0, np.nan)).fillna(0.0)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.fillna(0.0).ewm(alpha=1.0/period, adjust=False, min_periods=period).mean().fillna(0.0)
    return adx

def add_indicators(df):
    df = df.copy()
    # 기존
    df['rsi']       = compute_rsi(df['Close'])
    df['rsi2']      = compute_rsi(df['Close'], period=2)
    df['sma5']      = df['Close'].rolling(5).mean()
    df['sma200']    = df['Close'].rolling(200).mean()
    df['ema10']     = df['Close'].ewm(span=10).mean()
    df['ema20']     = df['Close'].ewm(span=20).mean()
    df['ema50']     = df['Close'].ewm(span=50).mean()
    df['ema200']    = df['Close'].ewm(span=200).mean()
    df['vol_ratio'] = df['Volume'] / df['Volume'].rolling(20).mean()
    df['gap']       = df['Open'] / df['Close'].shift(1) - 1
    df['atr']       = compute_atr(df)
    df['atr_pct']   = df['atr'] / df['Close']
    df['dollar_volume'] = df['Close'] * df['Volume']
    df['dollar_volume_ma20'] = df['dollar_volume'].rolling(20).mean().fillna(100_000_000)
    df['volume_ma20'] = df['Volume'].rolling(20).mean().fillna(10_000_000)
    for n in [5, 10, 15, 20]:
        df[f'high_max_{n}'] = df['High'].shift(1).rolling(n).max()
    # 신규
    ml, ms, mh      = compute_macd(df['Close'])
    df['macd_line'] = ml
    df['macd_sig']  = ms
    df['macd_hist'] = mh
    df['macd_cross']= (mh > 0) & (mh.shift(1) <= 0)  # 상향 교차
    df['bb_pct'], df['bb_width'] = compute_bbands(df['Close'])
    df['stoch_rsi'] = compute_stoch_rsi(df['rsi'])
    df['obv']       = compute_obv(df['Close'], df['Volume'])
    df['obv_trend'] = df['obv'].ewm(span=10).mean() > df['obv'].ewm(span=30).mean()
    df['adx']       = compute_adx(df)
    # 래리 윌리엄스 변동성 돌파용 지표
    df['noise_ratio_day'] = 1.0 - (df['Close'] - df['Open']).abs() / (df['High'] - df['Low']).replace(0, np.nan)
    df['noise_ratio'] = df['noise_ratio_day'].rolling(20).mean().fillna(0.5)
    df['k_dynamic'] = 0.3 + df['noise_ratio'] * 0.3
    df['prev_range'] = df['High'].shift(1) - df['Low'].shift(1)
    # 시장 국면: 200일 EMA 기준
    df['regime']    = np.where(df['Close'] > df['ema200'] * 1.02, 'bull',
                      np.where(df['Close'] < df['ema200'] * 0.98, 'bear', 'sideways'))
    before = len(df)
    result = df.dropna()
    result.attrs["warmup_rows_dropped"] = before - len(result)
    result.attrs["minimum_warmup_rows"] = 200
    result.attrs["indicator_warmup_rows"] = indicator_warmup_report()
    return result

# ── Kelly Criterion 포지션 사이징 ────────────────────────────────
def kelly_size(win_rate_pct, avg_win_pct, avg_loss_pct, max_size=MAX_POS):
    # 분모 0 방지 및 비정상 거래 통계 처리
    if win_rate_pct <= 0 or win_rate_pct > 100:
        return 0.10

    # 평균 손실이 양수이거나 0에 극도로 수렴하는 경우 방어
    if avg_loss_pct >= -0.01:
        # 손실이 거의 없는 훌륭한 전략이지만, 과투자 방지를 위해 승률 비례 기본값 할당
        return round(min(0.10 + (win_rate_pct / 1000), max_size), 2)

    p = win_rate_pct / 100
    q = 1 - p

    # 안전한 나눗셈 처리
    denominator = abs(avg_loss_pct)
    b = abs(avg_win_pct) / denominator  # 배당비율

    if b <= 0:
        return 0.10

    k = (p * b - q) / b                  # Kelly %

    # Half Kelly 기법 적용
    half_k = k * 0.5

    # 극단적인 비중 제약 방어 (10% ~ max_size 범위)
    constrained_k = max(min(half_k, max_size), 0.10)
    return round(constrained_k, 2)

# ── 백테스트 v3 ──────────────────────────────────────────────────
def backtest(
    df,
    p,
    market_trend_dict=None,
    target_regime=None,
    execution_model=None,
    *,
    initial_skip=220,
):
    execution_model = execution_model or _ACTIVE_EXECUTION_MODEL
    p = fill_missing_params(p)
    ema_col = f"ema{p['ema_span']}"
    capital = float(INITIAL_CAPITAL)
    trades, capitals = [], [capital]
    # Internal research folds pass initial_skip=0 because add_indicators()
    # already removed the complete indicator warmup. The default preserves
    # compatibility for callers that relied on the legacy API.
    i = initial_skip

    while i < len(df) - p['hold_days'] - 2:
        row   = df.iloc[i]
        close = float(row['Close'])
        ema   = float(row[ema_col])
        atr   = float(row['atr']) if row['atr'] > 0 else close * 0.02

        # ── 유동성 가드 검사 ──────────────────────────────────────
        min_vol = p.get('min_dollar_volume', 10_000_000)
        if 'dollar_volume_ma20' in row and float(row['dollar_volume_ma20']) < min_vol:
            i += 1; continue

        # 시장 지수 모멘텀 필터 적용
        market_ok = True
        if market_trend_dict:
            date_key = df.index[i]
            idx_name = '^SOX' if p.get('ticker') == 'SOXL' else '^IXIC'
            if idx_name in market_trend_dict:
                market_ok = market_trend_dict[idx_name].get(date_key, True)

        # ── 앙상블 진입 조건 ──────────────────────────────────────
        conds = {
            'rsi'    : p['rsi_lo'] <= float(row['rsi']) <= p['rsi_hi'],
            'ema'    : close > ema,
            'volume' : float(row['vol_ratio']) >= p['vol_mult'],
            'gap'    : float(row['gap']) >= p['gap_min'],
            'macd'   : bool(row['macd_cross']) if p['require_macd'] else True,
            'bb'     : float(row['bb_pct']) < 0.4 if p['require_bb'] else True,
            'regime' : row['regime'] != 'bear' if p['regime_filter'] else True,
            'obv'    : bool(row['obv_trend']),
            'stoch'  : float(row['stoch_rsi']) < 0.8,
        }

        strategy_mode = infer_strategy_mode(p)
        use_connors = strategy_mode == 'connors_rsi2'
        use_williams = strategy_mode == 'williams_breakout'
        use_volume = strategy_mode == 'volume_breakout'
        mandatory = conds['volume'] and conds['gap'] and market_ok

        if use_williams:
            williams_target = float(row['Open']) + float(row['prev_range']) * float(row['k_dynamic']) * p.get('williams_k_multiplier', 1.0)
            williams_ok = (close > williams_target) and (close > float(row['sma200']))
            if not (mandatory and williams_ok):
                i += 1; continue
            optionals = []
            optional_met = 0
        elif use_volume:
            vol_mult = p.get('volume_spike_mult', 2.0)
            vol_period = p.get('volume_breakout_period', 10)
            high_col = f'high_max_{vol_period}'
            volume_spike = float(row['Volume']) > float(row['volume_ma20']) * vol_mult
            price_break = close > float(row[high_col]) if high_col in row else False
            trend_ok = close > float(row['sma200'])
            volume_ok = volume_spike and price_break and trend_ok
            if not (mandatory and volume_ok):
                i += 1; continue
            optionals = []
            optional_met = 0
        elif use_connors:
            connors_ok = (close > float(row['sma200'])) and (float(row['rsi2']) < p.get('connors_rsi2_limit', 10))
            if not (mandatory and connors_ok):
                i += 1; continue
            optionals = []
            optional_met = 0
        else:
            # ADX 필터 작동시 진입성격 스위칭
            use_adx = p.get('use_adx_filter', False)
            adx_val = float(row['adx']) if 'adx' in row else 0.0

            # ADX 국면에 따른 필수 조건 분기
            if use_adx and adx_val > p.get('adx_threshold', 25):
                mandatory = mandatory and conds['ema']
                if p['require_macd']:
                    mandatory = mandatory and conds['macd']
                optionals = [conds['rsi'], conds['macd'] if not p['require_macd'] else True,
                             conds['bb'], conds['regime'], conds['obv'], conds['stoch']]
            elif use_adx and adx_val < 20:
                mandatory = mandatory and conds['rsi']
                if p['require_bb']:
                    mandatory = mandatory and conds['bb']
                optionals = [conds['ema'], conds['macd'], conds['bb'] if not p['require_bb'] else True,
                             conds['regime'], conds['obv'], conds['stoch']]
            else:
                # 기본 모드
                mandatory = mandatory and conds['rsi'] and conds['ema']
                optionals = [conds['macd'], conds['bb'], conds['regime'], conds['obv'], conds['stoch']]

            optional_met = sum([bool(cond) for cond in optionals])

            if not mandatory or optional_met < p['ensemble_min']:
                i += 1; continue

        entry_raw = float(df.iloc[i+1]['Open'])
        if entry_raw <= 0: i += 1; continue
        entry_idx = i + 1

        # ── 포지션 비중 결정 (Kelly + Volatility Sizing) ──────────
        confidence_score = optional_met / len(optionals) if optionals else 0.6
        confidence_score = max(0.2, min(confidence_score, 1.0))
        base_pos_size = p['pos_size'] * confidence_score * p.get('kelly_fraction', 0.50)

        if p.get('use_volatility_sizing', False):
            atr_pct = float(row['atr_pct']) if 'atr_pct' in row and row['atr_pct'] > 0 else (atr / close)
            atr_mult_stop = p.get('atr_mult_stop', 2.0) if p['use_atr_stop'] else (p['stop_pct'] / (atr / close))
            max_risk = p.get('max_risk_per_trade_pct', 0.015)
            risk_adjusted_size = max_risk / (atr_mult_stop * atr_pct)
            actual_pos_size = min(base_pos_size, risk_adjusted_size)
        else:
            actual_pos_size = base_pos_size

        actual_pos_size = max(min(actual_pos_size, MAX_POS), 0.05)

        # ── 변동성 및 시장 충격 슬리피지 적용 ─────────────────────
        dollar_vol_20 = float(row['dollar_volume_ma20']) if 'dollar_volume_ma20' in row else 100_000_000
        actual_pos_size, fill_ratio = execution_model.position_size_cap(
            capital=capital,
            requested_fraction=actual_pos_size,
            average_dollar_volume=dollar_vol_20,
        )
        if actual_pos_size <= 0:
            i += 1
            continue
        dynamic_slippage = execution_model.slippage_rate(
            atr=atr,
            close=close,
            order_notional=capital * actual_pos_size,
            average_dollar_volume=dollar_vol_20,
        )

        entry = entry_raw * (1.0 + dynamic_slippage)

        # ── 손절/목표 결정 ────────────────────────────────────────
        stop_dist   = (atr * p['atr_mult_stop']) if p['use_atr_stop'] else (entry * p['stop_pct'])
        stop_price  = entry - stop_dist

        use_atr_tgt = p.get('use_atr_target', False)
        target_dist = (atr * p.get('atr_mult_target', 2.0)) if use_atr_tgt else (entry * p['target_pct'])
        target_price= entry + target_dist
        trail_floor = stop_price  # 트레일링 시작점

        exit_price, exit_reason = None, 'time'
        exit_trigger = 'time_limit'
        exit_idx = None
        peak = entry
        worst_lo = entry
        breakeven_activated = False

        for j in range(1, p['hold_days'] + 2):
            idx = i + 1 + j
            if idx >= len(df): break
            fut = df.iloc[idx]
            opn = float(fut['Open'])
            hi  = float(fut['High'])
            lo  = float(fut['Low'])

            worst_lo = min(worst_lo, lo)

            # 본전 손절(Break-Even Stop) 작동 여부 감시
            if p.get('use_breakeven_stop', False) and not breakeven_activated:
                trigger_price = entry + (target_dist * p.get('breakeven_trigger_pct', 0.5))
                if hi >= trigger_price:
                    breakeven_activated = True
                    # 손절선을 수수료를 감안한 보전선으로 상향
                    stop_price = max(stop_price, entry * (1.0 + TRANSACTION_FEE * 2))

            # 트레일링 스톱 업데이트
            if p['trail_stop'] and hi > peak:
                peak        = hi
                trail_floor = max(trail_floor, peak * (1 - p['trail_pct']))

            effective_stop = max(stop_price, trail_floor) if p['trail_stop'] else stop_price

            # OCO 청산 판정: 일봉 내 경로 모드와 갭 체결을 함께 적용
            decision = execution_model.resolve_daily_exit(
                open_price=opn,
                high=hi,
                low=lo,
                close=float(fut['Close']),
                stop_price=effective_stop,
                target_price=target_price,
            )
            if decision:
                exit_price = decision.price
                exit_trigger = decision.trigger
                exit_idx = idx
                exit_reason = (
                    'breakeven'
                    if breakeven_activated and decision.reason == 'stop'
                    else decision.reason
                )
                break

            # 래리 코너스 청산 조건: Close > sma5
            if strategy_mode == 'connors_rsi2' and float(fut['Close']) > float(fut['sma5']):
                exit_price, exit_reason = float(fut['Close']), 'connors_exit'
                exit_trigger, exit_idx = 'strategy_exit', idx
                break

            # 정체 청산 (Timeout Exit): 보유 기간 절반 이상 지났을 때 수익률이 미미하면 조기 탈출
            if j >= max(2, p['hold_days'] // 2):
                current_ret = ((float(fut['Close']) - entry) / entry)
                if abs(current_ret) < 0.005:  # ±0.5% 이내 횡보 시
                    exit_price, exit_reason = float(fut['Close']), 'timeout'
                    exit_trigger, exit_idx = 'stagnation_timeout', idx
                    break

            # 조기 청산: RSI 과매수 + MACD 하향교차
            if j >= 2:
                fut_rsi  = float(fut['rsi']) if not pd.isna(fut['rsi']) else 50
                fut_macd = float(fut['macd_hist']) if not pd.isna(fut['macd_hist']) else 0
                prev_macd= float(df.iloc[idx-1]['macd_hist']) if not pd.isna(df.iloc[idx-1]['macd_hist']) else 0
                if fut_rsi > 80 and fut_macd < prev_macd:
                    exit_price, exit_reason = float(fut['Close']), 'overbought'
                    exit_trigger, exit_idx = 'indicator_exit', idx
                    break

        if exit_price is None:
            fidx = min(i + 1 + p['hold_days'], len(df)-1)
            exit_price = float(df.iloc[fidx]['Close'])
            exit_idx = fidx

        exit_settled = exit_price * (1.0 - dynamic_slippage)
        fee_rate = execution_model.fee_model.round_trip_cost_rate(entry, exit_settled)
        gross_ret = (exit_settled - entry) / entry
        ret = gross_ret - fee_rate

        capital_before = capital
        pnl = capital * actual_pos_size * ret
        capital += pnl
        capitals.append(capital)

        trade_mae_pct = ((worst_lo - entry) / entry) * 100
        trades.append({
            'trade_id': len(trades) + 1,
            'signal_date': str(df.index[i].date()),
            'entry_date': str(df.index[entry_idx].date()),
            'exit_date': str(df.index[exit_idx].date()),
            'entry_price': round(entry, 6),
            'exit_price': round(exit_settled, 6),
            'gross_return_pct': round(gross_ret * 100, 4),
            'net_return_pct': round(ret * 100, 4),
            'ret': round(ret * 100, 3),
            'fee_rate_pct': round(fee_rate * 100, 4),
            'slippage_rate_pct': round(dynamic_slippage * 100, 4),
            'position_pct': round(actual_pos_size * 100, 4),
            'capital_before': round(capital_before, 2),
            'capital_after': round(capital, 2),
            'pnl': round(pnl, 2),
            'reason': exit_reason,
            'trigger': exit_trigger,
            'date': str(df.index[i].date()),
            'holding_days': max(1, exit_idx - entry_idx),
            'mae': round(trade_mae_pct, 3),
            'fill_ratio': round(fill_ratio, 4),
        })
        i += p['hold_days'] + 1

    return trades, capital, capitals

# ── 성과 지표 v3 ─────────────────────────────────────────────────
# ── 멀티 윈도우 Walk-Forward 검증 ────────────────────────────────
def multi_window_validate(df, p, market_trend_dict=None, target_regime=None):
    """Evaluate non-overlapping OOS folds with purge and embargo gaps."""
    research = _ACTIVE_RESEARCH
    splits = purged_walk_forward_splits(
        len(df),
        train_rows=research.train_months * 21,
        validation_rows=research.validation_months * 21,
        windows=research.walk_forward_windows,
        purge_rows=research.purge_days,
        embargo_rows=research.embargo_days,
    )
    assert_purged_splits(splits)
    windows = []
    for split in splits:
        df_train = df.iloc[split.train_start : split.train_end]
        df_valid = df.iloc[split.validation_start : split.validation_end]
        tr_t, tr_cap, tr_ch = backtest(
            df_train,
            p,
            market_trend_dict,
            target_regime,
            initial_skip=0,
        )
        tr_m = calc_metrics(
            tr_t,
            tr_cap,
            tr_ch,
            min_trades=2 if target_regime else MIN_TRADES,
            fitness_version=research.fitness_version,
        )
        if tr_m is None:
            continue
        min_wr = 44 if target_regime else 48
        min_pf = 1.0 if target_regime else 1.2
        if tr_m["win_rate"] < min_wr or tr_m["profit_factor"] < min_pf:
            continue
        vl_t, vl_cap, vl_ch = backtest(
            df_valid,
            p,
            market_trend_dict,
            target_regime,
            initial_skip=0,
        )
        vl_m = calc_metrics(
            vl_t,
            vl_cap,
            vl_ch,
            min_trades=1 if target_regime else MIN_TRADES,
            fitness_version=research.fitness_version,
        )
        windows.append((split, tr_m, vl_m))

    completed = [(split, tr, vl) for split, tr, vl in windows if vl]
    if len(completed) < research.min_oos_windows:
        return None, None
    positive = [item for item in completed if item[2]["total_return"] > 0]
    pass_rate = len(positive) / len(completed)
    if pass_rate < research.min_oos_pass_rate:
        return None, None

    best_tr = max(completed, key=lambda item: item[1]["fitness"])[1]
    metrics = [item[2] for item in completed]
    average_sharpe = float(np.mean([item["daily_sharpe"] for item in metrics]))
    avg_val = {
        "fitness_version": research.fitness_version,
        "fitness": round(float(np.mean([item["fitness"] for item in metrics])), 3),
        "total_return": round(
            float(np.mean([item["total_return"] for item in metrics])), 1
        ),
        "win_rate": round(float(np.mean([item["win_rate"] for item in metrics])), 1),
        "daily_sharpe": round(average_sharpe, 2),
        "sharpe": round(average_sharpe, 2),
        "max_drawdown": round(
            float(max(item["max_drawdown"] for item in metrics)), 2
        ),
        "windows": len(completed),
        "positive_windows": len(positive),
        "pass_rate": round(pass_rate, 3),
        "purge_days": research.purge_days,
        "embargo_days": research.embargo_days,
        "folds": [
            {**split.to_dict(), "train": train, "validation": validation}
            for split, train, validation in completed
        ],
    }
    return best_tr, avg_val

# ── 메타 학습 가중 샘플링 ────────────────────────────────────────
def meta_sample(meta, key, choices, default_weight=0.5):
    """성공률 기반 가중치로 파라미터 선택"""
    if key not in meta: return random.choice(choices)
    weights = []
    for c in choices:
        k = str(c)
        if k in meta[key] and meta[key][k]['total'] >= 5:
            w = meta[key][k]['wins'] / meta[key][k]['total']
        else:
            w = default_weight
        weights.append(max(w, 0.05))
    total = sum(weights)
    probs = [w/total for w in weights]
    return random.choices(choices, weights=probs, k=1)[0]


# ── 유전 알고리즘 ────────────────────────────────────────────────
def tournament_select(pool, k=3):
    """토너먼트 선택: k개 후보 중 최고 선택"""
    candidates = random.sample(pool[:min(len(pool), TOP_K)], min(k, len(pool)))
    return max(candidates, key=lambda x: x.get('fitness', x.get('sharpe', -999)))

# ── 메타 학습 업데이트 ────────────────────────────────────────────
def update_meta(meta, params, success, decay=0.98):
    for key, val in params.items():
        if key not in PARAM_SPACE: continue
        if key not in meta: meta[key] = {}

        # 기존 누적 데이터 감쇠 (최근 성공 데이터의 상대적 비중 확대)
        for k in meta[key]:
            meta[key][k]['total'] = float(meta[key][k]['total']) * decay
            meta[key][k]['wins'] = float(meta[key][k]['wins']) * decay

        k = str(val)
        if k not in meta[key]: meta[key][k] = {'wins': 0.0, 'total': 0.0}
        meta[key][k]['total'] = float(meta[key][k]['total']) + 1.0
        if success:
            meta[key][k]['wins'] = float(meta[key][k]['wins']) + 1.0
    return meta

# ── 데이터 마이그레이션 가드 ───────────────────────────────────────
DEFAULT_PARAMS = {
    'strategy_mode': 'ensemble',
    'rsi_lo'       : 40,
    'rsi_hi'       : 70,
    'ema_span'     : 20,
    'vol_mult'     : 1.5,
    'gap_min'      : 0.0,
    'use_atr_stop' : False,
    'atr_mult_stop': 2.0,
    'stop_pct'     : 0.03,
    'target_pct'   : 0.06,
    'hold_days'    : 2,
    'trail_stop'   : False,
    'trail_pct'    : 0.03,
    'require_macd' : False,
    'require_bb'   : False,
    'regime_filter': False,
    'ensemble_min' : 2,
    'use_adx_filter': False,
    'adx_threshold' : 25,
    'use_connors_rsi2': False,
    'connors_rsi2_limit': 10,
    'use_breakeven_stop': False,
    'breakeven_trigger_pct': 0.5,
    'kelly_fraction': 0.5,
    'use_williams_breakout': False,
    'williams_k_multiplier': 1.0,
    'use_atr_target'       : False,
    'atr_mult_target'      : 2.0,
    'min_dollar_volume'    : 10_000_000,
    'use_volatility_sizing': False,
    'max_risk_per_trade_pct': 0.015,
    'use_volume_breakout'  : False,
    'volume_spike_mult'    : 2.0,
    'volume_breakout_period': 10,
    'pos_size'     : 0.20
}

def fill_missing_params(params):
    if not isinstance(params, dict):
        return normalize_strategy_params(copy.deepcopy(DEFAULT_PARAMS))
    inferred_mode = infer_strategy_mode(params)
    merged = copy.deepcopy(DEFAULT_PARAMS)
    merged.update(params)
    if 'strategy_mode' not in params:
        merged['strategy_mode'] = inferred_mode
    return normalize_strategy_params(merged)


def _repair_params(params):
    child = fill_missing_params(params)
    child['pos_size'] = 0.20
    if child.get('rsi_lo', 50) >= child.get('rsi_hi', 70):
        child['rsi_hi'] = child['rsi_lo'] + 15
    if (
        not child.get('use_atr_target')
        and not child.get('use_atr_stop')
        and child.get('target_pct', 0.1) <= child.get('stop_pct', 0.03)
    ):
        child['target_pct'] = child['stop_pct'] * 2
    if child.get('use_atr_target') and child.get('use_atr_stop'):
        if child.get('atr_mult_target', 2.0) <= child.get('atr_mult_stop', 2.0):
            child['atr_mult_target'] = child['atr_mult_stop'] * 1.5
    child = normalize_strategy_params(child)
    validate_params(child)
    return child


def sample_params(meta=None, use_meta=True):
    """Sample one strategy mode and only its active parameters."""
    m = meta if (use_meta and meta) else {}

    def choose(key, choices):
        return meta_sample(m, key, choices) if use_meta else random.choice(choices)

    params = copy.deepcopy(DEFAULT_PARAMS)
    params['strategy_mode'] = choose('strategy_mode', PARAM_SPACE['strategy_mode'])
    switches = (
        'use_atr_stop',
        'use_atr_target',
        'trail_stop',
        'use_breakeven_stop',
        'use_volatility_sizing',
    )
    for switch in switches:
        params[switch] = choose(switch, PARAM_SPACE[switch])
    active = active_parameter_space(params, STRATEGY_SPACES)
    for key, choices in active.items():
        if key != 'strategy_mode' and key not in switches:
            params[key] = choose(key, choices)
    return _repair_params(params)


def mutate(params, rate=0.25):
    child = fill_missing_params(params)
    if random.random() < rate:
        child['strategy_mode'] = random.choice(PARAM_SPACE['strategy_mode'])
    child = normalize_strategy_params(child)
    for key, choices in active_parameter_space(child, STRATEGY_SPACES).items():
        if key != 'strategy_mode' and random.random() < rate:
            child[key] = random.choice(choices)
    return _repair_params(child)


def crossover(p1, p2):
    left = fill_missing_params(p1)
    right = fill_missing_params(p2)
    child = copy.deepcopy(DEFAULT_PARAMS)
    child['strategy_mode'] = random.choice(
        [left['strategy_mode'], right['strategy_mode']]
    )
    child = normalize_strategy_params(child)
    for key, choices in active_parameter_space(child, STRATEGY_SPACES).items():
        if key == 'strategy_mode':
            continue
        source = left if random.random() < 0.5 else right
        child[key] = source.get(key, random.choice(choices))
    return _repair_params(child)

def migrate_json_structure(data):
    if not isinstance(data, dict): return {}
    migrated = {}
    for ticker, val in data.items():
        if not isinstance(val, dict):
            continue
        has_regimes = any(r in val for r in ["bull", "bear", "sideways"])
        if has_regimes:
            migrated[ticker] = {}
            for r in ["bull", "bear", "sideways"]:
                r_data = val.get(r, {})
                if isinstance(r_data, dict) and 'params' in r_data:
                    migrated[ticker][r] = copy.deepcopy(r_data)
                    migrated[ticker][r]['params'] = fill_missing_params(r_data['params'])
                else:
                    migrated[ticker][r] = {
                        "ticker": ticker,
                        "params": copy.deepcopy(DEFAULT_PARAMS),
                        "metrics": {},
                        "val_metrics": {}
                    }
        else:
            r_data = copy.deepcopy(val)
            if 'params' in r_data:
                r_data['params'] = fill_missing_params(r_data['params'])
            else:
                r_data['params'] = copy.deepcopy(DEFAULT_PARAMS)
            migrated[ticker] = {
                "bull": copy.deepcopy(r_data),
                "bear": copy.deepcopy(r_data),
                "sideways": copy.deepcopy(r_data)
            }
    return migrated

def migrate_gene_pool(data):
    if not isinstance(data, dict): return {}
    migrated = {}
    for ticker, val in data.items():
        if not isinstance(val, dict):
            migrated[ticker] = {
                "bull": [],
                "bear": [],
                "sideways": []
            }
            for item in val:
                if isinstance(item, dict) and 'params' in item:
                    item_copy = copy.deepcopy(item)
                    item_copy['params'] = fill_missing_params(item_copy['params'])
                    migrated[ticker]["bull"].append(item_copy)
                    migrated[ticker]["bear"].append(copy.deepcopy(item_copy))
                    migrated[ticker]["sideways"].append(copy.deepcopy(item_copy))
        else:
            has_regimes = any(r in val for r in ["bull", "bear", "sideways"])
            if has_regimes:
                migrated[ticker] = {}
                for r in ["bull", "bear", "sideways"]:
                    migrated[ticker][r] = []
                    for item in val.get(r, []):
                        if isinstance(item, dict) and 'params' in item:
                            item_copy = copy.deepcopy(item)
                            item_copy['params'] = fill_missing_params(item_copy['params'])
                            migrated[ticker][r].append(item_copy)
            else:
                migrated[ticker] = {
                    "bull": [],
                    "bear": [],
                    "sideways": []
                }
    return migrated

def migrate_history(data):
    if not isinstance(data, dict): return {}
    migrated = {}
    for ticker, val in data.items():
        if not isinstance(val, dict):
            migrated[ticker] = {
                "bull": copy.deepcopy(val),
                "bear": copy.deepcopy(val),
                "sideways": copy.deepcopy(val)
            }
        else:
            has_regimes = any(r in val for r in ["bull", "bear", "sideways"])
            if has_regimes:
                migrated[ticker] = val
            else:
                migrated[ticker] = {
                    "bull": [],
                    "bear": [],
                    "sideways": []
                }
    return migrated

# ── 오늘의 진입 신호 ─────────────────────────────────────────────
def check_today_signals(
    df,
    best_all,
    vix_val=0.0,
    market_trends=None,
    require_approved=False,
):
    """현재 데이터 기준 진입 조건 충족 여부 (VIX, 시장 지수, 거래대금 필터 포함)"""
    best_all = migrate_json_structure(best_all)
    today_sigs = {}
    for ticker in TICKERS:
        row = df[ticker].iloc[-1] if ticker in df else None
        if row is None:
            today_sigs[ticker] = {'signal': '데이터없음'}
            continue

        # 오늘 국면 판정
        today_regime = row['regime']  # 'bull', 'bear', 'sideways'

        # 최적 파라미터 로드
        ticker_data = best_all.get(ticker, {})
        data = ticker_data.get(today_regime)
        if require_approved and data and data.get("validation_status") != "approved":
            data = None

        # 폴백 처리 (오늘 국면 설정이 없으면 다른 국면이라도 사용)
        if not data or 'params' not in data:
            for r in ["bull", "bear", "sideways"]:
                if (
                    r in ticker_data
                    and 'params' in ticker_data[r]
                    and (
                        not require_approved
                        or ticker_data[r].get("validation_status") == "approved"
                    )
                ):
                    data = ticker_data[r]
                    break

        if not data or 'params' not in data:
            today_sigs[ticker] = {
                'signal': '재검증필요' if require_approved else '설정없음',
                'action': 'hold',
                'eligible': False,
            }
            continue

        p = fill_missing_params(data['params'])

        # 시장 모멘텀 필터 검사
        market_ok = True
        idx_name = '^SOX' if ticker == 'SOXL' else '^IXIC'
        if market_trends and idx_name in market_trends:
            last_date = df[ticker].index[-1]
            market_ok = market_trends[idx_name].get(last_date, True)

        # ── 거래대금 유동성 가드 검사 ──────────────────────────
        min_vol = p.get('min_dollar_volume', 10_000_000)
        dollar_vol_ok = True
        if 'dollar_volume_ma20' in row:
            dollar_vol_ok = float(row['dollar_volume_ma20']) >= min_vol

        ema = float(row[f"ema{p['ema_span']}"])

        # 앙상블 조건 판정
        conds = {
            'rsi'    : p['rsi_lo'] <= float(row['rsi']) <= p['rsi_hi'],
            'ema'    : float(row['Close']) > ema,
            'volume' : float(row['vol_ratio']) >= p['vol_mult'],
            'gap'    : float(row['gap']) >= p['gap_min'],
            'macd'   : bool(row['macd_cross']) if p['require_macd'] else True,
            'bb'     : float(row['bb_pct']) < 0.4 if p['require_bb'] else True,
            'regime' : row['regime'] != 'bear' if p['regime_filter'] else True,
            'obv'    : bool(row['obv_trend']),
            'stoch'  : float(row['stoch_rsi']) < 0.8,
        }

        strategy_mode = infer_strategy_mode(p)
        use_connors = strategy_mode == 'connors_rsi2'
        use_williams = strategy_mode == 'williams_breakout'
        use_volume = strategy_mode == 'volume_breakout'
        mandatory = conds['volume'] and conds['gap'] and market_ok

        if use_williams:
            williams_target = float(row['Open']) + float(row['prev_range']) * float(row['k_dynamic']) * p.get('williams_k_multiplier', 1.0)
            williams_ok = (float(row['Close']) > williams_target) and (float(row['Close']) > float(row['sma200']))
            all_ok = mandatory and williams_ok and dollar_vol_ok
        elif use_volume:
            vol_mult = p.get('volume_spike_mult', 2.0)
            vol_period = p.get('volume_breakout_period', 10)
            high_col = f'high_max_{vol_period}'
            volume_spike = float(row['Volume']) > float(row['volume_ma20']) * vol_mult
            price_break = float(row['Close']) > float(row[high_col]) if high_col in row else False
            trend_ok = float(row['Close']) > float(row['sma200'])
            volume_ok = volume_spike and price_break and trend_ok
            all_ok = mandatory and volume_ok and dollar_vol_ok
        elif use_connors:
            connors_ok = (float(row['Close']) > float(row['sma200'])) and (float(row['rsi2']) < p.get('connors_rsi2_limit', 10))
            all_ok = mandatory and connors_ok and dollar_vol_ok
        else:
            # ADX 필터 및 스위칭 로직
            use_adx = p.get('use_adx_filter', False)
            adx_val = float(row['adx']) if 'adx' in row else 0.0

            if use_adx and adx_val > p.get('adx_threshold', 25):
                mandatory = mandatory and conds['ema']
                if p['require_macd']:
                    mandatory = mandatory and conds['macd']
                optionals = [conds['rsi'], conds['macd'] if not p['require_macd'] else True,
                             conds['bb'], conds['regime'], conds['obv'], conds['stoch']]
            elif use_adx and adx_val < 20:
                mandatory = mandatory and conds['rsi']
                if p['require_bb']:
                    mandatory = mandatory and conds['bb']
                optionals = [conds['ema'], conds['macd'], conds['bb'] if not p['require_bb'] else True,
                             conds['regime'], conds['obv'], conds['stoch']]
            else:
                mandatory = mandatory and conds['rsi'] and conds['ema']
                optionals = [conds['macd'], conds['bb'], conds['regime'], conds['obv'], conds['stoch']]

            optional_met = sum([bool(cond) for cond in optionals])
            all_ok = mandatory and (optional_met >= p['ensemble_min']) and dollar_vol_ok

        # 상세 조건 현황 문자열화
        conds_str = {
            'RSI'    : f"{float(row['rsi']):.0f} ({'✅' if conds['rsi'] else '❌'})",
            'EMA'    : f"{'✅' if conds['ema'] else '❌'} ({float(row['Close']):.2f} vs {ema:.2f})",
            'Volume' : f"{'✅' if conds['volume'] else '❌'} ({float(row['vol_ratio']):.1f}x)",
            'MACD'   : f"{'✅' if row['macd_hist'] > 0 else '❌'}",
            'BB'     : f"{'✅' if float(row['bb_pct']) < 0.4 else '❌'} ({float(row['bb_pct']):.2f})",
            'Regime' : f"{today_regime} (필터:{'ON' if p['regime_filter'] else 'OFF'})",
            'Market' : f"{'✅' if market_ok else '❌'} ({idx_name} 상방)",
            'Dollar_Volume': f"{'✅' if dollar_vol_ok else '❌'} (${float(row['dollar_volume_ma20'])/1_000_000:.1f}M vs ${min_vol/1_000_000:.0f}M)",
        }
        if use_williams:
            williams_target = float(row['Open']) + float(row['prev_range']) * float(row['k_dynamic']) * p.get('williams_k_multiplier', 1.0)
            conds_str['Williams_Breakout'] = f"{'✅' if float(row['Close']) > williams_target else '❌'} (종가 {float(row['Close']):.2f} vs 타겟 {williams_target:.2f})"
            conds_str['SMA200'] = f"{'✅' if float(row['Close']) > float(row['sma200']) else '❌'} (종가 {float(row['Close']):.2f} vs SMA200 {float(row['sma200']):.2f})"
            conds_str['Williams_Mode'] = 'ACTIVE'
        elif use_volume:
            vol_mult = p.get('volume_spike_mult', 2.0)
            vol_period = p.get('volume_breakout_period', 10)
            high_col = f'high_max_{vol_period}'
            volume_spike = float(row['Volume']) > float(row['volume_ma20']) * vol_mult
            price_break = float(row['Close']) > float(row[high_col]) if high_col in row else False
            conds_str['Volume_Spike'] = f"{'✅' if volume_spike else '❌'} ({float(row['Volume'])/1_000_000:.1f}M vs {float(row['volume_ma20'])/1_000_000*vol_mult:.1f}M)"
            conds_str['Price_Break'] = f"{'✅' if price_break else '❌'} (종가 {float(row['Close']):.2f} vs {vol_period}일고가 {float(row[high_col]) if high_col in row else 0.0:.2f})"
            conds_str['SMA200'] = f"{'✅' if float(row['Close']) > float(row['sma200']) else '❌'} (종가 {float(row['Close']):.2f} vs SMA200 {float(row['sma200']):.2f})"
            conds_str['Volume_Mode'] = 'ACTIVE'
        elif use_connors:
            conds_str['RSI2'] = f"{float(row['rsi2']):.1f} ({'✅' if float(row['rsi2']) < p.get('connors_rsi2_limit', 10) else '❌'}, limit:{p.get('connors_rsi2_limit', 10)})"
            conds_str['SMA200'] = f"{'✅' if float(row['Close']) > float(row['sma200']) else '❌'} (종가 {float(row['Close']):.2f} vs SMA200 {float(row['sma200']):.2f})"
            conds_str['Connors_Mode'] = 'ACTIVE'
        else:
            conds_str['ADX'] = f"{adx_val:.1f} (필터:{'ON' if use_adx else 'OFF'}, 임계치:{p.get('adx_threshold',25)})"

        if vix_val >= 22.0:
            signal_desc = f"🔴 대기 (VIX 위험: {vix_val:.1f})"
        elif not market_ok:
            signal_desc = f"🔴 대기 ({idx_name} 하락세)"
        elif not dollar_vol_ok:
            signal_desc = f"🔴 대기 (거래대금 부족: ${float(row['dollar_volume_ma20'])/1_000_000:.1f}M)"
        else:
            signal_desc = '🟢 진입 검토' if all_ok else '🔴 대기'

        today_sigs[ticker] = {
            'signal': signal_desc,
            'action': 'buy' if all_ok and vix_val < 22.0 and market_ok and dollar_vol_ok else 'hold',
            'conditions': conds_str,
            'price': round(float(row['Close']), 2),
            'regime': today_regime,
            'suggested_position_pct': float(p.get('pos_size', 0.10)),
        }
    return today_sigs

def numpy_to_python(obj):
    if isinstance(obj, dict): return {k: numpy_to_python(v) for k, v in obj.items()}
    if isinstance(obj, list): return [numpy_to_python(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)): return bool(obj)
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)): return float(obj)
    return obj

def save_json(obj, path):
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(numpy_to_python(obj), f, ensure_ascii=False, indent=2)
        if os.path.exists(tmp_path):
            os.replace(tmp_path, path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass
        raise e

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  ⚠ JSON 파싱 오류 ({path}): {e}")
            # 손상된 파일 백업 후 기본값 반환
            backup = path + '.corrupt'
            try:
                import shutil
                shutil.copy2(path, backup)
                print(f"    → 손상 파일 백업: {backup}")
            except Exception:
                pass
    return default if default is not None else {}

# ── 메인 실행 ────────────────────────────────────────────────────
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


def assess_validation(train_metrics, validation_metrics):
    reasons = []
    if not validation_metrics:
        reasons.append("missing_out_of_sample_metrics")
    else:
        if validation_metrics.get("total_return", 0) <= 0:
            reasons.append("non_positive_out_of_sample_return")
        if validation_metrics.get("windows", 0) < _ACTIVE_RESEARCH.min_oos_windows:
            reasons.append("insufficient_out_of_sample_windows")
        if (
            validation_metrics.get("pass_rate", 0)
            < _ACTIVE_RESEARCH.min_oos_pass_rate
        ):
            reasons.append("out_of_sample_pass_rate_below_threshold")
        if not validation_metrics.get("folds"):
            reasons.append("missing_purged_fold_metadata")
        train_return = abs(float(train_metrics.get("total_return", 0)))
        valid_return = abs(float(validation_metrics.get("total_return", 0)))
        if train_return / max(valid_return, 0.1) > 5:
            reasons.append("train_validation_return_ratio_above_5")
    return {
        "approved": not reasons,
        "reasons": reasons,
        "train_metrics": train_metrics,
        "validation_metrics": validation_metrics,
    }


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
    now      = datetime.now()
    today    = now.strftime('%Y-%m-%d')
    run_time = now.strftime('%Y-%m-%d %H:%M')

    print(f"\n{'='*68}")
    print(f"  🔬 단타 시뮬레이션 v4  |  {run_time}")
    print(f"  종목: {TICKERS}")
    print(f"  {SIM_RUNS}회/종목/국면 | 유전({int(GENETIC_RATIO*100)}%)+메타가중 / 랜덤({int((1-GENETIC_RATIO)*100)}%)")
    print(f"  Walk-Forward: 멀티윈도우 3구간 | ADX 스위칭 필터 | 국면별 독립 파라미터")
    print(f"{'='*68}")
    if run_context:
        run_context.logger.info(
            "simulation started",
            extra={"run_id": run_context.run_id, "event": "simulation_start"},
        )

    # VIX 지수 사전 수집
    vix_val = 0.0
    try:
        vix_df = _fetch_market_data(data_service, '^VIX', '5d')
        if not vix_df.empty:
            vix_val = float(vix_df['Close'].dropna().iloc[-1])
            print(f"  📉 현재 VIX 지수: {vix_val:.2f}")
    except Exception as e:
        print(f"  ⚠ VIX 지수 조회 실패: {e}")

    # 시장/섹터 지수 사전 수집 (SOX, IXIC)
    market_trends = {}
    for index_ticker in ['^SOX', '^IXIC']:
        try:
            raw_idx = _fetch_market_data(data_service, index_ticker, '5y')
            if not raw_idx.empty:
                if isinstance(raw_idx.columns, pd.MultiIndex):
                    raw_idx.columns = raw_idx.columns.get_level_values(0)
                # 20일 EMA 계산
                raw_idx['ema20'] = raw_idx['Close'].ewm(span=20).mean()
                # 날짜별 트렌드 (종가 > ema20) 판정
                market_trends[index_ticker] = (raw_idx['Close'] > raw_idx['ema20']).to_dict()
                print(f"  📈 지수 {index_ticker} 모멘텀 수집 완료")
        except Exception as e:
            print(f"  ⚠ 지수 {index_ticker} 수집 실패: {e}")

    best_all  = migrate_json_structure(load_json(BEST_FILE))
    history   = migrate_history(load_json(HISTORY_FILE))
    gene_pool = migrate_gene_pool(load_json(GENE_POOL_FILE))
    meta      = load_json(META_FILE)

    today_results    = {}
    improved_tickers = []
    df_latest        = {}  # 오늘의 신호용

    for ticker in TICKERS:
        print(f"\n[{ticker}] 데이터 로드 중...")
        try:
            raw = _fetch_market_data(data_service, ticker, '5y')

            if raw.empty or len(raw) < 250: print(f"  ⚠ 데이터 부족"); continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw[['Open','High','Low','Close','Volume']].dropna()

            # 데이터 무결성 검증 (0 이하 값, NaN 및 Inf 값 정비)
            raw = raw[(raw['Open'] > 0) & (raw['High'] > 0) & (raw['Low'] > 0) & (raw['Close'] > 0) & (raw['Volume'] >= 0)]
            raw = raw.replace([np.inf, -np.inf], np.nan).dropna()

            if len(raw) < 200:
                print(f"  ⚠ 유효 데이터 부족 ({len(raw)}행)")
                continue

            df  = add_indicators(raw)
            df_latest[ticker] = df
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
            print(f"  ✗ {e}"); continue

        if not optimize:
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

            if prev_data.get("validation_status") == "approved":
                prev_val_metrics = prev_data.get('val_metrics') or {}
                prev_metrics = prev_data.get('metrics') or {}
                prev_fitness = prev_val_metrics.get('fitness', prev_val_metrics.get('sharpe', prev_metrics.get('fitness', prev_metrics.get('sharpe', -999))))
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

            print(f"    {SIM_RUNS}회 시뮬레이션 (유전자풀 {len(pool)}개)...", end='', flush=True)

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
                    if pool and random.random() < GENETIC_RATIO:
                        if len(pool) >= 2 and random.random() < 0.35:
                            p1 = tournament_select(pool)
                            p2 = tournament_select(pool)
                            p  = crossover(p1['params'], p2['params'])
                        else:
                            parent = tournament_select(pool)
                            p = mutate(parent['params'], rate=mut_rate)
                    else:
                        # 메타 가중 샘플링
                        use_meta = random.random() < 0.7
                        p = sample_params(meta, use_meta=use_meta)

                    # 멀티 윈도우 Walk-Forward 검증 (특정 국면으로 제한)
                    tr_m, val_m = multi_window_validate(df, p, market_trends, target_regime=regime)
                    if tr_m is None:
                        no_improve += 1; continue
                    valid_n += 1

                    success = (tr_m['win_rate'] >= 48 and tr_m['profit_factor'] >= 1.2
                               and tr_m['total_return'] > 0)
                    update_meta(meta, p, success)
                    if not success:
                        no_improve += 1; continue

                    eval_fitness = val_m['fitness'] if val_m else tr_m['fitness']
                    if val_m and val_m.get('total_return', 0) <= 0:
                        no_improve += 1; continue

                    if eval_fitness > best_fitness:
                        # Kelly 포지션 사이징
                        p['pos_size'] = kelly_size(tr_m['win_rate'], tr_m['avg_win'],
                                                   tr_m['avg_loss'])
                        best_fitness = eval_fitness
                        no_improve  = 0
                        best_run = {
                            'ticker'     : ticker,
                            'regime'     : regime,
                            'params'     : p,
                            'metrics'    : tr_m,
                            'val_metrics': val_m,
                            'updated'    : today,
                            'run_time'   : run_time,
                            'kelly_pos'  : p['pos_size'],
                            'engine_version': 5,
                            'fitness_version': settings.research.fitness_version,
                            'random_seed': regime_seed,
                            'execution_model': settings.execution.model_dump(),
                        }
                    else:
                        no_improve += 1
                except Exception as sim_err:
                    no_improve += 1
                    if run_i < 3:  # 처음 3회만 에러 로깅 (반복 에러 방지)
                        print(f"\n    ⚠ 시뮬레이션 {run_i+1}회 오류: {type(sim_err).__name__}: {sim_err}")
                    continue

            print(
                f" 완료 (유효 {valid_n}회, 평가 {evaluated_runs}회"
                f"{', 조기종료' if early_stopped else ''})"
            )

            try:
                if best_run:
                    best_run['evaluated_runs'] = evaluated_runs
                    best_run['early_stopped'] = early_stopped
                    if run_context:
                        trade_log, _, equity_history = backtest(
                            df,
                            best_run['params'],
                            market_trends,
                            target_regime=regime,
                            initial_skip=0,
                        )
                        trade_path = (
                            run_context.run_dir
                            / "trades"
                            / f"{ticker}_{regime}.json"
                        )
                        trade_path.parent.mkdir(parents=True, exist_ok=True)
                        save_json(trade_log, str(trade_path))
                        run_context.record_artifact(trade_path)
                        equity_path = (
                            run_context.run_dir
                            / "equity"
                            / f"{ticker}_{regime}.json"
                        )
                        equity_path.parent.mkdir(parents=True, exist_ok=True)
                        save_json(
                            equity_curve_records(trade_log, equity_history),
                            str(equity_path),
                        )
                        run_context.record_artifact(equity_path)
                        best_run['trade_log_file'] = str(
                            trade_path.relative_to(run_context.run_dir)
                        )
                        best_run['equity_curve_file'] = str(
                            equity_path.relative_to(run_context.run_dir)
                        )
                        best_run['trade_log_count'] = len(trade_log)
                    best_run = numpy_to_python(best_run)
                    m  = best_run['metrics']
                    vm = best_run.get('val_metrics') or {}
                    p  = best_run['params']
                    validation = assess_validation(m, vm)
                    best_run['validation'] = validation
                    best_run['validation_status'] = (
                        'approved' if validation['approved'] else 'rejected'
                    )
                    if not validation['approved']:
                        print(
                            f"    ⚠ [{regime.upper()}] OOS 재검증 거부: "
                            f"{', '.join(validation['reasons'])}"
                        )
                        today_results.setdefault(ticker, {})[regime] = best_run
                        continue
                    print(f"    ✅ [{regime.upper()}] 전략 개선!")
                    print(f"       [학습] 수익 {m['total_return']}% | Sharpe {m['sharpe']} | Sortino {m.get('sortino','?')}")
                    print(f"       [검증] 수익 {vm.get('total_return','?')}% | Sharpe {vm.get('sharpe','?')} ({vm.get('windows','?')}구간)")
                    print(f"       ADX필터 {'ON' if p.get('use_adx_filter') else 'OFF'}(임계치:{p.get('adx_threshold')}) | Kelly {float(p['pos_size'])*100:.0f}%")

                    best_all[ticker][regime] = best_run
                    today_results.setdefault(ticker, {})[regime] = best_run
                    if ticker not in improved_tickers:
                        improved_tickers.append(ticker)

                    pool.append({'params': p, 'sharpe': best_fitness, 'fitness': best_fitness})
                    pool.sort(key=lambda x: x.get('fitness', x.get('sharpe', -999)), reverse=True)
                    gene_pool[ticker][regime] = pool[:TOP_K]

                    if regime not in history[ticker]: history[ticker][regime] = []
                    history[ticker][regime].append({'date': today, 'metrics': m,
                                            'val_metrics': vm, 'params': p})
                else:
                    prev = best_all.get(ticker, {}).get(regime, {})
                    pm   = prev.get('val_metrics') or prev.get('metrics', {})
                    print(f"    → [{regime.upper()}] 기존 유지 (Sharpe {pm.get('sharpe','?')} | 수익 {pm.get('total_return','?')}%)")
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
        )
        save_json(signals, SIGNAL_FILE)
    except Exception as e:
        signals = {}
        print(f"  ⚠ 신호 생성 오류: {e}")

    # 저장
    save_json(best_all,  BEST_FILE)
    save_json(history,   HISTORY_FILE)
    save_json(gene_pool, GENE_POOL_FILE)
    save_json(meta,      META_FILE)
    log = (
        str(run_context.run_dir / "result.json")
        if run_context
        else os.path.join(LOG_DIR, f'sim_{today}_{now.strftime("%H%M")}.json')
    )
    save_json({'run_time': run_time, 'improved': improved_tickers,
               'results': today_results, 'signals': signals}, log)
    if run_context:
        save_json(
            {
                ticker: {
                    regime: result.get("validation", {})
                    for regime, result in regimes.items()
                }
                for ticker, regimes in today_results.items()
            },
            str(run_context.run_dir / "validation_report.json"),
        )

    # 최종 리포트
    print(f"\n{'='*68}")
    print(f"  📊 최적 전략 현황 (국면별)")
    print(f"{'='*68}")
    kakao_lines = []
    for t in TICKERS:
        print(f"\n  [{t}]")
        sig_data = signals.get(t, {})
        sig = sig_data.get('signal', '?')
        today_reg = sig_data.get('regime', '?')
        print(f"   오늘의 국면: {today_reg.upper()} | 신호: {sig}")

        for regime in ["bull", "bear", "sideways"]:
            data = best_all.get(t, {}).get(regime)
            if not data or not data.get('params'): continue
            m   = data.get('val_metrics') or data.get('metrics', {})
            p   = data['params']
            tag = '[검증]' if data.get('val_metrics') else '[학습]'
            star = "⭐" if regime == today_reg else "  "
            print(f"   {star} [{regime.upper()}] {tag} | 수익 {m.get('total_return','?')}% | Sharpe {m.get('sharpe','?')} | Sortino {m.get('sortino','?')}")
            print(f"       손절 {'ATR×' + str(p.get('atr_mult_stop')) if p.get('use_atr_stop') else str(float(p.get('stop_pct',0))*100) + '%'}")
            print(f"       목표 +{float(p.get('target_pct',0))*100:.1f}% | ADX필터 {'ON' if p.get('use_adx_filter') else 'OFF'} | Kelly {float(p.get('pos_size',0.2))*100:.0f}%")

        # 오늘 활성 국면 정보로 카카오 전송용 요약 작성
        active_data = best_all.get(t, {}).get(today_reg, {})
        if active_data:
            m = active_data.get('val_metrics') or active_data.get('metrics', {})
            kakao_lines.append(f"{t}({today_reg.upper()}): 승률{m.get('win_rate','?')}% 수익{m.get('total_return','?')}% {sig}")
        else:
            kakao_lines.append(f"{t}: 설정없음 {sig}")

    print(f"\n{'='*68}")
    print(f"  🎯 오늘의 진입 신호")
    print(f"{'='*68}")
    for t, sig_data in signals.items():
        print(f"  [{t}] {sig_data.get('signal','?')} (국면: {sig_data.get('regime','?').upper()}) | 현재가: ${sig_data.get('price','?')}")
        for cond_name, cond_val in sig_data.get('conditions', {}).items():
            print(f"       {cond_name}: {cond_val}")

    print(f"\n  로그: {log}")
    print(f"{'='*68}\n")

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

if __name__ == '__main__':
    run()
