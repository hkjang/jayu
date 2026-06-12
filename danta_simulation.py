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
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import yfinance as yf
import pandas as pd
import numpy as np
import json, os, random, copy, time
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ── 설정 ──────────────────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
TICKERS         = ['SOXL', 'TQQQ', 'TSLA', 'IONQ', 'NVDL', 'QBTS']
INITIAL_CAPITAL = 10_000_000
SIM_RUNS        = 500
TRANSACTION_FEE = 0.0015
SLIPPAGE        = 0.0005

config_path = os.path.join(BASE_DIR, 'config.json')
if os.path.exists(config_path):
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            BASE_DIR = cfg.get('BASE_DIR', BASE_DIR)
            TICKERS = cfg.get('TICKERS', TICKERS)
            INITIAL_CAPITAL = cfg.get('INITIAL_CAPITAL', INITIAL_CAPITAL)
            SIM_RUNS = cfg.get('SIM_RUNS', SIM_RUNS)
            TRANSACTION_FEE = cfg.get('TRANSACTION_FEE', TRANSACTION_FEE)
            SLIPPAGE = cfg.get('SLIPPAGE', SLIPPAGE)
    except Exception as e:
        print(f"설정 파일 config.json 로드 에러: {e}")

GENETIC_RATIO   = 0.65
TOP_K           = 15
TRAIN_MONTHS    = 18
VALID_MONTHS    = 6
MIN_TRADES      = 5
MAX_POS         = 0.30
LOG_DIR         = os.path.join(BASE_DIR, 'simulation_logs')
BEST_FILE       = os.path.join(BASE_DIR, 'best_strategy.json')
HISTORY_FILE    = os.path.join(BASE_DIR, 'strategy_history.json')
GENE_POOL_FILE  = os.path.join(BASE_DIR, 'gene_pool.json')
META_FILE       = os.path.join(BASE_DIR, 'meta_learning.json')
SIGNAL_FILE     = os.path.join(BASE_DIR, 'today_signals.json')
os.makedirs(LOG_DIR, exist_ok=True)

# ── 파라미터 공간 ───────────────────────────────────────────────
PARAM_SPACE = {
    'rsi_lo'       : [35, 40, 45, 50, 55],
    'rsi_hi'       : [60, 65, 70, 75, 80],
    'ema_span'     : [10, 20, 50],
    'vol_mult'     : [1.2, 1.5, 1.8, 2.0, 2.5, 3.0],
    'gap_min'      : [-0.01, -0.005, 0.0, 0.002, 0.005],
    'use_atr_stop' : [True, False],        # ATR 기반 vs 고정 손절
    'atr_mult_stop': [1.5, 2.0, 2.5, 3.0],
    'stop_pct'     : [0.02, 0.025, 0.03, 0.035, 0.04, 0.05],
    'target_pct'   : [0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15],
    'hold_days'    : [1, 2, 3, 5],
    'trail_stop'   : [True, False],        # 트레일링 스톱 사용 여부
    'trail_pct'    : [0.02, 0.03, 0.04],   # 최고가 대비 트레일링 비율
    'require_macd' : [True, False],        # MACD 상향 교차 필요
    'require_bb'   : [True, False],        # 볼린저 밴드 하단 근처 진입
    'regime_filter': [True, False],        # 시장 국면 필터
    'ensemble_min' : [1, 2, 3],            # 최소 충족 조건 수 (버그 수정: [2,3,4] -> [1,2,3])
    'use_adx_filter': [True, False],       # ADX 추세/횡보 필터
    'adx_threshold' : [20, 25, 30],        # ADX 추세 기준선
    'use_connors_rsi2': [True, False],     # 래리 코너스 RSI(2) 전략 사용 여부
    'connors_rsi2_limit': [5, 10, 15],     # 코너스 RSI(2) 진입 임계값
    'use_breakeven_stop': [True, False],    # 본전 손절 사용 여부
    'breakeven_trigger_pct': [0.3, 0.4, 0.5], # 본전 손절 발동 수익률 임계치
    'kelly_fraction': [0.25, 0.50, 1.00],   # Kelly 비중 조절 비율
    'use_williams_breakout': [True, False],  # 래리 윌리엄스 변동성 돌파 전략 사용 여부
    'williams_k_multiplier': [0.8, 1.0, 1.2], # 돌파 K-계수 보정 멀티플라이어
    'use_atr_target'       : [True, False],        # 익절에 ATR 기반 변동성 적용 여부
    'atr_mult_target'      : [1.5, 2.0, 2.5, 3.0, 4.0], # 익절 ATR 배수
    'min_dollar_volume'    : [5_000_000, 10_000_000, 20_000_000], # 최소 20일 평균 거래대금 기준 (미달러)
    'use_volatility_sizing': [True, False],        # ATR 변동성 비례 포지션 비중 조절
    'max_risk_per_trade_pct': [0.01, 0.015, 0.02],  # 거래당 계좌 대비 최대 허용 손실 비율
    'use_volume_breakout'  : [True, False],        # 거래량 스파이크 돌파 전략 사용 여부
    'volume_spike_mult'    : [1.8, 2.0, 2.5, 3.0], # 거래량 급증 기준 배수 (평균 대비)
    'volume_breakout_period': [5, 10, 15, 20],      # 가격 채널 돌파 기준일수 (Donchian)
}


# ── 기술 지표 ────────────────────────────────────────────────────
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

def compute_adx(df, period=14):
    h_l = df['High'] - df['Low']
    h_pc = (df['High'] - df['Close'].shift(1)).abs()
    l_pc = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
    
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
    df['atr']       = (df['High'] - df['Low']).rolling(14).mean()
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
    return df.dropna()

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
def backtest(df, p, market_trend_dict=None, target_regime=None):
    ema_col = f"ema{p['ema_span']}"
    capital = float(INITIAL_CAPITAL)
    trades, capitals = [], [capital]
    i = 220  # 충분한 워밍업 (EMA200 필요)

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

        use_connors = p.get('use_connors_rsi2', False)
        use_williams = p.get('use_williams_breakout', False)
        use_volume = p.get('use_volume_breakout', False)
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
        market_impact = 0.15 * (capital * actual_pos_size / dollar_vol_20)
        dynamic_slippage = max(SLIPPAGE, (atr / close) * 0.1) + market_impact
        dynamic_slippage = min(dynamic_slippage, 0.01) # 상한 1.0%
        
        entry = entry_raw * (1.0 + dynamic_slippage)

        # ── 손절/목표 결정 ────────────────────────────────────────
        stop_dist   = (atr * p['atr_mult_stop']) if p['use_atr_stop'] else (entry * p['stop_pct'])
        stop_price  = entry - stop_dist
        
        use_atr_tgt = p.get('use_atr_target', False)
        target_dist = (atr * p.get('atr_mult_target', 2.0)) if use_atr_tgt else (entry * p['target_pct'])
        target_price= entry + target_dist
        trail_floor = stop_price  # 트레일링 시작점

        exit_price, exit_reason = None, 'time'
        peak = entry
        worst_lo = entry
        breakeven_activated = False

        for j in range(1, p['hold_days'] + 2):
            idx = i + 1 + j
            if idx >= len(df): break
            fut = df.iloc[idx]
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

            # 청산 판정
            if lo <= effective_stop:
                exit_price = effective_stop
                exit_reason = 'breakeven' if breakeven_activated else 'stop'
                break
            if hi >= target_price:
                exit_price, exit_reason = target_price, 'target'; break
            
            # 래리 코너스 청산 조건: Close > sma5
            if p.get('use_connors_rsi2', False) and float(fut['Close']) > float(fut['sma5']):
                exit_price, exit_reason = float(fut['Close']), 'connors_exit'; break
                
            # 정체 청산 (Timeout Exit): 보유 기간 절반 이상 지났을 때 수익률이 미미하면 조기 탈출
            if j >= max(2, p['hold_days'] // 2):
                current_ret = ((float(fut['Close']) - entry) / entry)
                if abs(current_ret) < 0.005:  # ±0.5% 이내 횡보 시
                    exit_price, exit_reason = float(fut['Close']), 'timeout'; break
                    
            # 조기 청산: RSI 과매수 + MACD 하향교차
            if j >= 2:
                fut_rsi  = float(fut['rsi']) if not pd.isna(fut['rsi']) else 50
                fut_macd = float(fut['macd_hist']) if not pd.isna(fut['macd_hist']) else 0
                prev_macd= float(df.iloc[idx-1]['macd_hist']) if not pd.isna(df.iloc[idx-1]['macd_hist']) else 0
                if fut_rsi > 80 and fut_macd < prev_macd:
                    exit_price, exit_reason = float(fut['Close']), 'overbought'; break

        if exit_price is None:
            fidx = min(i + 1 + p['hold_days'], len(df)-1)
            exit_price = float(df.iloc[fidx]['Close'])

        exit_settled = exit_price * (1.0 - dynamic_slippage)
        ret = ((exit_settled - entry) / entry) - (TRANSACTION_FEE * 2)
        
        pnl = capital * actual_pos_size * ret
        capital += pnl
        capitals.append(capital)
        
        trade_mae_pct = ((worst_lo - entry) / entry) * 100
        trades.append({'ret': round(ret*100, 3), 'pnl': round(pnl, 0),
                       'reason': exit_reason, 'date': str(df.index[i].date()),
                       'mae': round(trade_mae_pct, 3)})
        i += p['hold_days'] + 1

    return trades, capital, capitals

# ── 성과 지표 v3 ─────────────────────────────────────────────────
def calc_metrics(trades, final_cap, cap_hist, min_trades=MIN_TRADES):
    if len(trades) < min_trades: return None
    rets  = np.nan_to_num(np.array([float(t['ret']) if t['ret'] is not None and not pd.isna(t['ret']) else 0.0 for t in trades]), nan=0.0, posinf=0.0, neginf=0.0)
    wins  = rets[rets > 0]
    loses = rets[rets <= 0]

    win_rate = len(wins) / len(rets) * 100 if len(rets) > 0 else 0.0
    avg_win  = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(loses)) if len(loses) > 0 else 0.0
    
    # MAE (Maximum Adverse Excursion) 계산
    maes = np.array([float(t['mae']) for t in trades if 'mae' in t])
    avg_mae = float(np.mean(maes)) if len(maes) > 0 else 0.0
    worst_mae = float(np.min(maes)) if len(maes) > 0 else 0.0

    # 수치형 극단값/NaN 방어 함수
    def clean_metric(val, max_val):
        if val is None or pd.isna(val) or np.isnan(val) or np.isinf(val):
            return 0.0
        return float(max(min(val, max_val), -max_val))

    pf       = clean_metric(wins.sum() / abs(loses.sum()) if loses.sum() != 0 else 9.99, 9.99)
    rr       = clean_metric(abs(avg_win / avg_loss) if avg_loss != 0 else 0.0, 9.99)

    arr      = rets / 100
    sharpe_raw = float(np.mean(arr) / np.std(arr) * np.sqrt(252)) if np.std(arr) > 0 else 0.0
    sharpe   = clean_metric(sharpe_raw, 20.0)
    
    # Sortino: 하방 표준편차만 사용
    neg_arr  = arr[arr < 0]
    sortino_raw = float(np.mean(arr) / np.std(neg_arr) * np.sqrt(252)) if len(neg_arr) > 0 and np.std(neg_arr) > 0 else 0.0
    sortino  = clean_metric(sortino_raw, 30.0)

    peak   = INITIAL_CAPITAL; max_dd = 0.0
    for c in cap_hist:
        if c > peak: peak = c
        dd = (peak - c) / peak * 100
        if dd > max_dd: max_dd = dd

    total_ret = (final_cap - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    # Calmar: 연수익률 / 최대낙폭
    calmar_raw = total_ret / max_dd if max_dd > 0 else 0.0
    calmar = clean_metric(calmar_raw, 50.0)

    # 피트니스 스코어 계산 (Sharpe * 0.5 + Sortino * 0.3 + Calmar * 0.2)
    f_sharpe = max(sharpe, 0.0)
    f_sortino = max(sortino, 0.0)
    f_calmar = max(calmar, 0.0)
    base_fitness = f_sharpe * 0.5 + f_sortino * 0.3 + f_calmar * 0.2
    
    # MDD 페널티 반영 (MDD가 0일 때는 패널티 1.0, 10% 이상일 때는 최소 0.1로 감소)
    mdd_penalty = max(0.1, 1.0 - (max_dd / 10.0))
    
    # MAE 페널티 반영 (Worst MAE가 -8% 미만으로 깊어지면 추가 페널티 부여하여 생존 지향)
    mae_penalty = max(0.1, 1.0 - (abs(worst_mae) - 8.0) / 10.0) if worst_mae < -8.0 else 1.0
    
    fitness = round(base_fitness * mdd_penalty * mae_penalty, 3)

    return {
        'trades'       : int(len(rets)),
        'win_rate'     : round(win_rate, 1),
        'avg_win'      : round(avg_win, 2),
        'avg_loss'     : round(avg_loss, 2),
        'profit_factor': round(min(pf, 9.99), 2),
        'rr_ratio'     : round(rr, 2),
        'sharpe'       : round(sharpe, 2),
        'sortino'      : round(sortino, 2),
        'calmar'       : calmar,
        'fitness'      : fitness,
        'max_drawdown' : round(max_dd, 1),
        'total_return' : round(total_ret, 1),
        'final_capital': round(final_cap, 0),
        'avg_mae'      : round(avg_mae, 2),
        'worst_mae'    : round(worst_mae, 2),
    }

# ── 멀티 윈도우 Walk-Forward 검증 ────────────────────────────────
def multi_window_validate(df, p, market_trend_dict=None, target_regime=None):
    """3개 검증 구간의 평균 성과 → 과최적화 방지 강화"""
    n = len(df)
    windows = []
    for offset in [0, 21, 42]:  # 0, 1, 2개월 오프셋
        valid_start = max(220, n - (VALID_MONTHS * 21) - offset)
        train_end   = max(220 + 60, valid_start - 21)
        if train_end < 280: continue

        df_train = df.iloc[:train_end]
        df_valid = df.iloc[valid_start:]
        if len(df_valid) < 20: continue

        tr_t, tr_cap, tr_ch = backtest(df_train, p, market_trend_dict, target_regime)
        tr_m = calc_metrics(tr_t, tr_cap, tr_ch, min_trades=2 if target_regime else MIN_TRADES)
        if tr_m is None: continue
        
        # 국면별 최적화 시에는 데이터양이 적으므로 조건 기준 완화
        min_wr = 44 if target_regime else 48
        min_pf = 1.0 if target_regime else 1.2
        if tr_m['win_rate'] < min_wr or tr_m['profit_factor'] < min_pf: continue

        vl_t, vl_cap, vl_ch = backtest(df_valid, p, market_trend_dict, target_regime)
        vl_m = calc_metrics(vl_t, vl_cap, vl_ch, min_trades=1 if target_regime else MIN_TRADES)
        windows.append((tr_m, vl_m))

    if not windows: return None, None
    # 검증셋에서 수익 기록한 윈도우만
    valid_windows = [(tr, vl) for tr, vl in windows if vl and vl['total_return'] > 0]
    if not valid_windows: return None, None

    # 가장 좋은 학습셋 기준 + 검증셋 평균 (피트니스 기반 정렬)
    best_tr = max(valid_windows, key=lambda x: x[0]['fitness'])[0]
    avg_fitness = float(np.mean([vl['fitness'] for _, vl in valid_windows]))
    avg_return = float(np.mean([vl['total_return'] for _, vl in valid_windows]))
    avg_win    = float(np.mean([vl['win_rate'] for _, vl in valid_windows]))

    avg_val = {'fitness': round(avg_fitness, 3),
               'total_return': round(avg_return, 1),
               'win_rate': round(avg_win, 1),
               'windows': len(valid_windows)}
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

def sample_params(meta=None, use_meta=True):
    """메타 가중 or 순수 랜덤 파라미터 생성"""
    m = meta if (use_meta and meta) else {}
    def s(key): return meta_sample(m, key, PARAM_SPACE[key]) if use_meta else random.choice(PARAM_SPACE[key])

    stop   = s('stop_pct')
    t_ok   = [t for t in PARAM_SPACE['target_pct'] if t >= stop * 1.5]
    target = random.choice(t_ok) if t_ok else stop * 2
    rsi_lo = s('rsi_lo')
    rsi_hi = random.choice([x for x in PARAM_SPACE['rsi_hi'] if x > rsi_lo + 5])
    return {
        'rsi_lo'       : rsi_lo,
        'rsi_hi'       : rsi_hi,
        'ema_span'     : s('ema_span'),
        'vol_mult'     : s('vol_mult'),
        'gap_min'      : s('gap_min'),
        'use_atr_stop' : s('use_atr_stop'),
        'atr_mult_stop': s('atr_mult_stop'),
        'stop_pct'     : stop,
        'target_pct'   : target,
        'hold_days'    : s('hold_days'),
        'trail_stop'   : s('trail_stop'),
        'trail_pct'    : s('trail_pct'),
        'require_macd' : s('require_macd'),
        'require_bb'   : s('require_bb'),
        'regime_filter': s('regime_filter'),
        'ensemble_min' : s('ensemble_min'),
        'use_adx_filter': s('use_adx_filter'),
        'adx_threshold' : s('adx_threshold'),
        'use_connors_rsi2': s('use_connors_rsi2'),
        'connors_rsi2_limit': s('connors_rsi2_limit'),
        'use_breakeven_stop': s('use_breakeven_stop'),
        'breakeven_trigger_pct': s('breakeven_trigger_pct'),
        'kelly_fraction': s('kelly_fraction'),
        'use_williams_breakout': s('use_williams_breakout'),
        'williams_k_multiplier': s('williams_k_multiplier'),
        'use_atr_target'       : s('use_atr_target'),
        'atr_mult_target'      : s('atr_mult_target'),
        'min_dollar_volume'    : s('min_dollar_volume'),
        'use_volatility_sizing': s('use_volatility_sizing'),
        'max_risk_per_trade_pct': s('max_risk_per_trade_pct'),
        'use_volume_breakout'  : s('use_volume_breakout'),
        'volume_spike_mult'    : s('volume_spike_mult'),
        'volume_breakout_period': s('volume_breakout_period'),
        'pos_size'     : 0.20,  # Kelly로 나중에 덮어씀
    }

# ── 유전 알고리즘 ────────────────────────────────────────────────
def tournament_select(pool, k=3):
    """토너먼트 선택: k개 후보 중 최고 선택"""
    candidates = random.sample(pool[:min(len(pool), TOP_K)], min(k, len(pool)))
    return max(candidates, key=lambda x: x.get('fitness', x.get('sharpe', -999)))

def mutate(params, rate=0.25):
    child = copy.deepcopy(params)
    for key, choices in PARAM_SPACE.items():
        if key in child and random.random() < rate:
            child[key] = random.choice(choices)
    child['pos_size'] = 0.20  # Kelly로 나중에 재계산
    if child.get('rsi_lo', 50) >= child.get('rsi_hi', 70):
        child['rsi_hi'] = child['rsi_lo'] + 15
    if child.get('target_pct', 0.1) < child.get('stop_pct', 0.03) * 1.5:
        child['target_pct'] = child['stop_pct'] * 2
    if child.get('use_atr_target') and child.get('use_atr_stop'):
        if child.get('atr_mult_target', 2.0) < child.get('atr_mult_stop', 2.0) * 1.2:
            child['atr_mult_target'] = child['atr_mult_stop'] * 1.5
    return child

def crossover(p1, p2):
    child = {}
    for key in PARAM_SPACE:
        child[key] = p1.get(key, random.choice(PARAM_SPACE[key])) if random.random() < 0.5 \
               else  p2.get(key, random.choice(PARAM_SPACE[key]))
    child['pos_size'] = 0.20
    if child.get('rsi_lo', 50) >= child.get('rsi_hi', 70):
        child['rsi_hi'] = child['rsi_lo'] + 15
    if child.get('target_pct', 0.1) < child.get('stop_pct', 0.03) * 1.5:
        child['target_pct'] = child['stop_pct'] * 2
    if child.get('use_atr_target') and child.get('use_atr_stop'):
        if child.get('atr_mult_target', 2.0) < child.get('atr_mult_stop', 2.0) * 1.2:
            child['atr_mult_target'] = child['atr_mult_stop'] * 1.5
    return child

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
        return copy.deepcopy(DEFAULT_PARAMS)
    merged = copy.deepcopy(DEFAULT_PARAMS)
    merged.update(params)
    return merged

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
def check_today_signals(df, best_all, vix_val=0.0, market_trends=None):
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
        
        # 폴백 처리 (오늘 국면 설정이 없으면 다른 국면이라도 사용)
        if not data or 'params' not in data:
            for r in ["bull", "bear", "sideways"]:
                if r in ticker_data and 'params' in ticker_data[r]:
                    data = ticker_data[r]
                    break
                    
        if not data or 'params' not in data:
            today_sigs[ticker] = {'signal': '설정없음'}
            continue
            
        p = data['params']

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
        
        use_connors = p.get('use_connors_rsi2', False)
        use_williams = p.get('use_williams_breakout', False)
        use_volume = p.get('use_volume_breakout', False)
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
            'conditions': conds_str,
            'price': round(float(row['Close']), 2),
            'regime': today_regime,
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
def run():
    now      = datetime.now()
    today    = now.strftime('%Y-%m-%d')
    run_time = now.strftime('%Y-%m-%d %H:%M')

    print(f"\n{'='*68}")
    print(f"  🔬 단타 시뮬레이션 v4  |  {run_time}")
    print(f"  종목: {TICKERS}")
    print(f"  {SIM_RUNS}회/종목/국면 | 유전({int(GENETIC_RATIO*100)}%)+메타가중 / 랜덤({int((1-GENETIC_RATIO)*100)}%)")
    print(f"  Walk-Forward: 멀티윈도우 3구간 | ADX 스위칭 필터 | 국면별 독립 파라미터")
    print(f"{'='*68}")

    # VIX 지수 사전 수집
    vix_val = 0.0
    try:
        vix_df = yf.download('^VIX', period='5d', auto_adjust=True, progress=False)
        if not vix_df.empty:
            vix_val = float(vix_df['Close'].dropna().iloc[-1])
            print(f"  📉 현재 VIX 지수: {vix_val:.2f}")
    except Exception as e:
        print(f"  ⚠ VIX 지수 조회 실패: {e}")

    # 시장/섹터 지수 사전 수집 (SOX, IXIC)
    market_trends = {}
    for index_ticker in ['^SOX', '^IXIC']:
        try:
            raw_idx = yf.download(index_ticker, period='2y', auto_adjust=True, progress=False)
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
            # 3회 재시도 루프 적용
            raw = pd.DataFrame()
            for attempt in range(3):
                try:
                    raw = yf.download(ticker, period='2y', auto_adjust=True, progress=False)
                    if not raw.empty and len(raw) >= 250:
                        break
                except Exception as ex:
                    print(f"    ({attempt+1}차 시도 실패): {ex}")
                time.sleep(1)

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
            print(f"  {len(df)}행 | 지표: RSI/EMA/MACD/BB/StochRSI/OBV/ADX/Regime")
        except Exception as e:
            print(f"  ✗ {e}"); continue

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
                
            prev_val_metrics = prev_data.get('val_metrics') or {}
            prev_metrics = prev_data.get('metrics') or {}
            prev_fitness = prev_val_metrics.get('fitness', prev_val_metrics.get('sharpe', prev_metrics.get('fitness', prev_metrics.get('sharpe', -999))))
            
            best_run = None
            best_fitness = prev_fitness
            valid_n = 0
            no_improve = 0  # 적응형 변이율용

            print(f"    {SIM_RUNS}회 시뮬레이션 (유전자풀 {len(pool)}개)...", end='', flush=True)

            for run_i in range(SIM_RUNS):
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
                        }
                    else:
                        no_improve += 1
                except Exception as sim_err:
                    no_improve += 1
                    if run_i < 3:  # 처음 3회만 에러 로깅 (반복 에러 방지)
                        print(f"\n    ⚠ 시뮬레이션 {run_i+1}회 오류: {type(sim_err).__name__}: {sim_err}")
                    continue

            print(f" 완료 (유효 {valid_n}회)")

            try:
                if best_run:
                    best_run = numpy_to_python(best_run)
                    m  = best_run['metrics']
                    vm = best_run.get('val_metrics') or {}
                    p  = best_run['params']
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
        signals = check_today_signals(df_latest, best_all, vix_val, market_trends)
        save_json(signals, SIGNAL_FILE)
    except Exception as e:
        signals = {}
        print(f"  ⚠ 신호 생성 오류: {e}")

    # 저장
    save_json(best_all,  BEST_FILE)
    save_json(history,   HISTORY_FILE)
    save_json(gene_pool, GENE_POOL_FILE)
    save_json(meta,      META_FILE)
    log = os.path.join(LOG_DIR, f'sim_{today}_{now.strftime("%H%M")}.json')
    save_json({'run_time': run_time, 'improved': improved_tickers,
               'results': today_results, 'signals': signals}, log)

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

    # 카카오톡 알림 자동 전송
    try:
        from stock_kakao import send_kakao
        msg_lines = [
            f"🔬 단타 시뮬레이션 v4 ({run_time})",
            f"VIX 지수: {vix_val:.2f}" if vix_val > 0 else "VIX 지수: 조회실패",
            f"개선 종목: {', '.join(improved_tickers) if improved_tickers else '없음'}",
            ""
        ]
        for line in kakao_lines:
            msg_lines.append(line)
        
        msg = "\n".join(msg_lines).strip()
        res = send_kakao(msg)
        print(f"  카카오톡 전송 결과: {res}")
    except Exception as e:
        print(f"  ⚠ 카카오톡 알림 전송 실패: {e}")

    return best_all, kakao_lines, improved_tickers, signals

if __name__ == '__main__':
    run()
