"""Human-friendly Korean explanations for dashboard metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

MetricGroup = Literal[
    "overview",
    "signals",
    "analysis",
    "portfolio",
    "risk",
]


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    group: MetricGroup
    label: str
    plain_name: str
    short_description: str
    good_value: str
    watch_out: str
    source: str = "src/jayu/metric_dictionary.py"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        key="data_validation",
        group="overview",
        label="데이터 검증",
        plain_name="가격 데이터 신뢰도",
        short_description="여러 데이터 제공자의 가격이 서로 맞는지 확인해, 신호 계산에 써도 되는지 보는 지표입니다.",
        good_value="95% 이상이거나 불일치 종목이 0개면 좋습니다.",
        watch_out="낮으면 매수·매도 신호보다 데이터 오류 확인이 먼저입니다.",
    ),
    MetricDefinition(
        key="risk_gate",
        group="overview",
        label="리스크 게이트",
        plain_name="매수 후보 안전 심사",
        short_description="매수 신호가 있더라도 현금, 종목 비중, 섹터 집중, 손실 한도 같은 안전 규칙을 통과했는지 봅니다.",
        good_value="승인 신호가 있고 차단 신호가 0개면 좋습니다.",
        watch_out="차단이 있으면 주문 후보가 아니라 검토 후보입니다.",
    ),
    MetricDefinition(
        key="survivorship_policy",
        group="overview",
        label="생존편향 정책",
        plain_name="상장폐지 종목까지 고려했는지",
        short_description="좋았던 종목만 보고 전략을 평가하지 않도록 과거 사라진 종목까지 포함했는지 확인합니다.",
        good_value="strict 정책과 delisted 포함 상태가 좋습니다.",
        watch_out="미검증이면 백테스트 성과를 그대로 믿기 어렵습니다.",
    ),
    MetricDefinition(
        key="shadow_promotion",
        group="overview",
        label="Shadow 승격",
        plain_name="실전 전 모의 검증 일수",
        short_description="자동 운영 전에 여러 날 shadow 모드에서 같은 규칙이 안정적으로 작동했는지 보는 지표입니다.",
        good_value="필요 일수를 채우고 실패 조건이 없으면 좋습니다.",
        watch_out="부족하면 live 전환보다 shadow 기록을 더 쌓아야 합니다.",
    ),
    MetricDefinition(
        key="today_signal",
        group="overview",
        label="오늘의 신호",
        plain_name="오늘 실제 검토할 매수 후보",
        short_description="전략이 만든 매수 후보 중 데이터와 리스크 심사를 통과한 종목 수입니다.",
        good_value="eligible 후보가 있고 차단 사유가 설명되어 있으면 좋습니다.",
        watch_out="숫자가 많아도 검증 실패가 있으면 우선순위가 내려갑니다.",
    ),
    MetricDefinition(
        key="health_score",
        group="overview",
        label="Health",
        plain_name="운영 건강 점수",
        short_description="최근 실행 성공, 데이터 상태, promotion 조건 등을 합쳐 운영 상태를 빠르게 보는 점수입니다.",
        good_value="기준점 이상이면 정상 운영에 가깝습니다.",
        watch_out="낮으면 최근 실패 run과 health report를 먼저 확인하세요.",
    ),
    MetricDefinition(
        key="publication_status",
        group="signals",
        label="출판 상태",
        plain_name="신호가 오늘 사용 가능한 상태인지",
        short_description="오늘 신호 파일이 안전 검증을 지나 sidecar로 공개됐는지 확인합니다.",
        good_value="published면 화면과 알림에서 같은 신호를 참고할 수 있습니다.",
        watch_out="blocked 또는 missing이면 주문 후보로 보지 않습니다.",
    ),
    MetricDefinition(
        key="eligible_buy",
        group="signals",
        label="검토 가능 매수",
        plain_name="실제로 검토할 매수 후보",
        short_description="매수 신호 중 데이터 검증과 리스크 게이트를 통과한 후보 수입니다.",
        good_value="분모 대비 통과 비율이 높고 이유 코드가 없으면 좋습니다.",
        watch_out="분모가 커도 eligible이 0이면 매수 준비가 되지 않은 상태입니다.",
    ),
    MetricDefinition(
        key="blocked_buy",
        group="signals",
        label="차단 매수",
        plain_name="매수 신호였지만 막힌 후보",
        short_description="전략은 매수라고 봤지만 데이터, 리스크, 브로커 경고 때문에 제외된 후보입니다.",
        good_value="0개가 가장 좋습니다.",
        watch_out="차단 사유가 반복되면 설정이나 포트폴리오 비중을 조정해야 합니다.",
    ),
    MetricDefinition(
        key="hold_signal",
        group="signals",
        label="대기",
        plain_name="지금은 행동하지 않을 후보",
        short_description="매수·매도보다 관망이 낫다고 판단된 신호 수입니다.",
        good_value="시장 환경이 애매할 때 대기가 늘어나는 것은 자연스럽습니다.",
        watch_out="항상 대기만 나오면 전략 조건이 너무 보수적일 수 있습니다.",
    ),
    MetricDefinition(
        key="data_verified",
        group="signals",
        label="데이터 검증",
        plain_name="신호 가격 신뢰도",
        short_description="신호 계산에 사용한 가격이 검증 가능한 데이터인지 확인합니다.",
        good_value="전체 신호가 검증됨이면 좋습니다.",
        watch_out="검증 실패 신호는 가격 오류 가능성이 있어 실행에서 제외해야 합니다.",
    ),
    MetricDefinition(
        key="signal_hash",
        group="signals",
        label="신호 hash",
        plain_name="신호 지문",
        short_description="오늘 신호 내용이 중간에 바뀌지 않았는지 추적하는 짧은 고유값입니다.",
        good_value="출판된 신호와 리포트의 hash가 같으면 재현성이 좋습니다.",
        watch_out="hash가 없으면 어떤 신호를 검토했는지 추적하기 어렵습니다.",
    ),
    MetricDefinition(
        key="entry_price",
        group="signals",
        label="진입가",
        plain_name="매수 기준 가격",
        short_description="전략이 이 가격 근처에서 진입을 고려한다고 계산한 기준점입니다.",
        good_value="현재가와 너무 멀지 않고 손절·목표가가 함께 있어야 합니다.",
        watch_out="진입가만 보고 매수하지 말고 손절가와 목표가를 같이 봐야 합니다.",
    ),
    MetricDefinition(
        key="stop_price",
        group="signals",
        label="손절가",
        plain_name="틀렸다고 인정할 가격",
        short_description="가격이 이 아래로 내려가면 전략 가정이 깨졌다고 보고 손실을 제한하는 기준입니다.",
        good_value="진입 전에 명확히 정해져 있어야 합니다.",
        watch_out="손절가가 없거나 너무 멀면 한 번의 실패가 크게 커질 수 있습니다.",
    ),
    MetricDefinition(
        key="target_price",
        group="signals",
        label="목표가",
        plain_name="이익 실현을 검토할 가격",
        short_description="진입 후 기대하는 상승 여력이 어느 정도인지 보여주는 기준입니다.",
        good_value="목표가까지의 보상이 손절까지의 위험보다 충분히 커야 합니다.",
        watch_out="목표가가 손절 위험보다 가까우면 보상 대비 위험이 불리합니다.",
    ),
    MetricDefinition(
        key="approved_position_pct",
        group="signals",
        label="승인 비중",
        plain_name="최대 투자 허용 비중",
        short_description="리스크 심사를 통과한 뒤 이 종목에 허용된 포트폴리오 비중입니다.",
        good_value="전략 후보라도 비중이 작게 제한되면 안전장치가 작동한 것입니다.",
        watch_out="0%이면 매수 신호가 있어도 실행 대상이 아닙니다.",
    ),
    MetricDefinition(
        key="liquidity_status",
        group="signals",
        label="유동성",
        plain_name="쉽게 사고팔 수 있는지",
        short_description="거래대금과 참여 가능성을 보고 주문이 가격을 흔들 위험이 큰지 봅니다.",
        good_value="통과면 주문이 시장에 주는 충격이 상대적으로 작습니다.",
        watch_out="유동성 부족이면 분할 주문이나 제외가 필요합니다.",
    ),
    MetricDefinition(
        key="reason_code",
        group="signals",
        label="Reason code",
        plain_name="차단 또는 경고 이유",
        short_description="왜 신호가 승인·차단·보류됐는지 기계가 남긴 구조화된 사유입니다.",
        good_value="NO_BLOCKER 또는 빈 값이면 추가 차단 사유가 없습니다.",
        watch_out="같은 코드가 반복되면 해당 설정이나 데이터 소스를 먼저 손봐야 합니다.",
    ),
    MetricDefinition(
        key="rsi",
        group="analysis",
        label="RSI",
        plain_name="가격이 너무 많이 올랐는지 보는 지표",
        short_description="최근 상승과 하락의 힘을 비교해 과열 또는 과매도 가능성을 봅니다.",
        good_value="30 아래는 과매도, 70 위는 과열로 해석하는 경우가 많습니다.",
        watch_out="강한 추세에서는 과열·과매도 구간이 오래 지속될 수 있습니다.",
    ),
    MetricDefinition(
        key="mdd",
        group="portfolio",
        label="MDD",
        plain_name="가장 크게 잃었던 구간",
        short_description="고점 대비 계좌가 최대 몇 퍼센트까지 내려갔는지 보여줍니다.",
        good_value="낮을수록 계좌 방어가 좋습니다.",
        watch_out="수익률이 좋아도 MDD가 크면 버티기 어려운 전략일 수 있습니다.",
    ),
    MetricDefinition(
        key="sharpe",
        group="portfolio",
        label="Sharpe",
        plain_name="위험을 감수한 만큼 수익이 좋았는지",
        short_description="수익률을 변동성으로 나누어 같은 위험 대비 효율을 비교합니다.",
        good_value="1 이상은 참고 가능, 2 이상은 우수하게 보는 경우가 많습니다.",
        watch_out="표본이 적으면 값이 쉽게 과장됩니다.",
    ),
    MetricDefinition(
        key="adx",
        group="analysis",
        label="ADX",
        plain_name="추세가 강한지 약한지",
        short_description="방향이 아니라 추세의 강도만 봅니다.",
        good_value="25 이상이면 추세가 강해졌다고 보는 경우가 많습니다.",
        watch_out="+DI/-DI와 함께 봐야 방향을 알 수 있습니다.",
    ),
    MetricDefinition(
        key="volatility",
        group="risk",
        label="변동성",
        plain_name="가격이 얼마나 크게 흔들리는지",
        short_description="가격의 일일 흔들림 폭을 보고 손절 거리와 비중을 조절합니다.",
        good_value="전략이 감당할 수 있는 범위 안에 있으면 좋습니다.",
        watch_out="급등하면 같은 금액을 사도 실제 위험이 커집니다.",
    ),
    MetricDefinition(
        key="dividend_payout",
        group="portfolio",
        label="배당성향",
        plain_name="이익 중 배당으로 지급하는 비율",
        short_description="기업이 번 돈 중 얼마를 배당으로 돌려주는지 보여줍니다.",
        good_value="현금흐름과 이익 안정성에 맞는 수준이면 좋습니다.",
        watch_out="너무 높으면 배당 지속성이 약해질 수 있습니다.",
    ),
)


def metric_definitions_for(group: MetricGroup, *, limit: int | None = None) -> list[dict[str, str]]:
    rows = [item.to_dict() for item in METRIC_DEFINITIONS if item.group == group]
    return rows[:limit] if limit is not None else rows


def metric_dictionary_payload(*groups: MetricGroup) -> dict[str, list[dict[str, str]]]:
    selected = groups or ("overview", "signals", "analysis", "portfolio", "risk")
    return {group: metric_definitions_for(group) for group in selected}


def metric_definition(key: str) -> dict[str, str] | None:
    for item in METRIC_DEFINITIONS:
        if item.key == key:
            return item.to_dict()
    return None
