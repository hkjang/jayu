from __future__ import annotations

from pathlib import Path
from typing import Any

from .dividend_cashflow_simulator import DividendCashflowSimulator


class PortfolioDietMode:
    """Analyzes the current portfolio holdings to recommend diet adjustments (ETF redundancies, micro-positions)."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.simulator = DividendCashflowSimulator(project_root)

    def analyze_portfolio_diet(
        self,
        holdings: list[dict[str, Any]] | None = None,
        fx_rate: float = 1350.0
    ) -> dict[str, Any]:
        """Perform static analysis on asset count, weight, and redundancy to suggest diet actions."""
        if holdings is None:
            csv_path = self.project_root / "toss_portfolio.csv"
            holdings = self.simulator.load_holdings_from_csv(csv_path)

        total_value_krw = 0.0
        parsed_holdings = []

        for h in holdings:
            ticker = h.get("ticker") or h.get("symbol")
            qty = h.get("quantity") or h.get("qty") or 0.0
            price = h.get("price") or h.get("current_price") or 0.0
            if not ticker:
                continue
            is_us = not ticker.isdigit() and not (ticker.endswith(".KS") or ticker.endswith(".KQ"))
            val_krw = qty * price * (fx_rate if is_us else 1.0)
            total_value_krw += val_krw
            parsed_holdings.append({
                "ticker": ticker,
                "value_krw": val_krw,
                "quantity": qty
            })

        # Calculate percentages
        for h in parsed_holdings:
            h["weight_pct"] = (h["value_krw"] / total_value_krw * 100.0) if total_value_krw > 0 else 0.0

        diet_recommendations = []
        redundancy_flags = []

        # 1. Check for Duplicate ETF or overlapping themes
        # If both QQQ and TQQQ exist, or SOXL and NVDL (heavy overlap in technology leverage)
        has_qqq = any(h["ticker"] == "QQQ" for h in parsed_holdings)
        has_tqqq = any(h["ticker"] == "TQQQ" for h in parsed_holdings)
        has_soxl = any(h["ticker"] == "SOXL" for h in parsed_holdings)
        has_nvdl = any(h["ticker"] == "NVDL" for h in parsed_holdings)

        if has_qqq and has_tqqq:
            redundancy_flags.append({
                "type": "Leverage Redundancy (레버리지 중복)",
                "tickers": ["QQQ", "TQQQ"],
                "reason": "동일 지수(Nasdaq-100)의 1배수와 3배수를 동시에 보유 중입니다. 변동성 잠식(Volatility Drag)을 고려해 한쪽으로 비중을 단순화하는 것을 권장합니다."
            })
        if has_soxl and has_nvdl:
            redundancy_flags.append({
                "type": "Sector Heavy Redundancy (반도체/테크 편중 중복)",
                "tickers": ["SOXL", "NVDL"],
                "reason": "필라델피아 반도체 3배와 엔비디아 레버리지가 중복되어 특정 기술주 변동성에 극도로 과도한 위험이 누적되었습니다."
            })

        # 2. Check for Diworsification (Excessive positions count)
        ticker_count = len(parsed_holdings)
        if ticker_count > 15:
            diet_recommendations.append({
                "category": "Excessive Tickers (과도한 종목 수)",
                "level": "warning",
                "message": f"현재 보유 종목 수가 {ticker_count}개로 매우 많습니다. 개인 투자자가 15개 이상의 종목을 밀착 감시 및 리밸런싱하기는 어렵습니다. 핵심 우량자산 위주로 10개 내외로 다이어트가 필요합니다."
            })

        # 3. Negligible micro-positions (Weight < 1.0%)
        micro_positions = []
        for h in parsed_holdings:
            if h["weight_pct"] < 1.0 and h["value_krw"] > 0:
                micro_positions.append(h["ticker"])

        if micro_positions:
            diet_recommendations.append({
                "category": "Micro-positions Pruning (미세 비중 정리 대상)",
                "level": "info",
                "tickers": micro_positions,
                "message": f"보유 비중이 1% 미만인 소액 종목({', '.join(micro_positions)})이 다수 감지되었습니다. 이 종목들은 수익이 나더라도 포트폴리오 전체 성과에 거의 기여하지 못하므로, 전량 정리하여 핵심 포지션에 합산하는 것을 제안합니다."
            })

        return {
            "total_value_krw": round(total_value_krw, 2),
            "ticker_count": ticker_count,
            "parsed_holdings": parsed_holdings,
            "redundancy_warnings": redundancy_flags,
            "diet_recommendations": diet_recommendations
        }
