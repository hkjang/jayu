use jayu_core::{
    backtest_close_path, CappedRiskModel, FixedSlippageModel, StrategyMode, StrategyParams,
    ThresholdFillModel,
};

fn fixture_number(fixture: &str, key: &str) -> f64 {
    let marker = format!("\"{}\":", key);
    let start = fixture
        .find(&marker)
        .unwrap_or_else(|| panic!("missing key {key}"))
        + marker.len();
    let tail = fixture[start..].trim_start();
    let end = tail
        .find(|ch: char| !(ch.is_ascii_digit() || ch == '.' || ch == '-'))
        .unwrap_or(tail.len());
    tail[..end].parse::<f64>().expect("numeric fixture value")
}

#[test]
fn rust_close_path_matches_python_golden_fixture() {
    let fixture = include_str!("../../../tests/fixtures/rust_golden.json");
    let params = StrategyParams {
        mode: StrategyMode::Ensemble,
        stop_loss_pct: 0.05,
        take_profit_pct: 0.08,
        position_pct: 1.0,
    };
    let (_, metrics) = backtest_close_path(
        &[100.0, 110.0, 104.0, 112.0],
        &params,
        &ThresholdFillModel,
        &FixedSlippageModel { rate: 0.0 },
        &CappedRiskModel {
            max_position_pct: 1.0,
        },
    );

    assert_eq!(metrics.trade_count as f64, fixture_number(fixture, "trade_count"));
    assert!(
        (metrics.total_return_pct - fixture_number(fixture, "total_return_pct")).abs()
            < 0.000_001
    );
    assert!((metrics.win_rate - fixture_number(fixture, "win_rate")).abs() < 0.000_001);
}
