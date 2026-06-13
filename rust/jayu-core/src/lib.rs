#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StrategyMode {
    Ensemble,
    ConnorsRsi2,
    WilliamsBreakout,
    VolumeBreakout,
}

#[derive(Clone, Debug, PartialEq)]
pub struct StrategyParams {
    pub mode: StrategyMode,
    pub stop_loss_pct: f64,
    pub take_profit_pct: f64,
    pub position_pct: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Trade {
    pub entry_index: usize,
    pub exit_index: usize,
    pub entry_price: f64,
    pub exit_price: f64,
    pub return_pct: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Metrics {
    pub trade_count: usize,
    pub total_return_pct: f64,
    pub win_rate: f64,
}

pub trait FillModel {
    fn should_exit(&self, entry_price: f64, current_price: f64, params: &StrategyParams) -> bool;
}

pub trait SlippageModel {
    fn apply_entry(&self, price: f64) -> f64;
    fn apply_exit(&self, price: f64) -> f64;
}

pub trait RiskModel {
    fn approved_position_pct(&self, requested: f64) -> f64;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ThresholdFillModel;

impl FillModel for ThresholdFillModel {
    fn should_exit(&self, entry_price: f64, current_price: f64, params: &StrategyParams) -> bool {
        let change = current_price / entry_price - 1.0;
        change <= -params.stop_loss_pct || change >= params.take_profit_pct
    }
}

#[derive(Clone, Copy, Debug)]
pub struct FixedSlippageModel {
    pub rate: f64,
}

impl SlippageModel for FixedSlippageModel {
    fn apply_entry(&self, price: f64) -> f64 {
        price * (1.0 + self.rate)
    }

    fn apply_exit(&self, price: f64) -> f64 {
        price * (1.0 - self.rate)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct CappedRiskModel {
    pub max_position_pct: f64,
}

impl RiskModel for CappedRiskModel {
    fn approved_position_pct(&self, requested: f64) -> f64 {
        requested.min(self.max_position_pct).max(0.0)
    }
}

pub fn backtest_close_path<F, S, R>(
    closes: &[f64],
    params: &StrategyParams,
    fill_model: &F,
    slippage_model: &S,
    risk_model: &R,
) -> (Vec<Trade>, Metrics)
where
    F: FillModel,
    S: SlippageModel,
    R: RiskModel,
{
    if closes.len() < 2 {
        return (Vec::new(), empty_metrics());
    }
    let approved_position = risk_model.approved_position_pct(params.position_pct);
    if approved_position <= 0.0 {
        return (Vec::new(), empty_metrics());
    }
    let entry_price = slippage_model.apply_entry(closes[0]);
    let mut trades = Vec::new();
    for (index, price) in closes.iter().enumerate().skip(1) {
        if fill_model.should_exit(entry_price, *price, params) || index == closes.len() - 1 {
            let exit_price = slippage_model.apply_exit(*price);
            let return_pct = (exit_price / entry_price - 1.0) * approved_position;
            trades.push(Trade {
                entry_index: 0,
                exit_index: index,
                entry_price,
                exit_price,
                return_pct,
            });
            break;
        }
    }
    let metrics = metrics_from_trades(&trades);
    (trades, metrics)
}

pub fn metrics_from_trades(trades: &[Trade]) -> Metrics {
    if trades.is_empty() {
        return empty_metrics();
    }
    let total_return_pct = trades.iter().map(|trade| trade.return_pct).sum();
    let winners = trades.iter().filter(|trade| trade.return_pct > 0.0).count();
    Metrics {
        trade_count: trades.len(),
        total_return_pct,
        win_rate: winners as f64 / trades.len() as f64,
    }
}

fn empty_metrics() -> Metrics {
    Metrics {
        trade_count: 0,
        total_return_pct: 0.0,
        win_rate: 0.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn close_path_exits_at_take_profit() {
        let params = StrategyParams {
            mode: StrategyMode::Ensemble,
            stop_loss_pct: 0.05,
            take_profit_pct: 0.08,
            position_pct: 1.0,
        };
        let (trades, metrics) = backtest_close_path(
            &[100.0, 110.0, 104.0, 112.0],
            &params,
            &ThresholdFillModel,
            &FixedSlippageModel { rate: 0.0 },
            &CappedRiskModel {
                max_position_pct: 1.0,
            },
        );

        assert_eq!(trades.len(), 1);
        assert_eq!(trades[0].exit_index, 1);
        assert!((metrics.total_return_pct - 0.10).abs() < 0.000_001);
        assert_eq!(metrics.win_rate, 1.0);
    }
}
