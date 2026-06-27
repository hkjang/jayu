"""Tests for the 5 new personal investment management modules.

Covers:
- investment_goal_planner: set_goal, delete_goal, calculate_analysis (FV solver)
- cashflow_planner: add_cashflow, delete_cashflow, calculate_monthly_budget
- dividend_cashflow_simulator: simulate_cashflow projection math
- investor_behavior_insights: analyze_behavior structure
- portfolio_diet_mode: redundancy and micro-position detection
- investment_calendar: get_events, add_custom_event
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Investment Goal Planner
# ──────────────────────────────────────────────────────────────────────────────
from jayu.investment_goal_planner import InvestmentGoalPlanner


class TestInvestmentGoalPlanner:
    def _planner(self, tmp_path: Path) -> InvestmentGoalPlanner:
        # InvestmentGoalPlanner stores at project_root / "state" / "investment_goals.json"
        return InvestmentGoalPlanner(tmp_path)

    def test_set_and_load_goal(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        planner.set_goal(
            goal_id="goal_retire",
            name="은퇴 자금",
            target_amount=1_000_000_000,
            target_date="2036-01-01",
            current_amount=50_000_000,
            monthly_deposit=1_000_000,
            expected_return=0.08,
        )
        goals = planner.load_goals()
        assert len(goals) == 1
        assert goals[0]["goal_id"] == "goal_retire"
        assert goals[0]["name"] == "은퇴 자금"

    def test_overwrite_same_goal_id(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        planner.set_goal("g1", "이름A", 1_000_000, "2030-01-01", 0, 0, 0.0)
        planner.set_goal("g1", "이름B", 2_000_000, "2031-01-01", 0, 0, 0.0)
        goals = planner.load_goals()
        assert len(goals) == 1
        assert goals[0]["name"] == "이름B"

    def test_delete_goal(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        planner.set_goal("g1", "Test", 500_000_000, "2034-01-01", 10_000_000, 500_000, 0.07)
        removed = planner.delete_goal("g1")
        assert removed is True
        assert planner.load_goals() == []

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        assert planner.delete_goal("does_not_exist") is False

    def test_calculate_analysis_returns_required_return(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        goal = {
            "goal_id": "g1",
            "name": "목표",
            "target_amount": 500_000_000,
            "current_amount": 100_000_000,
            "monthly_deposit": 2_000_000,
            "expected_return": 0.08,
            "target_date": "2036-06-01",
        }
        result = planner.calculate_analysis(goal)
        assert "required_annual_return" in result
        assert isinstance(result["required_annual_return"], float)
        assert result["achievement_rate"] == pytest.approx(20.0, rel=0.01)

    def test_calculate_analysis_already_achieved(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        goal = {
            "goal_id": "g1",
            "name": "달성",
            "target_amount": 100_000_000,
            "current_amount": 200_000_000,
            "monthly_deposit": 0,
            "expected_return": 0.05,
            "target_date": "2027-01-01",
        }
        result = planner.calculate_analysis(goal)
        assert result["is_feasible"] is True
        assert result["required_annual_return"] <= 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Cashflow Planner
# ──────────────────────────────────────────────────────────────────────────────
from jayu.cashflow_planner import CashflowPlanner


class TestCashflowPlanner:
    def _planner(self, tmp_path: Path) -> CashflowPlanner:
        return CashflowPlanner(tmp_path)

    def test_add_and_load_cashflow(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        planner.add_cashflow(
            month="2026-06",
            salary_deposit=5_000_000,
            expected_dividends=100_000,
            extra_deposits=0,
            planned_buys=0,
            reserved_cash=1_000_000,
        )
        records = planner.load_cashflows()
        assert len(records) == 1
        assert records[0]["month"] == "2026-06"

    def test_overwrite_same_month(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        planner.add_cashflow("2026-07", 4_000_000, 0, 0, 0, 500_000)
        planner.add_cashflow("2026-07", 5_500_000, 0, 0, 0, 500_000)
        records = planner.load_cashflows()
        assert len(records) == 1
        assert records[0]["salary_deposit"] == 5_500_000

    def test_delete_cashflow(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        planner.add_cashflow("2026-08", 4_000_000, 0, 0, 0, 0)
        assert planner.delete_cashflow("2026-08") is True
        assert planner.load_cashflows() == []

    def test_budget_allocation_positive_net(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        record = {
            "month": "2026-06",
            "salary_deposit": 5_000_000,
            "expected_dividends": 100_000,
            "extra_deposits": 0,
            "planned_buys": 500_000,
            "reserved_cash": 600_000,
        }
        result = planner.calculate_monthly_budget(record)
        # net_investable = 5_100_000 - 600_000 - 500_000 = 4_000_000
        assert result["net_investable_budget"] == pytest.approx(4_000_000, rel=0.01)
        total_allocated = sum(result["allocations"].values())
        assert total_allocated == pytest.approx(4_000_000, rel=0.01)

    def test_budget_zero_when_overspent(self, tmp_path: Path) -> None:
        planner = self._planner(tmp_path)
        record = {
            "month": "2026-06",
            "salary_deposit": 1_000_000,
            "expected_dividends": 0,
            "extra_deposits": 0,
            "planned_buys": 2_000_000,
            "reserved_cash": 0,
        }
        result = planner.calculate_monthly_budget(record)
        assert result["net_investable_budget"] == 0
        assert all(v == 0 for v in result["allocations"].values())


# ──────────────────────────────────────────────────────────────────────────────
# Dividend Cashflow Simulator
# ──────────────────────────────────────────────────────────────────────────────
from jayu.dividend_cashflow_simulator import DividendCashflowSimulator


class TestDividendCashflowSimulator:
    def _holdings(self) -> list[dict]:
        # holdings use {ticker, quantity, price} format
        return [
            {"ticker": "SCHD", "quantity": 100, "price": 100.0},  # $10,000 → 13.5M KRW at 1350
            {"ticker": "SOXL", "quantity": 50, "price": 20.0},    # $1,000 → 1.35M KRW, ~0% dividend
        ]

    def test_monthly_payouts_has_12_elements(self, tmp_path: Path) -> None:
        sim = DividendCashflowSimulator(tmp_path)
        result = sim.simulate_cashflow(self._holdings())
        assert len(result["monthly_payouts_krw"]) == 12

    def test_annual_dividend_positive_for_schd(self, tmp_path: Path) -> None:
        sim = DividendCashflowSimulator(tmp_path)
        # SCHD has 3.4% yield → annual_dividend > 0
        result = sim.simulate_cashflow(self._holdings())
        assert result["annual_dividend_krw"] > 0

    def test_projections_grow_over_time(self, tmp_path: Path) -> None:
        sim = DividendCashflowSimulator(tmp_path)
        result = sim.simulate_cashflow(self._holdings())
        p = result["reinvestment_projections"]
        assert p["5_year_value_krw"] > p["1_year_value_krw"]

    def test_zero_yield_portfolio(self, tmp_path: Path) -> None:
        sim = DividendCashflowSimulator(tmp_path)
        # Only SOXL which has no dividend in profiles → falls back to 1.5% quarterly
        result = sim.simulate_cashflow([{"ticker": "SOXL", "quantity": 10, "price": 20.0}])
        # Should still return a valid structure
        assert "annual_dividend_krw" in result
        assert isinstance(result["annual_dividend_krw"], float)


# ──────────────────────────────────────────────────────────────────────────────
# Investor Behavior Insights
# ──────────────────────────────────────────────────────────────────────────────
from jayu.investor_behavior_insights import InvestorBehaviorInsights


class TestInvestorBehaviorInsights:
    def test_analyze_returns_expected_keys(self, tmp_path: Path) -> None:
        """analyze_behavior() must return standard keys even with no history."""
        # Mock the RuntimePaths and approval history loader to avoid filesystem deps
        with patch("jayu.investor_behavior_insights.load_approval_history", return_value=[]):
            insights = InvestorBehaviorInsights.__new__(InvestorBehaviorInsights)
            insights.project_root = tmp_path
            insights.paths = MagicMock()
            result = insights.analyze_behavior()
        assert "total_decisions_analyzed" in result
        assert "biases_detected" in result
        assert "warnings" in result
        assert "healthy_habits" in result

    def test_fomo_detected_on_override(self, tmp_path: Path) -> None:
        history = [
            {"recommendation_verdict": "blocked", "user_decision": "approve", "action": "buy"},
            {"recommendation_verdict": "blocked", "user_decision": "approve", "action": "buy"},
        ]
        with patch("jayu.investor_behavior_insights.load_approval_history", return_value=history):
            insights = InvestorBehaviorInsights.__new__(InvestorBehaviorInsights)
            insights.project_root = tmp_path
            insights.paths = MagicMock()
            result = insights.analyze_behavior()
        assert result["biases_detected"]["fomo_override_count"] == 2
        bias_tags = [w["bias"] for w in result["warnings"]]
        assert any("FOMO" in tag for tag in bias_tags)

    def test_no_warnings_with_clean_history(self, tmp_path: Path) -> None:
        # All approved signals have a valid recommendation
        history = [
            {"recommendation_verdict": "approved", "user_decision": "approve", "action": "buy"},
        ] * 10  # 10 trades, within overtrading threshold of 15
        with patch("jayu.investor_behavior_insights.load_approval_history", return_value=history):
            insights = InvestorBehaviorInsights.__new__(InvestorBehaviorInsights)
            insights.project_root = tmp_path
            insights.paths = MagicMock()
            result = insights.analyze_behavior()
        # With 10 approvals (< 15 threshold), no overtrading warning
        assert result["biases_detected"]["fomo_override_count"] == 0
        assert result["biases_detected"]["loss_aversion_holds"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Portfolio Diet Mode
# ──────────────────────────────────────────────────────────────────────────────
from jayu.portfolio_diet_mode import PortfolioDietMode


class TestPortfolioDietMode:
    def _make_holdings(self) -> list[dict]:
        # holdings use {ticker, quantity, price} format
        return [
            {"ticker": "SOXL", "quantity": 100, "price": 20.0},  # $2000 → ~2.7M KRW
            {"ticker": "TQQQ", "quantity": 80,  "price": 50.0},  # $4000 → ~5.4M KRW
            {"ticker": "QQQ",  "quantity": 10,  "price": 450.0}, # $4500 → ~6.07M KRW
            {"ticker": "NVDL", "quantity": 5,   "price": 30.0},  # $150  → ~202K KRW (micro)
            {"ticker": "TINY", "quantity": 1,   "price": 10.0},  # $10   → ~13.5K KRW (micro)
        ]

    def test_redundancy_qqq_tqqq_detected(self, tmp_path: Path) -> None:
        diet = PortfolioDietMode(tmp_path)
        result = diet.analyze_portfolio_diet(self._make_holdings())
        flags = result["redundancy_warnings"]
        tickers_in_flags = [t for f in flags for t in f.get("tickers", [])]
        assert "QQQ" in tickers_in_flags and "TQQQ" in tickers_in_flags

    def test_redundancy_soxl_nvdl_detected(self, tmp_path: Path) -> None:
        diet = PortfolioDietMode(tmp_path)
        result = diet.analyze_portfolio_diet(self._make_holdings())
        flags = result["redundancy_warnings"]
        tickers_in_flags = [t for f in flags for t in f.get("tickers", [])]
        assert "SOXL" in tickers_in_flags and "NVDL" in tickers_in_flags

    def test_micro_positions_flagged(self, tmp_path: Path) -> None:
        diet = PortfolioDietMode(tmp_path)
        result = diet.analyze_portfolio_diet(self._make_holdings())
        diet_recs = result["diet_recommendations"]
        micro_rec = next((r for r in diet_recs if "Micro" in r.get("category", "")), None)
        assert micro_rec is not None
        assert "TINY" in micro_rec.get("tickers", [])

    def test_clean_portfolio_no_warnings(self, tmp_path: Path) -> None:
        # Two equal-weight holdings, no redundancy
        holdings = [
            {"ticker": "SCHD", "quantity": 100, "price": 100.0},
            {"ticker": "SPY",  "quantity": 10,  "price": 500.0},
        ]
        diet = PortfolioDietMode(tmp_path)
        result = diet.analyze_portfolio_diet(holdings)
        assert result["redundancy_warnings"] == []
        assert result["diet_recommendations"] == []


# ──────────────────────────────────────────────────────────────────────────────
# Investment Calendar
# ──────────────────────────────────────────────────────────────────────────────
from jayu.investment_calendar import InvestmentCalendar


class TestInvestmentCalendar:
    def test_get_events_returns_list(self) -> None:
        cal = InvestmentCalendar()
        events = cal.get_events()
        assert isinstance(events, list)
        assert len(events) > 0

    def test_events_sorted_by_date(self) -> None:
        cal = InvestmentCalendar()
        cal.add_custom_event("2099-12-31", "macro", "멀리 있는 이벤트")
        cal.add_custom_event("2020-01-01", "salary", "오래된 이벤트")
        events = cal.get_events()
        dates = [e["date"] for e in events]
        assert dates == sorted(dates)

    def test_add_custom_event(self) -> None:
        cal = InvestmentCalendar()
        before = len(cal.get_events())
        cal.add_custom_event("2026-09-15", "earnings", "NVDA 실적발표", "Q3 실적")
        after = len(cal.get_events())
        assert after == before + 1
        custom = next((e for e in cal.get_events() if e["date"] == "2026-09-15"), None)
        assert custom is not None
        assert custom["title"] == "NVDA 실적발표"

    def test_filter_by_start_date(self) -> None:
        cal = InvestmentCalendar()
        events = cal.get_events(start_date="2026-06-20")
        assert all(e["date"] >= "2026-06-20" for e in events)

    def test_filter_by_end_date(self) -> None:
        cal = InvestmentCalendar()
        events = cal.get_events(end_date="2026-06-25")
        assert all(e["date"] <= "2026-06-25" for e in events)
