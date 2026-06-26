from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ConfigDict


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str
    mode: str
    status: str | None = None
    execution_status: str | None = None
    display_status: str | None = None
    safety_decision: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    command: str | None = None
    config_hash: str | None = None
    data_hash: str | None = None
    signal_hash: str | None = None
    failure_code: str | None = None


class DecisionSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    overall: str
    headline: str | None = None
    top_reasons: list[dict[str, Any]] = Field(default_factory=list)
    affected_tickers: list[str] = Field(default_factory=list)
    action: dict[str, Any] | None = None


class GatesSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    promotion: dict[str, Any] | None = None
    survivorship: dict[str, Any] | None = None


class SignalsSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    buy: int | None = 0
    eligible: int | None = 0
    blocked: int | None = 0
    hold: int | None = 0
    total: int | None = None
    approved: int | None = None


class TodayBoardItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    ticker: str | None = None
    label: str | None = None
    status: str | None = None
    action_type: str | None = None
    queue_status: str | None = "new"
    queue_id: str | None = None
    detail: str | None = None
    source: str | None = None
    page: str | None = None
    command: str | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None


class TodayBoard(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tasks: list[TodayBoardItem] = Field(default_factory=list)
    risky_stocks: list[TodayBoardItem] = Field(default_factory=list)
    buy_candidates: list[TodayBoardItem] = Field(default_factory=list)
    sell_candidates: list[TodayBoardItem] = Field(default_factory=list)
    order_prepares: list[TodayBoardItem] = Field(default_factory=list)
    dividend_reviews: list[TodayBoardItem] = Field(default_factory=list)
    action_queue: list[dict[str, Any]] = Field(default_factory=list)


class DecisionTimelineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    label: str
    status: str
    failure_code: str | None = None
    next_action: dict[str, Any] | None = None


class SessionReplaySummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str
    step_count: int


class SessionReplay(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: SessionReplaySummary
    events: list[dict[str, Any]] = Field(default_factory=list)


class DataLineageSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str
    provider_count: int


class DataLineage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: DataLineageSummary
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class FailurePatternsSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latest_failure_code: str | None = None
    top_code_count: int


class FailurePatterns(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: FailurePatternsSummary
    items: list[dict[str, Any]] = Field(default_factory=list)


class RunEvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str
    missing_required_count: int


class RunEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: RunEvidenceSummary
    items: list[dict[str, Any]] = Field(default_factory=list)


class MetricDictionary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    overview: list[dict[str, Any]] = Field(default_factory=list)


class RecoveryGuide(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    summary: dict[str, Any]
    items: list[dict[str, Any]] = Field(default_factory=list)


class OverviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str | int | float
    run: RunSummary
    decision: DecisionSummary
    gates: GatesSummary
    signals: SignalsSummary
    today_board: TodayBoard
    decision_timeline: list[DecisionTimelineItem] = Field(default_factory=list)
    session_replay: SessionReplay
    data_lineage: DataLineage | None = None
    failure_patterns: FailurePatterns
    run_evidence: RunEvidence
    metric_dictionary: MetricDictionary
    recommended_actions: list[dict[str, Any]] = Field(default_factory=list)
    recovery_guide: RecoveryGuide


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str | int | float
    run_id: str
    overall: str
    status_rank: int
    recommended_next_action: dict[str, Any] | None = None
    top_blockers: list[dict[str, Any]] = Field(default_factory=list)
    affected_tickers: list[str] = Field(default_factory=list)
    context: dict[str, Any]


class DataQualitySummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    provider_count: int
    blocked_tickers: list[str] = Field(default_factory=list)


class DataQualityResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str | int | float
    run_id: str
    summary: DataQualitySummary
    mismatches: list[dict[str, Any]] = Field(default_factory=list)
    data_lineage: DataLineage | None = None


class RiskSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    blocked_count: int
    approved_count: int


class RiskResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str | int | float
    run_id: str
    summary: RiskSummary
    checks: list[dict[str, Any]] = Field(default_factory=list)


class SignalsResponseSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    buy_count: int | None = None
    eligible_count: int | None = None
    blocked_count: int | None = None
    hold_count: int | None = None
    data_verified_count: int | None = None
    total_count: int | None = None
    data_verified_rate: float | None = None
    signal_count: int | None = None
    evaluated_count: int | None = None


class SignalsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str | int | float
    run_id: str | None = None
    summary: SignalsResponseSummary
    rows: list[dict[str, Any]] = Field(default_factory=list)


class TraderLensResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str | int | float
    run_id: str | None = None
    summary: dict[str, Any]
    traders: list[dict[str, Any]] = Field(default_factory=list)


class AutotradingStatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str | int | float | None = None
    status: dict[str, Any]
    readiness_score: dict[str, Any] | None = None
    paper_promotion_report: dict[str, Any] | None = None
    phases: list[dict[str, Any]] = Field(default_factory=list)
    safety_requirements: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str | None = None
    warning: str | None = None


class RunsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str | int | float
    runs: list[dict[str, Any]] = Field(default_factory=list)
    failure_patterns: FailurePatterns | None = None

