from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class StrategyCard:
    strategy_id: str
    name: str
    type: str  # e.g., "Ensemble", "Mean Reversion", "Breakout", "DSL"
    investment_objective: str
    suitable_portfolio_type: str
    forbidden_market_regimes: list[str]
    recent_performance: dict[str, Any]  # e.g., {"sharpe_ratio": 1.45, "mdd_pct": 12.5, "win_rate_pct": 62.0}
    risk_description: str
    parameters_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StrategyCardRegistry:
    """Registry to manage strategy cards for the dashboard and agent analysis."""

    def __init__(self) -> None:
        self._cards: dict[str, StrategyCard] = {}
        self._load_defaults()

    def register(self, card: StrategyCard) -> None:
        self._cards[card.strategy_id] = card

    def get_card(self, strategy_id: str) -> StrategyCard | None:
        return self._cards.get(strategy_id)

    def list_cards(self) -> list[StrategyCard]:
        return list(self._cards.values())

    def _load_defaults(self) -> None:
        # 1. Ensemble Card
        self.register(
            StrategyCard(
                strategy_id="ensemble",
                name="다중 지표 앙상블 전략",
                type="Ensemble",
                investment_objective="RSI, EMA, MACD, Bollinger Bands 등 다양한 기술적 지표의 매수 조건을 조합하여 시장 국면에 맞는 안전하고 균형 잡힌 진입 타이밍을 포착합니다.",
                suitable_portfolio_type="balanced",
                forbidden_market_regimes=["bear"],
                recent_performance={
                    "sharpe_ratio": 1.52,
                    "mdd_pct": 10.4,
                    "win_rate_pct": 64.5,
                },
                risk_description="여러 지표가 동시에 일치해야 하므로 강한 추세 시장에서 진입 기회를 놓칠 수 있으며, 지표 간 신호 불일치로 잦은 필터링이 발생할 수 있습니다.",
                parameters_summary="EMA span 20-200, RSI 30-70 범위 필터링 및 MACD/BB 강제 적용 옵션",
            )
        )

        # 2. Connors RSI2 Card
        self.register(
            StrategyCard(
                strategy_id="connors_rsi2",
                name="코너스 RSI2 역추세 전략",
                type="Mean Reversion",
                investment_objective="장기 상승 추세(SMA 200)에 있는 종목 중 극단적인 단기 과매도 상태(RSI 2 < 10)에 진입한 대상을 선별하여 단기 반등 수익을 목표로 합니다.",
                suitable_portfolio_type="short_term",
                forbidden_market_regimes=["bear"],
                recent_performance={
                    "sharpe_ratio": 1.28,
                    "mdd_pct": 14.8,
                    "win_rate_pct": 72.1,
                },
                risk_description="단기 낙폭 과대 종목을 매수하므로 떨어지는 칼날을 잡는 위험이 존재하며, 손절 라인이 부적절할 경우 일시적 급락에 큰 타격을 입을 수 있습니다.",
                parameters_summary="RSI 2 한계값 10 이하, 장기 이평선 이격도 필터링",
            )
        )

        # 3. Williams Breakout Card
        self.register(
            StrategyCard(
                strategy_id="williams_breakout",
                name="윌리엄스 변동성 돌파 전략",
                type="Breakout",
                investment_objective="전일 가격 변동 범위에 특정 멀티플라이어를 곱한 가격대를 당일 돌파할 때 강한 추세 추종 매수를 감행하여 모멘텀 이익을 극대화합니다.",
                suitable_portfolio_type="momentum",
                forbidden_market_regimes=["sideways"],
                recent_performance={
                    "sharpe_ratio": 1.41,
                    "mdd_pct": 11.2,
                    "win_rate_pct": 58.3,
                },
                risk_description="비추세 횡보 국면에서 거짓 돌파(Whipsaw)가 자주 발생하여 수수료 및 슬리ppage 손실이 누적될 수 있습니다.",
                parameters_summary="K-multiplier 0.5-1.2 범위 설정 및 당일 시가 기준 돌파값 연산",
            )
        )

        # 4. Volume Breakout Card
        self.register(
            StrategyCard(
                strategy_id="volume_breakout",
                name="거래량 동반 돌파 전략",
                type="Breakout",
                investment_objective="단기 고가 채널을 상향 돌파함과 동시에, 최근 평균 거래량 대비 급격한 거래량 스파이크가 발생한 종목을 매수하여 추세의 신뢰도를 높입니다.",
                suitable_portfolio_type="momentum",
                forbidden_market_regimes=["bear"],
                recent_performance={
                    "sharpe_ratio": 1.35,
                    "mdd_pct": 13.1,
                    "win_rate_pct": 60.2,
                },
                risk_description="거래량 급증 후 급격한 차익 실현 매물로 인해 꼬리가 길게 달리는 고점 물리기가 발생할 위험이 있습니다.",
                parameters_summary="거래량 평균 돌파 멀티플 2.0배, N일 채널 고가 돌파 기준",
            )
        )


# Global singleton instance for easy access
GLOBAL_STRATEGY_CARD_REGISTRY = StrategyCardRegistry()
