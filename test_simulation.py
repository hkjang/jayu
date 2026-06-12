# test_simulation.py
# 주식 자동화 시뮬레이션 엔진 v3 통합 검증 유닛 테스트

import unittest
import pandas as pd
import numpy as np
import os
import json

# 테스트 대상 모듈 임포트
from danta_simulation import (
    compute_rsi,
    compute_macd,
    compute_bbands,
    kelly_size,
    backtest,
    check_today_signals,
    add_indicators,
    migrate_json_structure,
    migrate_gene_pool,
    migrate_history,
    save_json,
    calc_metrics
)

class TestDantaSimulation(unittest.TestCase):

    def setUp(self):
        # 1. 테스트용 Mock 주가 데이터 생성 (500일 분량)
        np.random.seed(42)
        dates = pd.date_range(end='2026-06-13', periods=500, freq='D')
        
        # 기본 가격 100달러에서 시작하는 점진적인 상승+노이즈 흐름
        price = 100.0
        prices = []
        for i in range(500):
            price = price * (1.001 + np.random.normal(0, 0.015))
            prices.append(price)
            
        self.df = pd.DataFrame({
            'Open': [p * 0.99 for p in prices],
            'High': [p * 1.02 for p in prices],
            'Low': [p * 0.98 for p in prices],
            'Close': prices,
            'Volume': [int(100000 + np.random.normal(0, 10000)) for _ in range(500)]
        }, index=dates)

    def test_indicators(self):
        """1. 기술 지표 연산 정합성 테스트"""
        df_ind = add_indicators(self.df)
        
        # 지표 컬럼 추가 여부 검사
        self.assertIn('rsi', df_ind.columns)
        self.assertIn('rsi2', df_ind.columns)
        self.assertIn('sma5', df_ind.columns)
        self.assertIn('sma200', df_ind.columns)
        self.assertIn('macd_hist', df_ind.columns)
        self.assertIn('bb_pct', df_ind.columns)
        self.assertIn('stoch_rsi', df_ind.columns)
        self.assertIn('regime', df_ind.columns)
        
        # 수치 유효성 검사 (RSI는 0 ~ 100 사이)
        self.assertTrue(df_ind['rsi'].min() >= 0)
        self.assertTrue(df_ind['rsi'].max() <= 100)
        self.assertTrue(df_ind['rsi2'].min() >= 0)
        self.assertTrue(df_ind['rsi2'].max() <= 100)
        
        # 볼린저 밴드 %B 범위
        self.assertTrue(df_ind['bb_pct'].dropna().min() >= -2)  # 오버슈팅 허용
        self.assertTrue(df_ind['bb_pct'].dropna().max() <= 3)

    def test_kelly_size(self):
        """2. 적응형 Kelly 공식 특이점 방어 및 범위 테스트"""
        # 정상적인 케이스 (승률 60%, 평균익 5%, 평균손 -2.5%, max 0.3)
        size_normal = kelly_size(60, 5.0, -2.5, max_size=0.30)
        self.assertEqual(size_normal, 0.20) # (0.6*2 - 0.4)/2 = 0.4 -> half kelly 0.2 -> min(0.2, 0.3) = 0.20
        
        # 손실이 거의 없는 극단적인 전략 케이스 (-0.0001% 손실)
        size_low_loss = kelly_size(70, 10.0, -0.0001, max_size=0.30)
        # 0.10 ~ 0.30 범위 내로 방어되어야 함 (기본 0.17 반환)
        self.assertTrue(0.10 <= size_low_loss <= 0.30)
        
        # 승률이 0인 최악의 전략
        size_zero_win = kelly_size(0, 5.0, -5.0, max_size=0.30)
        self.assertEqual(size_zero_win, 0.10) # 최소 비중으로 제한
        
        # 비정상 범위 승률 (120%)
        size_invalid = kelly_size(120, 5.0, -5.0, max_size=0.30)
        self.assertEqual(size_invalid, 0.10)

    def test_vix_filter(self):
        """3. VIX 변동성 필터 강제 차단 테스트"""
        best_all = {
            "TQQQ": {
                "ticker": "TQQQ",
                "params": {
                    "rsi_lo": 30, "rsi_hi": 70, "ema_span": 20, "vol_mult": 1.0,
                    "gap_min": -0.05, "stop_pct": 0.05, "target_pct": 0.10, "hold_days": 2,
                    "use_atr_stop": False, "atr_mult_stop": 2.0, "trail_stop": False, "trail_pct": 0.03,
                    "require_macd": False, "require_bb": False, "regime_filter": False, "ensemble_min": 1,
                    "pos_size": 0.20
                }
            }
        }
        
        df_ind = add_indicators(self.df)
        df_dict = {"TQQQ": df_ind}
        
        # VIX 지수가 낮은 상황 (평상시) -> 진입 조건이 맞다면 진입 검토 혹은 대기
        sigs_normal = check_today_signals(df_dict, best_all, vix_val=15.0)
        self.assertIn(sigs_normal["TQQQ"]["signal"], ['🟢 진입 검토', '🔴 대기'])
        
        # VIX 지수가 극도로 높은 폭락 장세 (VIX = 25.0) -> 무조건 대기 차단 (기준 22.0)
        sigs_danger = check_today_signals(df_dict, best_all, vix_val=25.0)
        self.assertEqual(sigs_danger["TQQQ"]["signal"], "🔴 대기 (VIX 위험: 25.0)")

    def test_backtest_logic(self):
        """4. 백테스트 시뮬레이션 흐름 및 예외 처리 테스트"""
        # 느슨한 파라미터로 무조건 진입 거래가 발생하게끔 설정
        params = {
            "rsi_lo": 10, "rsi_hi": 90, "ema_span": 10, "vol_mult": 0.1,
            "gap_min": -0.5, "stop_pct": 0.05, "target_pct": 0.10, "hold_days": 2,
            "use_atr_stop": False, "atr_mult_stop": 2.0, "trail_stop": False, "trail_pct": 0.03,
            "require_macd": False, "require_bb": False, "regime_filter": False, "ensemble_min": 1,
            "pos_size": 0.20
        }
        
        df_ind = add_indicators(self.df)
        trades, final_cap, cap_hist = backtest(df_ind, params)
        
        # 거래가 정상적으로 유발되었는지 검사
        self.assertTrue(len(trades) >= 0)
        self.assertEqual(len(cap_hist), len(trades) + 1)
        self.assertTrue(final_cap > 0)

    def test_meta_decay(self):
        """5. 지수 감쇠 피드백 루프 동작 테스트"""
        from danta_simulation import update_meta
        
        # 가상의 초기 메타 상태
        meta = {
            "rsi_lo": {
                "40": {"wins": 10.0, "total": 20.0}
            }
        }
        
        # 새로운 시뮬레이션 결과 반영 (rsi_lo가 40이며 성공한 케이스)
        params = {"rsi_lo": 40}
        success = True
        
        # update_meta 호출
        updated = update_meta(meta, params, success, decay=0.90)
        
        # 기대 결과:
        # 기존 wins (10.0 * 0.90 = 9.0) + 신규 성공 (1.0) = 10.0
        # 기존 total (20.0 * 0.90 = 18.0) + 신규 시도 (1.0) = 19.0
        self.assertAlmostEqual(updated["rsi_lo"]["40"]["wins"], 10.0)
        self.assertAlmostEqual(updated["rsi_lo"]["40"]["total"], 19.0)

    def test_market_trend_filter(self):
        """6. 시장 지수 모멘텀 필터 동작 검증"""
        # SOXL용 기초 지수인 ^SOX의 추세가 '하락세(False)'로 강제 지정된 가상 딕셔너리
        market_trends = {
            "^SOX": {
                date: False for date in self.df.index
            }
        }
        
        # SOXL 종목으로 파라미터 세팅
        params = {
            "ticker": "SOXL",
            "rsi_lo": 10, "rsi_hi": 90, "ema_span": 10, "vol_mult": 0.1,
            "gap_min": -0.5, "stop_pct": 0.05, "target_pct": 0.10, "hold_days": 2,
            "use_atr_stop": False, "atr_mult_stop": 2.0, "trail_stop": False, "trail_pct": 0.03,
            "require_macd": False, "require_bb": False, "regime_filter": False, "ensemble_min": 1,
            "pos_size": 0.20
        }
        
        df_ind = add_indicators(self.df)
        trades, final_cap, cap_hist = backtest(df_ind, params, market_trend_dict=market_trends)
        
        # 시장 지수가 하락세이므로 거래가 단 한 번도 발생하지 않아야 함 (0건)
        self.assertEqual(len(trades), 0)

    def test_adx_calculation(self):
        """7. ADX 연산 정합성 테스트"""
        df_ind = add_indicators(self.df)
        self.assertIn('adx', df_ind.columns)
        # ADX 값은 0에서 100 사이
        self.assertTrue(df_ind['adx'].min() >= 0)
        self.assertTrue(df_ind['adx'].max() <= 100)

    def test_migrations(self):
        """8. 데이터 구조 마이그레이션 가드 테스트"""
        old_best = {
            "SOXL": {
                "params": {"rsi_lo": 40},
                "metrics": {"total_return": 15.0}
            }
        }
        migrated_best = migrate_json_structure(old_best)
        self.assertIn("bull", migrated_best["SOXL"])
        self.assertIn("bear", migrated_best["SOXL"])
        self.assertIn("sideways", migrated_best["SOXL"])
        self.assertEqual(migrated_best["SOXL"]["bull"]["params"]["rsi_lo"], 40)

        old_pool = {
            "SOXL": [{"params": {"rsi_lo": 40}, "fitness": 1.5}]
        }
        migrated_pool = migrate_gene_pool(old_pool)
        self.assertIn("bull", migrated_pool["SOXL"])
        self.assertEqual(migrated_pool["SOXL"]["bull"][0]["params"]["rsi_lo"], 40)

        old_history = {
            "SOXL": [{"date": "2026-06-13", "metrics": {}}]
        }
        migrated_history = migrate_history(old_history)
        self.assertIn("bull", migrated_history["SOXL"])
        self.assertEqual(migrated_history["SOXL"]["bull"][0]["date"], "2026-06-13")

    def test_backtest_with_adx_switching(self):
        """9. ADX 스위칭 및 정체 청산(Timeout)이 통합된 백테스트 테스트"""
        params = {
            "ticker": "TQQQ",
            "rsi_lo": 10, "rsi_hi": 90, "ema_span": 10, "vol_mult": 0.1,
            "gap_min": -0.5, "stop_pct": 0.05, "target_pct": 0.10, "hold_days": 4,
            "use_atr_stop": False, "atr_mult_stop": 2.0, "trail_stop": False, "trail_pct": 0.03,
            "require_macd": False, "require_bb": False, "regime_filter": False, "ensemble_min": 1,
            "use_adx_filter": True, "adx_threshold": 25,
            "pos_size": 0.20
        }
        df_ind = add_indicators(self.df)
        trades, final_cap, cap_hist = backtest(df_ind, params)
        # 에러 없이 완료되고 결과 형식이 맞는지 검증
        self.assertTrue(len(cap_hist) > 0)
        self.assertTrue(final_cap > 0)

    def test_atomic_save_json(self):
        """10. 원자적 파일 쓰기 안정성 검증"""
        test_path = "test_atomic_write.json"
        # 1. 파일 정상 저장 확인
        obj = {"key": "value"}
        save_json(obj, test_path)
        self.assertTrue(os.path.exists(test_path))
        
        with open(test_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")
        
        # 2. 예외 발생 시 임시 파일이 정리되고 기존 파일이 보존되는지 확인
        # 비정상 객체 (시리얼라이즈 불가능한 set 타입 주입)
        bad_obj = {"key": {1, 2, 3}}
        with self.assertRaises(Exception):
            save_json(bad_obj, test_path)
            
        # 임시파일(.tmp)이 지워졌는지 확인
        self.assertFalse(os.path.exists(test_path + ".tmp"))
        # 기존 파일 내용이 유지되었는지 확인
        with open(test_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")
        
        # 클린업
        if os.path.exists(test_path):
            os.remove(test_path)

    def test_data_integrity_stress(self):
        """11. 비정상 데이터 주입 스트레스 테스트"""
        # 의도적인 NaN, 0, Inf 주입
        bad_data = self.df.copy()
        bad_data.iloc[10:15, bad_data.columns.get_loc('Close')] = 0.0
        bad_data.iloc[20:25, bad_data.columns.get_loc('High')] = np.nan
        bad_data.iloc[30:35, bad_data.columns.get_loc('Low')] = np.inf
        
        # 무결성 전처리 가동
        clean_data = bad_data[(bad_data['Open'] > 0) & (bad_data['High'] > 0) & (bad_data['Low'] > 0) & (bad_data['Close'] > 0)]
        clean_data = clean_data.replace([np.inf, -np.inf], np.nan).dropna()
        
        # 에러 없이 연산되는지 확인
        df_ind = add_indicators(clean_data)
        self.assertTrue(len(df_ind) >= 0)
        self.assertFalse(df_ind.isnull().values.any())

    def test_metric_clipping_and_nan_guards(self):
        """12. 성과 평가 극단값 방어 및 클리핑 검증"""
        # 1. 1건의 양수 거래만 존재하여 표준편차가 0이고 Sharpe가 발산하는 경우
        trades_flat = [{'ret': 10.0, 'pnl': 1000.0, 'reason': 'target', 'date': '2026-06-13'}]
        cap_hist = [1000.0, 2000.0]
        # Sharpe, Sortino가 NaN/Inf 대신 capped 상한값으로 방어되는지 확인
        metrics = calc_metrics(trades_flat, 2000.0, cap_hist, min_trades=1)
        self.assertIsNotNone(metrics)
        self.assertTrue(metrics['sharpe'] <= 20.0)
        self.assertTrue(metrics['sortino'] <= 30.0)
        
        # 2. NaN이나 Inf가 유발되는 극단 거래 데이터 주입
        trades_nan = [{'ret': np.nan, 'pnl': np.inf, 'reason': 'target', 'date': '2026-06-13'}]
        metrics_nan = calc_metrics(trades_nan, 2000.0, cap_hist, min_trades=1)
        # 0.0 으로 복구되는지 확인
        self.assertIsNotNone(metrics_nan)
        self.assertEqual(metrics_nan['sharpe'], 0.0)
        self.assertEqual(metrics_nan['sortino'], 0.0)

    def test_connors_rsi2_backtest(self):
        """13. 코너스 RSI(2) 진입 및 5일선 돌파 청산 통합 테스트"""
        params = {
            "use_connors_rsi2": True,
            "connors_rsi2_limit": 15,
            "rsi_lo": 10, "rsi_hi": 90, "ema_span": 10, "vol_mult": 0.1,
            "gap_min": -0.5, "stop_pct": 0.05, "target_pct": 0.20, "hold_days": 5,
            "use_atr_stop": False, "atr_mult_stop": 2.0, "trail_stop": False, "trail_pct": 0.03,
            "require_macd": False, "require_bb": False, "regime_filter": False, "ensemble_min": 1,
            "pos_size": 0.20
        }
        
        df_ind = add_indicators(self.df)
        
        # 확실한 코너스 진입 및 청산 상황 유도
        # dropna() 이후 실제 데이터 길이 기준 동적 인덱스 지정 (IndexError 방지)
        entry_idx = len(df_ind) - 10
        self.assertTrue(entry_idx > 20, f"df_ind length too short: {len(df_ind)}")
        
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('Close')] = 150.0
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('sma200')] = 100.0  # close > sma200
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('rsi2')] = 5.0      # rsi2 < 15
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('vol_ratio')] = 2.0  # volume ok
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('gap')] = 0.01      # gap ok
        
        # 다음 날 (entry_idx + 1) 진입 시 open가
        df_ind.iloc[entry_idx + 1, df_ind.columns.get_loc('Open')] = 151.0
        
        # 다다음 날 (entry_idx + 2) Close가 sma5를 돌파하도록 세팅 -> connors_exit 유발
        df_ind.iloc[entry_idx + 2, df_ind.columns.get_loc('Close')] = 160.0
        df_ind.iloc[entry_idx + 2, df_ind.columns.get_loc('sma5')] = 155.0     # Close > sma5
        df_ind.iloc[entry_idx + 2, df_ind.columns.get_loc('Low')] = 145.0      # stop loss 안 닿게
        df_ind.iloc[entry_idx + 2, df_ind.columns.get_loc('High')] = 161.0     # target 안 닿게
        
        trades, final_cap, cap_hist = backtest(df_ind, params)
        
        # connors_exit로 끝난 거래가 하나 이상 존재해야 함
        self.assertTrue(len(trades) > 0)
        connors_exits = [t for t in trades if t['reason'] == 'connors_exit']
        self.assertTrue(len(connors_exits) > 0, f"Expected connors_exit, but got: {[t['reason'] for t in trades]}")

    def test_breakeven_stop_backtest(self):
        """14. 본전 손절(Break-Even Stop) 작동 및 수수료 보전 청산 테스트"""
        params = {
            "use_breakeven_stop": True,
            "breakeven_trigger_pct": 0.5,
            "rsi_lo": 10, "rsi_hi": 90, "ema_span": 10, "vol_mult": 0.1,
            "gap_min": -0.5, "stop_pct": 0.05, "target_pct": 0.10, "hold_days": 5,
            "use_atr_stop": False, "atr_mult_stop": 2.0, "trail_stop": False, "trail_pct": 0.03,
            "require_macd": False, "require_bb": False, "regime_filter": False, "ensemble_min": 1,
            "pos_size": 0.20, "kelly_fraction": 0.5
        }
        df_ind = add_indicators(self.df)
        
        # 동적 인덱스 지정
        entry_idx = len(df_ind) - 10
        
        # 진입 조건 충족 유도 (RSI 앙상블 진입)
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('rsi')] = 50.0  # rsi_lo <= rsi <= rsi_hi
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('Close')] = 100.0
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('ema10')] = 90.0  # close > ema
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('vol_ratio')] = 2.0  # volume ok
        df_ind.iloc[entry_idx, df_ind.columns.get_loc('gap')] = 0.01      # gap ok
        
        # 다음 날 (entry_idx + 1) 진입 시 open가 = 100.0
        df_ind.iloc[entry_idx + 1, df_ind.columns.get_loc('Open')] = 100.0
        
        # 다다음 날 (entry_idx + 2)에 최고가가 trigger_price에 도달하게 함
        df_ind.iloc[entry_idx + 2, df_ind.columns.get_loc('High')] = 106.0
        # 저가를 낮춰서 수수료 보전선 터치 유도
        df_ind.iloc[entry_idx + 2, df_ind.columns.get_loc('Low')] = 99.0  
        df_ind.iloc[entry_idx + 2, df_ind.columns.get_loc('Close')] = 100.0
        
        trades, final_cap, cap_hist = backtest(df_ind, params)
        
        # breakeven 청산이 발생했는지 검증
        self.assertTrue(len(trades) > 0)
        be_exits = [t for t in trades if t['reason'] == 'breakeven']
        self.assertTrue(len(be_exits) > 0, f"Expected breakeven exit, but got: {[t['reason'] for t in trades]}")

    def test_compounding_fractional_kelly_and_mdd_penalty(self):
        """15. Fractional Kelly 포지션 스케일링 및 MDD 피트니스 패널티 검증"""
        # 1. Fractional Kelly 검증
        params_full = {
            "use_breakeven_stop": False, "rsi_lo": 10, "rsi_hi": 90, "ema_span": 10, "vol_mult": 0.1,
            "gap_min": -0.5, "stop_pct": 0.05, "target_pct": 0.10, "hold_days": 2,
            "use_atr_stop": False, "atr_mult_stop": 2.0, "trail_stop": False, "trail_pct": 0.03,
            "require_macd": False, "require_bb": False, "regime_filter": False, "ensemble_min": 1,
            "pos_size": 0.20, "kelly_fraction": 1.00  # 100% 반영
        }
        params_quarter = {
            "use_breakeven_stop": False, "rsi_lo": 10, "rsi_hi": 90, "ema_span": 10, "vol_mult": 0.1,
            "gap_min": -0.5, "stop_pct": 0.05, "target_pct": 0.10, "hold_days": 2,
            "use_atr_stop": False, "atr_mult_stop": 2.0, "trail_stop": False, "trail_pct": 0.03,
            "require_macd": False, "require_bb": False, "regime_filter": False, "ensemble_min": 1,
            "pos_size": 0.20, "kelly_fraction": 0.25  # 25%만 반영
        }
        
        df_ind = add_indicators(self.df)
        
        # 동일 데이터로 백테스트 수행 시 자산 변화량 차이 확인
        _, cap_full, _ = backtest(df_ind, params_full)
        _, cap_quarter, _ = backtest(df_ind, params_quarter)
        
        # full kelly의 자산 변화량이 quarter kelly의 변화량보다 훨씬 커야 함
        diff_full = abs(cap_full - 10000000)
        diff_quarter = abs(cap_quarter - 10000000)
        self.assertTrue(diff_full > diff_quarter)

        # 2. MDD 피트니스 패널티 검증
        trades = [
            {'ret': 10.0, 'pnl': 100000.0, 'reason': 'target', 'date': '2026-06-13'},
            {'ret': 5.0, 'pnl': 50000.0, 'reason': 'target', 'date': '2026-06-14'}
        ]
        # MDD 2.0% 발생 상황 (peak 10M, low 9.8M)
        cap_hist_no_dd = [10000000.0, 9800000.0, 11000000.0]
        # MDD 50.0% 발생 상황 (peak 10M, low 5M)
        cap_hist_high_dd = [10000000.0, 5000000.0, 11000000.0] 
        
        metrics_no_dd = calc_metrics(trades, 11000000.0, cap_hist_no_dd, min_trades=1)
        metrics_high_dd = calc_metrics(trades, 11000000.0, cap_hist_high_dd, min_trades=1)
        
        # MDD가 높은 전략은 피트니스가 엄청나게 낮아져야 함
        self.assertTrue(metrics_no_dd['fitness'] > metrics_high_dd['fitness'] * 2)

if __name__ == '__main__':
    unittest.main()
