from __future__ import annotations

import math
from typing import Any


class BenchmarkComparison:
    """Compares the user portfolio's performance with major market indices."""

    def __init__(self) -> None:
        # Fallback index performance data (recent representative monthly metrics)
        self.default_indices = {
            "KOSPI": {"return_pct": 2.5, "volatility_pct": 14.2, "mdd_pct": 8.5},
            "KOSDAQ": {"return_pct": 1.8, "volatility_pct": 19.5, "mdd_pct": 12.4},
            "S&P500": {"return_pct": 8.4, "volatility_pct": 12.1, "mdd_pct": 6.2},
            "Nasdaq": {"return_pct": 12.6, "volatility_pct": 16.5, "mdd_pct": 9.8},
            "QQQ": {"return_pct": 12.4, "volatility_pct": 16.3, "mdd_pct": 9.6},
            "SCHD": {"return_pct": 5.2, "volatility_pct": 10.5, "mdd_pct": 5.1},
        }

    def compare_portfolio(
        self,
        portfolio_return_pct: float,
        portfolio_volatility_pct: float,
        portfolio_mdd_pct: float,
        risk_free_rate_pct: float = 2.0,
    ) -> dict[str, Any]:
        """Compare the portfolio return against major indices and compute differentials."""
        comparisons = {}
        
        portfolio_sharpe = (
            (portfolio_return_pct - risk_free_rate_pct) / portfolio_volatility_pct
            if portfolio_volatility_pct > 0
            else 0.0
        )

        for index_name, metrics in self.default_indices.items():
            idx_ret = metrics["return_pct"]
            idx_vol = metrics["volatility_pct"]
            idx_mdd = metrics["mdd_pct"]

            idx_sharpe = (
                (idx_ret - risk_free_rate_pct) / idx_vol
                if idx_vol > 0
                else 0.0
            )

            alpha = portfolio_return_pct - idx_ret
            vol_diff = portfolio_volatility_pct - idx_vol
            mdd_diff = portfolio_mdd_pct - idx_mdd
            sharpe_diff = portfolio_sharpe - idx_sharpe

            # Generate natural Korean explanation
            explanation = ""
            if alpha > 0:
                explanation += f"내 포트폴리오가 {index_name} 대비 **+{alpha:.2f}%p의 초과수익(Alpha)**을 창출하며 시장을 이겼습니다. "
            else:
                explanation += f"내 포트폴리오가 {index_name} 대비 **{alpha:.2f}%p 하회**하였습니다. "

            if mdd_diff < 0:
                explanation += f"또한, 최대 낙폭(MDD) 측면에서 {index_name}보다 **{abs(mdd_diff):.2f}%p 더 안전하게 방어**했습니다."
            else:
                explanation += f"다만, {index_name} 대비 최대 낙폭(MDD)이 **{mdd_diff:.2f}%p 높아 변동성 노출이 큽니다.**"

            comparisons[index_name] = {
                "benchmark_return_pct": idx_ret,
                "benchmark_volatility_pct": idx_vol,
                "benchmark_mdd_pct": idx_mdd,
                "benchmark_sharpe": round(idx_sharpe, 2),
                "alpha_pct": round(alpha, 2),
                "volatility_diff_pct": round(vol_diff, 2),
                "mdd_diff_pct": round(mdd_diff, 2),
                "sharpe_diff": round(sharpe_diff, 2),
                "explanation_korean": explanation,
            }

        return {
            "portfolio": {
                "return_pct": portfolio_return_pct,
                "volatility_pct": portfolio_volatility_pct,
                "mdd_pct": portfolio_mdd_pct,
                "sharpe": round(portfolio_sharpe, 2),
            },
            "comparisons": comparisons
        }
