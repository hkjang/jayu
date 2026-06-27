from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


class DividendCashflowSimulator:
    """Estimates expected monthly/quarterly dividend cashflow and projects reinvestment scenarios."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        # Default dividend profiles for fallback matching
        self.default_dividend_profiles = {
            "SCHD": {"yield": 0.034, "months": [3, 6, 9, 12]},
            "O": {"yield": 0.055, "months": list(range(1, 13))},
            "JEPI": {"yield": 0.072, "months": list(range(1, 13))},
            "JEPQ": {"yield": 0.091, "months": list(range(1, 13))},
            "AAPL": {"yield": 0.005, "months": [2, 5, 8, 11]},
            "MSFT": {"yield": 0.007, "months": [3, 6, 9, 12]},
            "KO": {"yield": 0.031, "months": [4, 7, 10, 12]},
            "005930": {"yield": 0.021, "months": [4, 5, 8, 11]},  # Samsung Electronics (standard months)
        }

    def load_holdings_from_csv(self, csv_path: Path) -> list[dict[str, Any]]:
        if not csv_path.exists():
            return []
        holdings = []
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ticker = row.get("ticker", "").strip().upper()
                    qty = row.get("quantity", "0")
                    price = row.get("price", "0") or row.get("current_price", "0")
                    if ticker and qty:
                        holdings.append({
                            "ticker": ticker,
                            "quantity": float(qty),
                            "price": float(price) if price else 0.0
                        })
        except Exception:
            pass
        return holdings

    def simulate_cashflow(
        self,
        holdings: list[dict[str, Any]] | None = None,
        fx_rate: float = 1350.0
    ) -> dict[str, Any]:
        """Project expected monthly dividend payouts in KRW."""
        if holdings is None:
            csv_path = self.project_root / "toss_portfolio.csv"
            holdings = self.load_holdings_from_csv(csv_path)

        monthly_flows = [0.0] * 12
        portfolio_value_krw = 0.0
        dividend_holdings = []

        for h in holdings:
            ticker = h["ticker"]
            qty = h["quantity"]
            price = h["price"]
            
            # Estimate value
            # Standard US tickers vs KR tickers
            is_us = not ticker.isdigit() and not (ticker.endswith(".KS") or ticker.endswith(".KQ"))
            val_local = qty * price
            val_krw = val_local * fx_rate if is_us else val_local
            portfolio_value_krw += val_krw

            # Resolve dividend profile
            profile = self.default_dividend_profiles.get(ticker)
            if not profile:
                # Standard default fallback for generic tickers: 1.5% yield paid quarterly
                profile = {"yield": 0.015, "months": [3, 6, 9, 12]}

            annual_payout_krw = val_krw * profile["yield"]
            payouts_count = len(profile["months"])
            payout_per_period = annual_payout_krw / payouts_count if payouts_count > 0 else 0.0

            for m in profile["months"]:
                # 1-indexed to 0-indexed month array
                monthly_flows[m - 1] += payout_per_period

            dividend_holdings.append({
                "ticker": ticker,
                "quantity": qty,
                "value_krw": round(val_krw, 2),
                "dividend_yield": profile["yield"],
                "annual_payout_krw": round(annual_payout_krw, 2),
                "months": profile["months"]
            })

        # Calculate reinvestment compound scenarios
        # We assume monthly compounding at the portfolio's aggregate dividend yield
        total_annual_dividend = sum(h["annual_payout_krw"] for h in dividend_holdings)
        aggregate_yield = (total_annual_dividend / portfolio_value_krw) if portfolio_value_krw > 0 else 0.0

        def compound_projection(years: int) -> float:
            # FV = PV * (1 + yield/12)^(years * 12)
            monthly_rate = aggregate_yield / 12.0
            return portfolio_value_krw * ((1.0 + monthly_rate) ** (years * 12))

        projections = {
            "1_year_value_krw": round(compound_projection(1), 2),
            "3_year_value_krw": round(compound_projection(3), 2),
            "5_year_value_krw": round(compound_projection(5), 2),
        }

        return {
            "portfolio_value_krw": round(portfolio_value_krw, 2),
            "annual_dividend_krw": round(total_annual_dividend, 2),
            "aggregate_yield_pct": round(aggregate_yield * 100.0, 2),
            "monthly_payouts_krw": [round(val, 2) for val in monthly_flows],
            "holdings": dividend_holdings,
            "reinvestment_projections": projections
        }
