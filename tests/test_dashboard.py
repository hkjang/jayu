import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import pytest

from jayu.dashboard import (
    build_dashboard_decision,
    build_dashboard_data_quality,
    build_dashboard_overview,
    build_dashboard_api_monitoring,
    build_dashboard_promotion,
    build_dashboard_risk,
    build_dashboard_settings_validation,
    build_dashboard_signals,
    build_dashboard_trader_lens,
    build_dashboard_toss_accounts,
    build_dashboard_toss_market_snapshot,
    build_dashboard_toss_portfolio,
    build_dashboard_toss_status,
    build_dashboard_toss_reconciliation,
    build_dashboard_toss_order_plan,
    create_dashboard_server,
    dashboard_static_dir,
    list_dashboard_runs,
)
from jayu.io import atomic_write_json, read_json
from jayu.paths import RuntimePaths


def _paths(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths.from_root(tmp_path)
    paths.ensure_runtime_dirs()
    return paths


def _write_run(paths: RuntimePaths) -> Path:
    run_dir = paths.runs_dir / "run-001"
    run_dir.mkdir()
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": "run-001",
            "command": "signal",
            "execution_mode": "shadow",
            "status": "success",
            "started_at": "2026-06-14T00:00:00+00:00",
            "finished_at": "2026-06-14T00:05:00+00:00",
            "config_hash": "config-hash",
            "data_hashes": {"SOXL": "price-hash"},
            "survivorship_audit": {
                "policy": "strict",
                "valid": True,
                "includes_delisted": True,
                "universe_source": "point_in_time",
            },
            "data_reports": {
                "SOXL": {
                    "ticker": "SOXL",
                    "valid": True,
                    "price_verified": False,
                    "price_usable": False,
                }
            },
            "result": {
                "mode": "shadow",
                "data_hash": "data-hash",
                "signal_hash": "signal-hash",
            },
        },
    )
    atomic_write_json(
        run_dir / "data_sources.json",
        {
            "sources": [
                {
                    "provider": "yahoo",
                    "ticker": "SOXL",
                    "status": "success",
                    "rows": 3,
                },
                {
                    "provider": "tiingo",
                    "ticker": "SOXL",
                    "status": "success",
                    "rows": 2,
                },
            ]
        },
    )
    atomic_write_json(
        run_dir / "provider_disagreement_report.json",
        {
            "disagreements": [
                {
                    "ticker": "SOXL",
                    "disagreements": [
                        {
                            "baseline": "yahoo",
                            "candidate": "tiingo",
                            "value_mismatches": [
                                {
                                    "date": "2026-06-13",
                                    "field": "Close",
                                    "relative_delta": 0.02,
                                    "threshold": 0.005,
                                    "values": {"yahoo": 100.0, "tiingo": 98.0},
                                }
                            ],
                            "date_mismatches": [
                                {
                                    "date": "2026-06-12",
                                    "present_in": ["yahoo"],
                                    "missing_in": ["tiingo"],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )
    atomic_write_json(
        run_dir / "signals_risk.json",
        {
            "SOXL": {
                "signal": "entry",
                "action": "buy",
                "eligible": False,
                "blocked": True,
                "status": "blocked",
                "price": 100.0,
                "stop_price": 92.0,
                "target_price": 118.0,
                "approved_position_pct": 0.0,
                "reason_codes": ["SECTOR_EXPOSURE_EXCEEDED"],
                "risk": {
                    "reason_codes": ["SECTOR_EXPOSURE_EXCEEDED"],
                    "data_trust": {"price": {"verified": False}},
                    "violation_details": [
                        {
                            "code": "SECTOR_EXPOSURE_EXCEEDED",
                            "metric": "sector_exposure",
                            "observed": 0.62,
                            "limit": 0.4,
                        }
                    ],
                },
            }
        },
    )
    atomic_write_json(
        run_dir / "risk_explanation.json",
        {
            "approved_count": 0,
            "blocked_count": 1,
            "hold_count": 0,
            "top_block_reasons": [{"code": "SECTOR_EXPOSURE_EXCEEDED", "count": 1}],
            "signals": [
                {
                    "ticker": "SOXL",
                    "action": "buy",
                    "reviewed": True,
                    "eligible": False,
                    "approved_position_pct": 0.0,
                    "passed": [{"metric": "cash_pct", "observed": 0.3, "limit": 0.2}],
                    "failed": [
                        {
                            "code": "SECTOR_EXPOSURE_EXCEEDED",
                            "metric": "sector_exposure",
                            "observed": 0.62,
                            "limit": 0.4,
                            "excess": 0.22,
                        }
                    ],
                }
            ],
        },
    )
    atomic_write_json(
        run_dir / "safety_verdict.json",
        {
            "overall": "blocked",
            "reasons": [
                {
                    "component": "data",
                    "code": "DATA_DISAGREEMENT",
                    "message": "provider disagreement exceeded tolerance",
                },
                {
                    "component": "risk",
                    "code": "SECTOR_EXPOSURE_EXCEEDED",
                    "message": "sector exposure exceeded",
                },
            ],
        },
    )
    atomic_write_json(
        run_dir / "promotion.json",
        {
            "eligible": False,
            "shadow_days": ["2026-06-13", "2026-06-14"],
            "criteria": [],
            "metrics": {},
        },
    )
    atomic_write_json(paths.state_dir / "health.json", {"health_score": 72})
    return run_dir


class FakeTossDashboardClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def accounts(self) -> dict[str, object]:
        self.calls.append("accounts")
        return {
            "result": [
                {
                    "accountNo": "12345678901",
                    "accountSeq": 1,
                    "accountType": "BROKERAGE",
                }
            ]
        }

    def prices(self, symbols: object) -> dict[str, object]:
        self.calls.append(f"prices:{symbols}")
        rows = symbols if isinstance(symbols, list) else str(symbols).split(",")
        return {
            "prices": [
                {
                    "symbol": symbol,
                    "currentPrice": 120 if symbol == "AAPL" else 70000,
                    "changeRate": 0.04 if symbol == "AAPL" else -0.01,
                }
                for symbol in rows
            ]
        }

    def stocks(self, symbols: object) -> dict[str, object]:
        self.calls.append(f"stocks:{symbols}")
        rows = symbols if isinstance(symbols, list) else str(symbols).split(",")
        return {
            "stocks": [
                {
                    "symbol": symbol,
                    "stockName": "Apple" if symbol == "AAPL" else "Samsung Electronics",
                    "securityType": "COMMON_STOCK",
                    "sector": "Technology",
                    "industry": "Consumer Electronics" if symbol == "AAPL" else "Semiconductors",
                }
                for symbol in rows
            ]
        }

    def stock_warnings(self, symbol: str) -> dict[str, object]:
        self.calls.append(f"warnings:{symbol}")
        if symbol == "005930":
            return {"warnings": [{"code": "INVESTMENT_CAUTION", "message": "sample warning"}]}
        return {"warnings": []}

    def price_limits(self, symbol: str) -> dict[str, object]:
        self.calls.append(f"price_limits:{symbol}")
        return {"symbol": symbol, "upper": 110, "lower": 90}

    def orderbook(self, symbol: str) -> dict[str, object]:
        self.calls.append(f"orderbook:{symbol}")
        return {"symbol": symbol, "asks": [], "bids": []}

    def trades(self, symbol: str, *, count: int = 50) -> dict[str, object]:
        self.calls.append(f"trades:{symbol}:{count}")
        return {"trades": [{"symbol": symbol, "price": 100}]}

    def candles(self, symbol: str, *, interval: str, count: int = 100) -> dict[str, object]:
        self.calls.append(f"candles:{symbol}:{interval}:{count}")
        return {"candles": [{"symbol": symbol, "interval": interval, "close": 100}]}

    def holdings(self, *, account: str | None = None, symbol: str | None = None) -> dict[str, object]:
        self.calls.append(f"holdings:{account}:{symbol}")
        if symbol:
            return {"holdings": [{"symbol": symbol, "quantity": 1}]}
        return {
            "result": [
                {
                    "symbol": "AAPL",
                    "stockName": "Apple",
                    "quantity": 2,
                    "averagePrice": 100,
                    "currentPrice": 120,
                    "currency": "USD",
                },
                {
                    "symbol": "005930",
                    "stockName": "Samsung Electronics",
                    "quantity": 10,
                    "averagePrice": 60000,
                    "currentPrice": 70000,
                    "currency": "KRW",
                },
            ]
        }

    def sellable_quantity(self, symbol: str, *, account: str | None = None) -> dict[str, object]:
        self.calls.append(f"sellable:{account}:{symbol}")
        return {"symbol": symbol, "sellableQuantity": 1}

    def buying_power(self, *, currency: str, account: str | None = None) -> dict[str, object]:
        self.calls.append(f"buying_power:{account}:{currency}")
        return {"result": {"currency": currency, "buyingPower": 1000 if currency == "USD" else 0}}

    def commissions(self, *, account: str | None = None) -> dict[str, object]:
        self.calls.append(f"commissions:{account}")
        return {"result": {"commissionRate": 0.0005}}

    def exchange_rate(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        date_time: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(f"exchange_rate:{base_currency}:{quote_currency}:{date_time}")
        return {
            "result": {
                "baseCurrency": base_currency,
                "quoteCurrency": quote_currency,
                "rate": "1400",
                "midRate": "1395",
                "changeRate": 0.02,
                "rateChangeType": "UP",
                "validFrom": "2026-03-25T09:30:00+09:00",
                "validUntil": "2026-03-25T09:31:00+09:00",
            }
        }


def test_dashboard_overview_prioritizes_data_error_and_actions(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    report = build_dashboard_overview(
        paths,
        run_id="run-001",
        now=datetime(2026, 6, 14, 1, tzinfo=UTC),
    )

    assert report["run"]["mode"] == "shadow"
    assert report["decision"]["overall"] == "data_error"
    assert report["gates"]["data"]["disagreement_count"] == 1
    assert report["gates"]["risk"]["blocked_count"] == 1
    assert report["signals"]["blocked"] == 1
    assert report["today_board"]["tasks"][0]["label"] == "데이터 검증 확인"
    assert report["today_board"]["tasks"][0]["action_type"] == "data_check"
    assert report["today_board"]["tasks"][0]["queue_status"] == "new"
    assert report["today_board"]["risky_stocks"][0]["ticker"] == "SOXL"
    assert report["today_board"]["risky_stocks"][0]["action_type"] == "risk_review"
    assert report["today_board"]["buy_candidates"] == []
    assert report["today_board"]["action_queue"][0]["queue_section"] == "tasks"
    timeline = report["decision_timeline"]
    assert [item["id"] for item in timeline] == [
        "data_collection",
        "provider_validation",
        "signal_generation",
        "risk_review",
        "toss_reconciliation",
        "order_review",
        "notification_ready",
    ]
    assert timeline[1]["failure_code"] == "DATA_DISAGREEMENT"
    assert timeline[3]["failure_code"] == "SECTOR_EXPOSURE_EXCEEDED"
    assert timeline[3]["next_action"]["page"] == "risk"
    assert timeline[5]["status"] == "not_evaluated"
    replay = report["session_replay"]
    assert replay["summary"]["run_id"] == "run-001"
    assert replay["summary"]["step_count"] >= 7
    assert any(item["id"] == "risk_review" for item in replay["events"])
    overview_metrics = report["metric_dictionary"]["overview"]
    assert any(item["key"] == "data_validation" for item in overview_metrics)
    assert overview_metrics[0]["plain_name"] == "가격 데이터 신뢰도"
    assert report["decision"]["top_reasons"][0]["code"] == "DATA_DISAGREEMENT"
    assert report["recommended_actions"][0]["page"] == "data-quality"
    assert report["recovery_guide"]["status"] == "blocked"
    assert report["recovery_guide"]["summary"]["blocked_count"] >= 1
    assert {item["code"] for item in report["recovery_guide"]["items"]} >= {
        "DATA_DISAGREEMENT",
        "SECTOR_EXPOSURE_EXCEEDED",
    }


def test_dashboard_overview_promotes_toss_stock_warning_to_today_board(tmp_path: Path):
    paths = _paths(tmp_path)
    run_dir = _write_run(paths)
    atomic_write_json(
        run_dir / "signals_risk.json",
        {
            "AAPL": {
                "signal": "entry",
                "action": "buy",
                "eligible": True,
                "status": "eligible",
                "price": 120.0,
                "stop_price": 112.0,
                "target_price": 140.0,
                "approved_position_pct": 0.05,
            }
        },
    )
    atomic_write_json(
        paths.state_dir / "stock_warning_gate.json",
        {
            "AAPL": {
                "has_warning": True,
                "message": "Broker warning flag: OVERHEATED",
                "warnings": {"result": [{"warningType": "OVERHEATED"}]},
            }
        },
    )

    report = build_dashboard_overview(paths, run_id="run-001")

    assert report["today_board"]["buy_candidates"] == []
    warning_item = next(
        item for item in report["today_board"]["risky_stocks"] if item["ticker"] == "AAPL"
    )
    assert warning_item["status"] == "blocked"
    assert warning_item["action_type"] == "broker_warning"
    assert warning_item["queue_status"] == "new"
    assert warning_item["queue_id"] == "broker-warning-aapl"
    assert warning_item["detail"] == "Broker warning flag: OVERHEATED"
    assert "Toss /api/v1/stocks/{symbol}/warnings" in warning_item["source"]


def test_dashboard_overview_adds_order_prepare_queue_for_buy_candidates(tmp_path: Path):
    paths = _paths(tmp_path)
    run_dir = _write_run(paths)
    atomic_write_json(
        run_dir / "signals_risk.json",
        {
            "AAPL": {
                "signal": "entry",
                "action": "buy",
                "eligible": True,
                "status": "eligible",
                "price": 120.0,
                "stop_price": 112.0,
                "target_price": 140.0,
                "approved_position_pct": 0.05,
            }
        },
    )

    report = build_dashboard_overview(paths, run_id="run-001")

    buy_item = report["today_board"]["buy_candidates"][0]
    assert buy_item["ticker"] == "AAPL"
    assert buy_item["action_type"] == "buy_review"
    assert buy_item["queue_status"] == "new"
    order_item = report["today_board"]["order_prepares"][0]
    assert order_item["action_type"] == "order_prepare"
    assert order_item["page"] == "toss-account"
    assert "OrderIntent" in order_item["source"]
    assert any(item["queue_id"] == "order-prepare-buy-candidates" for item in report["today_board"]["action_queue"])


def test_dashboard_decision_api_prioritizes_next_action_and_blockers(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    report = build_dashboard_decision(
        paths,
        run_id="run-001",
        now=datetime(2026, 6, 14, 1, tzinfo=UTC),
    )

    assert report["overall"] == "data_error"
    assert report["status_rank"] == 0
    assert report["recommended_next_action"]["page"] == "data-quality"
    assert report["top_blockers"][0]["code"] == "DATA_DISAGREEMENT"
    assert report["top_blockers"][0]["action"]["page"] == "data-quality"
    assert report["affected_tickers"] == ["SOXL"]
    assert report["context"]["data_hash"]


def test_dashboard_survivorship_action_exposes_validation_command(tmp_path: Path):
    paths = _paths(tmp_path)
    run_dir = _write_run(paths)
    manifest = {
        **read_json(run_dir / "manifest.json"),
        "status": "failed",
        "failure_code": "SURVIVORSHIP_GATE_FAILED",
        "data_reports": {},
    }
    atomic_write_json(run_dir / "manifest.json", manifest)
    (run_dir / "safety_verdict.json").unlink()
    atomic_write_json(run_dir / "provider_disagreement_report.json", {"disagreements": []})
    (run_dir / "risk_explanation.json").unlink()
    (run_dir / "signals_risk.json").unlink()
    (run_dir / "promotion.json").unlink()

    report = build_dashboard_overview(paths, run_id="run-001")

    action = next(
        item for item in report["recommended_actions"] if item["id"] == "review-survivorship"
    )
    assert action["page"] is None
    assert action["command"] == "uv run jayu validate-config --mode research"


def test_dashboard_data_quality_flattens_provider_values_and_dates(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    report = build_dashboard_data_quality(paths, run_id="run-001")

    assert report["summary"]["status"] == "data_error"
    assert report["summary"]["provider_count"] == 2
    assert report["summary"]["blocked_tickers"] == ["SOXL"]
    assert {row["kind"] for row in report["mismatches"]} == {"value", "date"}
    value = next(row for row in report["mismatches"] if row["kind"] == "value")
    assert value["values"] == {"yahoo": 100.0, "tiingo": 98.0}


def test_dashboard_risk_keeps_current_limit_and_excess(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    report = build_dashboard_risk(paths, run_id="run-001")

    assert report["summary"]["status"] == "blocked"
    assert report["summary"]["blocked_count"] == 1
    failed = next(row for row in report["checks"] if row["status"] == "blocked")
    assert failed["observed"] == 0.62
    assert failed["limit"] == 0.4
    assert failed["excess"] == 0.22


def test_dashboard_signals_exposes_publication_prices_and_reasons(tmp_path: Path):
    paths = _paths(tmp_path)
    run_dir = _write_run(paths)
    previous_run = paths.runs_dir / "run-000"
    previous_run.mkdir()
    atomic_write_json(
        previous_run / "manifest.json",
        {
            "run_id": "run-000",
            "command": "signal",
            "execution_mode": "shadow",
            "status": "success",
            "started_at": "2026-06-10T00:00:00+00:00",
            "finished_at": "2026-06-10T00:05:00+00:00",
            "result": {"mode": "shadow"},
        },
    )
    atomic_write_json(
        previous_run / "signals_risk.json",
        {
            "SOXL": {
                "signal": "entry",
                "action": "buy",
                "eligible": True,
                "status": "eligible",
                "price": 95.0,
                "reason_codes": ["MOMENTUM_OK"],
            }
        },
    )
    atomic_write_json(
        run_dir / "signal_publication.json",
        {
            "status": "blocked",
            "run_id": "run-001",
            "signal_date": "2026-06-14",
            "failure_code": "SAFETY_VERDICT_BLOCKED",
        },
    )
    atomic_write_json(
        paths.state_dir / "signal_outcome.json",
        {
            "status": "partial",
            "horizons": [1, 5, 20],
            "summary": {
                "status": "partial",
                "signal_count": 2,
                "evaluated_count": 1,
                "pending_count": 1,
                "buy_candidate_count": 1,
                "blocked_buy_count": 1,
                "hold_count": 0,
                "sell_candidate_count": 0,
            },
            "aggregate": {"1d": {"avg_return": -0.03, "sample_count": 1, "hit_rate": 0.0}},
            "by_decision_group": [
                {
                    "key": "blocked_buy",
                    "label": "차단된 매수",
                    "signal_count": 1,
                    "evaluated_count": 1,
                    "horizons": {
                        "1d": {
                            "avg_return": -0.03,
                            "sample_count": 1,
                            "hit_rate": 0.0,
                        }
                    },
                }
            ],
            "by_strategy": [],
            "blocked_avoidance": {
                "1d": {
                    "blocked_count": 1,
                    "sample_count": 1,
                    "avoided_loss_count": 1,
                    "avg_avoided_loss": 0.03,
                }
            },
            "source": "signals JSON · price history JSON · signal_outcome.py",
        },
    )
    atomic_write_json(
        paths.state_dir / "stock_lifecycle.json",
        {
            "states": {
                "SOXL": {
                    "ticker": "SOXL",
                    "status": "candidate",
                    "transitioned_at": "2026-06-10T00:05:00+00:00",
                }
            },
            "history": [],
        },
    )

    report = build_dashboard_signals(paths, run_id="run-001")

    assert report["summary"]["blocked_count"] == 1
    assert report["publication"]["status"] == "blocked"
    signal_metrics = report["metric_dictionary"]["signals"]
    assert any(item["key"] == "stop_price" for item in signal_metrics)
    assert signal_metrics[0]["plain_name"] == "신호가 오늘 사용 가능한 상태인지"
    row = report["rows"][0]
    assert row["ticker"] == "SOXL"
    assert row["entry_price"] == 100.0
    assert row["stop_price"] == 92.0
    assert row["target_price"] == 118.0
    assert row["failed"][0]["code"] == "SECTOR_EXPOSURE_EXCEEDED"
    history = report["signal_history"]
    assert history["status"] == "success"
    card = history["cards"][0]
    assert card["ticker"] == "SOXL"
    assert card["windows"]["7d"]["run_count"] == 2
    assert card["windows"]["7d"]["eligible_count"] == 1
    assert card["windows"]["7d"]["blocked_count"] == 1
    assert card["trend"] == "deteriorating"
    assert "운영 가능 → 차단" in card["changes"][0]["summary"]
    outcome = report["signal_outcome"]
    assert outcome["status"] == "partial"
    assert outcome["summary"]["evaluated_count"] == 1
    assert outcome["blocked_avoidance"]["1d"]["avg_avoided_loss"] == 0.03
    assert "state/signal_outcome.json" in outcome["source"]
    lifecycle = report["stock_lifecycle"]
    assert lifecycle["summary"]["status_counts"]["caution"] == 1
    lifecycle_item = lifecycle["items"][0]
    assert lifecycle_item["ticker"] == "SOXL"
    assert lifecycle_item["status"] == "caution"
    assert lifecycle_item["previous_status"] == "candidate"
    assert lifecycle["history"][0]["to_status"] == "caution"
    stability = report["signal_stability"]
    assert stability["summary"]["ticker_count"] == 1
    assert stability["items"][0]["ticker"] == "SOXL"
    assert stability["items"][0]["auto_candidate_excluded"] is True
    assert stability["items"][0]["windows"]["10d"]["transition_count"] >= 1


def test_dashboard_trader_lens_builds_reward_risk_and_provider_trust(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    report = build_dashboard_trader_lens(paths, run_id="run-001")

    assert report["summary"]["status"] == "data_error"
    assert report["summary"]["signals_reviewed"] == 1
    assert report["summary"]["average_reward_to_risk"] == 2.25
    row = report["signal_ladder"][0]
    assert row["ticker"] == "SOXL"
    assert row["risk_pct"] == 0.08
    assert row["reward_pct"] == 0.18
    assert row["reward_to_risk"] == 2.25
    assert row["review_priority"] == "data_error"
    assert any(item["status"] == "data_error" for item in report["provider_trust"])
    assert report["risk_concentration"][0]["code"] == "SECTOR_EXPOSURE_EXCEEDED"
    assert report["read_only"] is True


def test_dashboard_promotion_reports_criteria_and_shadow_history(tmp_path: Path):
    paths = _paths(tmp_path)
    atomic_write_json(paths.state_dir / "health.json", {"health_score": 90})
    shadow_dir = paths.signals_dir / "shadow"
    shadow_dir.mkdir(parents=True)
    atomic_write_json(
        shadow_dir / "2026-06-14.json",
        {
            "SOXL": {
                "signal": "entry",
                "signal_date": "2026-06-14",
                "action": "buy",
                "eligible": True,
                "shadow_status": "pending",
                "risk": {
                    "violation_details": [],
                    "data_trust": {"price": {"verified": True, "provider_disagreements": []}},
                },
            }
        },
    )

    report = build_dashboard_promotion(paths)

    assert report["summary"]["status"] == "blocked"
    assert report["summary"]["shadow_day_count"] == 1
    assert report["history"][0]["date"] == "2026-06-14"
    assert report["history"][0]["data_verified_count"] == 1
    assert {item["name"] for item in report["criteria"]} >= {"shadow_days", "health_score"}


def test_dashboard_settings_validation_blocks_loose_operational_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = _paths(tmp_path)
    monkeypatch.setattr("os.environ", {})
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    report = build_dashboard_settings_validation(paths, mode="shadow")

    assert report["summary"]["status"] == "blocked"
    assert any(item["key"] == "settings.mode_validation" for item in report["rules"])
    assert any(item["status"] == "blocked" for item in report["rules"])
    assert report["settings"]["tiingo_api_key"] is None


def test_dashboard_toss_status_is_read_only_and_masks_credentials(tmp_path: Path):
    paths = _paths(tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "toss_api_key": "client-id",
                "toss_secret_key": "client-secret",
                "toss_account": "1",
            }
        ),
        encoding="utf-8",
    )

    report = build_dashboard_toss_status(paths)

    assert report["status"] == "configured"
    assert report["read_only"] is True
    assert report["credentials"] == {
        "api_key": True,
        "secret_key": True,
        "account": True,
    }
    assert len(report["endpoints"]) == 17
    assert {row["method"] for row in report["endpoints"]} == {"GET"}
    assert all("client-secret" not in json.dumps(row) for row in report["endpoints"])


def test_dashboard_api_monitoring_exposes_toss_api_drift(tmp_path: Path):
    paths = _paths(tmp_path)
    atomic_write_json(
        paths.state_dir / "toss_api_drift.json",
        {
            "last_checked_at": datetime.now(UTC).isoformat(),
            "status": "drifted",
            "missing_endpoints": ["/api/v1/new-spec-route"],
            "extra_endpoints": ["/api/v1/local-only-route"],
            "fallback_snapshot_used": True,
            "fetch_error": "HTTP 503",
        },
    )
    atomic_write_json(paths.state_dir / "toss_openapi_snapshot.json", {"paths": {}})

    report = build_dashboard_api_monitoring(paths)
    drift = report["toss_api_drift"]

    assert report["summary"]["status"] == "warning"
    assert drift["status"] == "drifted"
    assert drift["status_label"] == "스펙 변경 감지"
    assert drift["missing_count"] == 1
    assert drift["extra_count"] == 1
    assert drift["fallback_snapshot_used"] is True
    assert drift["snapshot_available"] is True
    assert drift["next_action"] == "uv run jayu toss endpoints --sync"


def test_dashboard_toss_accounts_normalizes_and_masks_account_rows(tmp_path: Path):
    paths = _paths(tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps(
                {
                    "toss_api_key": "client-id",
                    "toss_secret_key": "client-secret",
                    "toss_account": "1",
                }
        ),
        encoding="utf-8",
    )
    fake = FakeTossDashboardClient()

    report = build_dashboard_toss_accounts(paths, client=fake)

    assert report["status"] == "success"
    assert report["read_only"] is True
    assert report["auto_select_account_seq"] == "1"
    assert report["permissions"] == {
        "read": True,
        "order": False,
        "automation": False,
        "reason": "Jayu dashboard currently exposes Toss GET endpoints only.",
    }
    account = report["accounts"][0]
    assert account["account_seq"] == "1"
    assert account["display_name"] == "Toss account 1"
    assert account["masked_account_no"] == "***-8901"
    assert account["account_type"] == "BROKERAGE"
    assert account["is_default"] is True
    assert account["permissions"]["order"] is False
    assert "12345678901" not in json.dumps(report)
    assert fake.calls == ["accounts"]


def test_dashboard_toss_portfolio_auto_selects_first_account_and_holdings(tmp_path: Path):
    paths = _paths(tmp_path)
    atomic_write_json(
        paths.state_dir / "account_attribution.json",
        {
            "status": "success",
            "summary": {
                "account_value_delta_krw": 40_000,
                "price_effect_krw": 20_000,
                "fx_effect_krw": 10_000,
                "holding_flow_krw": 60_000,
                "cash_delta_krw": -50_000,
            },
            "rows": [{"symbol": "AAPL", "value_delta_krw": 60_000}],
            "source": "account_attribution.json",
        },
    )
    fake = FakeTossDashboardClient()

    report = build_dashboard_toss_portfolio(paths, client=fake)

    assert report["status"] == "success"
    assert report["read_only"] is True
    assert report["auto_select_account_seq"] == "1"
    assert report["selected_account"]["account_seq"] == "1"
    assert report["summary"]["holding_count"] == 2
    assert report["summary"]["total_market_value"] == 1036000
    assert report["summary"]["total_cost_basis"] == 880000
    assert report["summary"]["unrealized_pnl"] == 156000
    assert report["summary"]["unrealized_pnl_pct"] == 0.177273
    assert report["summary"]["valuation_currency"] == "KRW"
    assert report["summary"]["cash_available"] == 0
    assert report["holdings"][0]["symbol"] == "005930"
    assert report["holdings"][0]["market_region"] == "KR"
    assert report["holdings"][0]["market_value_krw"] == 700000
    assert report["holdings"][0]["weight"] == 0.675676
    assert report["holdings"][0]["category"] == "STOCK"
    assert report["holdings"][0]["sector"] == "Technology"
    assert report["holdings"][0]["warning_count"] == 1
    assert "TOSS_WARNING" in report["holdings"][0]["situation_tags"]
    assert report["holdings"][0]["primary_portfolio_type"] in {"swing", "long_term"}
    assert report["holdings"][0]["primary_portfolio_type_label"] in {"중타", "장타"}
    assert "portfolio_mapping.json" in report["holdings"][0]["portfolio_type_source"]
    us_holding = next(item for item in report["holdings"] if item["symbol"] == "AAPL")
    assert us_holding["market_region"] == "US"
    assert us_holding["market_value_krw"] == 336000
    assert us_holding["fx_rate_to_krw"] == 1400
    assert us_holding["day_change_pct"] == 0.04
    assert "UP_3PCT_TODAY" in us_holding["situation_tags"]
    assert {"중타", "장타"}.issubset(set(us_holding["portfolio_type_labels"]))
    assert report["fx_rates"][1]["base_currency"] == "USD"
    assert report["fx_rates"][1]["rate"] == 1400
    assert report["fx_rates"][1]["fx_change_pct"] == 0.02
    fx_impact = report["fx_impact"]
    assert fx_impact["status"] == "success"
    assert fx_impact["summary"]["evaluated_count"] == 2
    assert fx_impact["summary"]["fx_effect_krw"] == pytest.approx(6334.8416)
    assert fx_impact["summary"]["total_day_pnl_krw"] == pytest.approx(12187.2115)
    aapl_impact = next(item for item in fx_impact["rows"] if item["symbol"] == "AAPL")
    assert aapl_impact["asset_return_pct"] == 0.04
    assert aapl_impact["fx_return_pct"] == 0.02
    assert aapl_impact["asset_effect_krw"] == pytest.approx(12669.6833)
    assert aapl_impact["fx_effect_krw"] == pytest.approx(6334.8416)
    assert aapl_impact["day_return_krw"] == pytest.approx(0.0608)
    assert report["account_attribution"]["status"] == "success"
    assert report["account_attribution"]["summary"]["account_value_delta_krw"] == 40_000
    assert {item["region"]: item["count"] for item in report["region_totals"]} == {"KR": 1, "US": 1}
    assert {item["currency"]: item["count"] for item in report["currency_totals"]} == {
        "KRW": 1,
        "USD": 1,
    }
    assert {item["category"]: item["count"] for item in report["category_totals"]} == {"STOCK": 2}
    assert {item["sector"]: item["count"] for item in report["sector_totals"]} == {
        "TECHNOLOGY": 2
    }
    portfolio_types = {item["label"]: item for item in report["portfolio_type_totals"]}
    assert set(portfolio_types) == {"단타", "중타", "장타", "배당"}
    assert portfolio_types["중타"]["count"] == 2
    assert portfolio_types["중타"]["market_value_krw"] == 1036000
    assert portfolio_types["중타"]["source"] == "portfolio_mapping.json · Toss holdings/stocks metadata"
    assert report["enrichment"]["stocks_covered"] == 2
    assert report["enrichment"]["prices_covered"] == 2
    assert report["enrichment"]["day_change_covered"] == 2
    assert report["enrichment"]["warning_hit_count"] == 1
    assert "holdings:1:None" in fake.calls
    assert any(
        call.startswith("exchange_rate:USD:KRW:") and not call.endswith(":None")
        for call in fake.calls
    )
    assert any(call.startswith("stocks:") for call in fake.calls)
    assert any(call.startswith("prices:") for call in fake.calls)
    assert "warnings:005930" in fake.calls
    assert not any(call.startswith("buying_power:") for call in fake.calls)
    assert not any(call.startswith("commissions:") for call in fake.calls)
    assert "12345678901" not in json.dumps(report)


def test_dashboard_toss_portfolio_type_override_wins_over_heuristics(tmp_path: Path):
    paths = _paths(tmp_path)
    override_dir = tmp_path / "configs"
    override_dir.mkdir()
    atomic_write_json(
        override_dir / "portfolio_type_overrides.json",
        {
            "tickers": {
                "AAPL": {
                    "portfolio_types": ["dividend"],
                    "reason": "사용자가 배당 점검 대상으로 지정",
                }
            }
        },
    )
    fake = FakeTossDashboardClient()

    report = build_dashboard_toss_portfolio(paths, client=fake)

    aapl = next(item for item in report["holdings"] if item["symbol"] == "AAPL")
    assert aapl["portfolio_types"] == ["dividend"]
    assert aapl["primary_portfolio_type"] == "dividend"
    assert aapl["portfolio_type_reason"] == "사용자가 배당 점검 대상으로 지정"
    assert aapl["portfolio_type_override"]["active"] is True
    assert aapl["portfolio_type_source"] == "portfolio_type_overrides.json"
    portfolio_types = {item["type"]: item for item in report["portfolio_type_totals"]}
    assert portfolio_types["dividend"]["count"] == 1
    assert "portfolio_type_overrides.json" in portfolio_types["dividend"]["source"]


def test_dashboard_toss_market_snapshot_uses_get_sections_without_network(tmp_path: Path):
    paths = _paths(tmp_path)
    fake = FakeTossDashboardClient()

    report = build_dashboard_toss_market_snapshot(
        paths,
        symbol="aapl",
        account="account-seq",
        include_account=True,
        client=fake,
    )

    assert report["symbol"] == "AAPL"
    assert report["read_only"] is True
    assert report["summary"]["status"] == "success"
    assert report["summary"]["successful_sections"] == 8
    assert set(report["sections"]) == {
        "price",
        "stock",
        "warnings",
        "price_limit",
        "orderbook",
        "trades",
        "candles_1d",
        "candles_1m",
    }
    assert report["account_sections"]["holdings"]["status"] == "success"
    assert report["account_sections"]["sellable_quantity"]["status"] == "success"
    assert "prices:AAPL" in fake.calls
    assert "holdings:account-seq:AAPL" in fake.calls


def test_dashboard_lists_runs_and_rejects_path_traversal(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)

    assert list_dashboard_runs(paths)[0]["run_id"] == "run-001"
    with pytest.raises(ValueError, match="unknown run_id"):
        build_dashboard_overview(paths, run_id="../state")


def test_dashboard_latest_prefers_completed_run_over_stale_running(tmp_path: Path):
    paths = _paths(tmp_path)
    completed_dir = paths.runs_dir / "run-completed"
    completed_dir.mkdir()
    atomic_write_json(
        completed_dir / "manifest.json",
        {
            "run_id": "run-completed",
            "command": "simulate",
            "execution_mode": "research",
            "status": "success",
            "started_at": "2026-06-21T07:24:00+09:00",
            "finished_at": "2026-06-21T07:24:36+09:00",
            "result": {"mode": "research"},
        },
    )
    running_dir = paths.runs_dir / "run-running"
    running_dir.mkdir()
    atomic_write_json(
        running_dir / "manifest.json",
        {
            "run_id": "run-running",
            "command": "simulate",
            "execution_mode": "research",
            "status": "running",
            "started_at": "2026-06-21T07:25:01+09:00",
            "finished_at": None,
            "result": {"mode": "research"},
        },
    )

    runs = list_dashboard_runs(paths)
    assert runs[0]["run_id"] == "run-running"
    assert runs[0]["is_complete"] is False
    assert runs[1]["is_complete"] is True

    report = build_dashboard_overview(paths, run_id="latest")
    assert report["run"]["run_id"] == "run-completed"


def test_dashboard_survivorship_exception_warning_is_not_blocker(tmp_path: Path):
    paths = _paths(tmp_path)
    run_dir = paths.runs_dir / "run-survivorship-review"
    run_dir.mkdir()
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": "run-survivorship-review",
            "command": "simulate",
            "execution_mode": "research",
            "status": "success",
            "started_at": "2026-06-21T07:24:00+09:00",
            "finished_at": "2026-06-21T07:24:36+09:00",
            "survivorship_audit": {
                "policy": "strict",
                "valid": True,
                "universe_source": "manual_current_universe",
                "universe_as_of": "2026-06-21",
                "includes_delisted": False,
                "exception_reason": "local research exception",
                "warnings": [
                    "SURVIVORSHIP_BIAS_RISK: manual_current_universe is not point-in-time membership"
                ],
            },
            "result": {"mode": "research"},
        },
    )
    atomic_write_json(
        run_dir / "safety_verdict.json",
        {
            "overall": "review",
            "reasons": [
                {
                    "component": "survivorship",
                    "code": "SURVIVORSHIP_BIAS_RISK",
                    "message": "SURVIVORSHIP_BIAS_RISK: manual_current_universe is not point-in-time membership",
                }
            ],
        },
    )

    overview = build_dashboard_overview(paths, run_id="latest")
    decision = build_dashboard_decision(paths, run_id="latest")

    assert overview["gates"]["survivorship"]["status"] == "pass"
    assert overview["decision"]["overall"] == "warning"
    assert overview["decision"]["top_reasons"][0]["severity"] == "warning"
    assert "SURVIVORSHIP_BIAS_RISK" not in overview["decision"]["headline"]
    assert decision["top_blockers"] == []


def test_dashboard_static_assets_are_bundled_without_order_actions():
    static_dir = dashboard_static_dir()
    assert (static_dir / "index.html").exists()
    assert (static_dir / "styles.css").exists()
    assert (static_dir / "app.js").exists()
    content = (static_dir / "app.js").read_text(encoding="utf-8")
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    css = (static_dir / "styles.css").read_text(encoding="utf-8")
    assert "Toss Account" in html
    assert "Toss Market" in html
    assert "Trader Lens" in html
    assert "account-summary" in html
    assert "READ_ONLY_GET" in content
    assert "READ_ONLY_ACCOUNT" in content
    assert "renderTossAccountDashboard" in content
    assert "renderTossRegionTabs" in content
    assert "renderReconciliationReview" in content
    assert "RECONCILIATION_ISSUE_LABELS" in content
    assert "renderExposureDonut" in content
    assert "renderSituationTags" in content
    assert "renderPortfolioTypeCards" in content
    assert "포트폴리오 타입별 요약" in content
    assert "투자 타입" in content
    assert "portfolio-type-grid" in css
    assert "portfolio-type-cell" in css
    assert "Category split" in content
    assert "Sector exposure" in content
    assert "renderDataSourceNote" in content
    assert "renderSourceLabel" in content
    assert "renderSourceCaption" in content
    assert "RUN_CONTEXT_OPTIONAL_PAGES" in content
    assert "function isCompletedRun" in content
    assert "state.runs.find(isCompletedRun)" in content
    assert "renderAutotradingReadiness" in content
    assert "자동매매 준비 점수" in content
    assert "renderPaperPromotionReport" in content
    assert "Paper Trading 승격 리포트" in content
    assert "renderMetricDictionaryStrip" in content
    assert "renderTodayBoard" in content
    assert "renderDecisionTimeline" in content
    assert "renderSessionReplay" in content
    assert "투자 세션 리플레이" in content
    assert "renderRecoveryGuide" in content
    assert "실패 복구 가이드" in content
    assert "renderSignalHistoryCards" in content
    assert "renderSignalOutcomePanel" in content
    assert "renderStockLifecycle" in content
    assert "종목 상태 머신" in content
    assert "renderSignalStabilityPanel" in content
    assert "신호 안정성 점수" in content
    assert "renderFxImpactPanel" in content
    assert "FX impact split" in content
    assert "FX day" in content
    assert "renderAccountAttributionPanel" in content
    assert "계좌 변화 원인" in content
    assert "state/signal_outcome.json" in content
    assert "종목별 판단 이력" in content
    assert "투자 판단 타임라인" in content
    assert "renderHubSignalConflictPanel" in content
    assert "renderHubDividendCashflow" in content
    assert "hubMetricSource" in content
    assert "hubSummaryCard" in content
    assert "배당 현금흐름 추정" in content
    assert "ACTION_QUEUE_STATUS_LABELS" in content
    assert "ACTION_TYPE_LABELS" in content
    assert "order_prepares" in content
    assert "renderPaperOrderContract" in content
    assert "renderAllocationPreview" in content
    assert "자금 배분 시뮬레이터" in content
    assert "renderOrderIntentQuality" in content
    assert "주문 의도 품질 점수" in content
    assert "renderTossApiDriftPanel" in content
    assert "Toss OpenAPI Drift Check" in content
    assert "운영 지표 쉬운 설명" in content
    assert "신호 지표 쉬운 설명" in content
    assert "오늘 확인할 항목" in content
    assert "위험 종목" in content
    assert "Paper 주문 의도 계약" in content
    assert "OrderIntent · OrderPlan · OrderApproval" in content
    assert "portfolio_type_overrides.json" in content
    assert "data-source-inline" in css
    assert "data-source-caption" in css
    assert "tv-news-context" in css
    assert "tv-related-symbol" in css
    assert "metric-help-panel" in css
    assert "metric-help-grid" in css
    assert "today-board" in css
    assert "today-card" in css
    assert "today-item-tags" in css
    assert "decision-timeline" in css
    assert "timeline-item" in css
    assert "session-replay-section" in css
    assert "session-replay-event" in css
    assert "recovery-guide-section" in css
    assert "recovery-guide-card" in css
    assert "signal-history-section" in css
    assert "signal-history-card" in css
    assert "stock-lifecycle-section" in css
    assert "stock-lifecycle-card" in css
    assert "signal-stability-section" in css
    assert "signal-stability-card" in css
    assert "signal-outcome-section" in css
    assert "signal-outcome-card" in css
    assert "fx-impact" in css
    assert "fx-impact-row" in css
    assert "account-attribution" in css
    assert "account-attribution-row" in css
    assert "hub-conflict-section" in css
    assert "hub-dividend-cashflow" in css
    assert "hub-price-source" in css
    assert "hub-source-inline" in css
    assert "reconciliation-issue-table" in css
    assert "order-quality-panel" in css
    assert "allocation-preview-section" in css
    assert "allocation-preview-card" in css
    assert "toss-drift-panel" in css
    assert "at-score-section" in css
    assert "at-paper-report" in css
    assert "Data sources:" in content
    assert "Toss warnings endpoint" in content
    assert "Toss status config" in content
    assert "generated markdown slips" in content
    assert "TradingView scanner popup-technicals" in content
    assert "TradingView 뉴스 플로우" in content
    assert "동반 언급 심볼" in content
    assert "주요 뉴스 맥락" in content
    assert "TradingView news-mediator relatedSymbols · derived role map" in content
    assert "Yahoo Finance OHLCV · derived RSI" in content
    assert "Yahoo Finance adjusted close series" in content
    assert "Yahoo Finance info.dividendYield" in content
    assert "Yahoo Finance OHLCV latest close · daily change" in content
    assert "portfolio_hub.py signal rules · Yahoo Finance derived indicators" in content
    assert "portfolio_hub.py portfolio type meta · portfolio_mapping.json portfolio_types" in content
    assert "Toss /api/v1/stocks/{symbol}/warnings" in content
    assert "runs/*/manifest.json" in content
    assert "runs/*/manifest.json · signals_risk.json" in content
    assert "manifest.json · data_sources.json · signals_risk.json" in content
    assert "TradingView 상세 스냅샷" in content
    assert "초단기 상세 진단" in content
    assert "성과 산출 가능한 실행 없음" in content
    assert "NAV 프리미엄" in content
    assert "renderTraderLens" in content
    assert "data-toss-account" in content
    assert "주문 실행" not in content
    assert "매수 실행" not in content
    assert "No run-local signals found" not in content
    assert "Promotion eligible" not in content
    assert "Settings Validation" not in content


def test_dashboard_static_app_js_parses_when_node_available():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")

    app_js = dashboard_static_dir() / "app.js"
    completed = subprocess.run(
        [node, "--check", str(app_js)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_dashboard_http_server_serves_static_page_and_api(tmp_path: Path):
    paths = _paths(tmp_path)
    _write_run(paths)
    server = create_dashboard_server(paths, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:  # noqa: S310
            html = response.read().decode("utf-8")
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/overview?run_id=run-001",
            timeout=5,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/decision?run_id=run-001",
            timeout=5,
        ) as response:
            decision = json.loads(response.read().decode("utf-8"))
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/runs/run-001/signals",
            timeout=5,
        ) as response:
            signals = json.loads(response.read().decode("utf-8"))
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/runs/run-001/trader-lens",
            timeout=5,
        ) as response:
            trader_lens = json.loads(response.read().decode("utf-8"))
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/promotion",
            timeout=5,
        ) as response:
            promotion = json.loads(response.read().decode("utf-8"))
        with urlopen(  # noqa: S310
            f"http://127.0.0.1:{port}/api/v1/settings/validation?mode=shadow",
            timeout=5,
        ) as response:
            validation = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert "<title>Jayu 운영 콘솔</title>" in html
    assert payload["run"]["run_id"] == "run-001"
    assert payload["decision"]["overall"] == "data_error"
    assert decision["recommended_next_action"]["page"] == "data-quality"
    assert signals["summary"]["blocked_count"] == 1
    assert trader_lens["summary"]["average_reward_to_risk"] == 2.25
    assert promotion["summary"]["status"] == "blocked"
    assert validation["mode"] == "shadow"


def test_dashboard_toss_reconciliation_missing_credentials(tmp_path: Path, monkeypatch):
    paths = _paths(tmp_path)
    monkeypatch.setattr("jayu.dashboard._load_dashboard_settings", lambda p: type("Settings", (), {
        "toss_api_key": None,
        "toss_secret_key": None,
        "toss_account": None,
    })())
    report = build_dashboard_toss_reconciliation(paths)
    assert report["status"] == "missing_credentials"



def test_dashboard_toss_order_plan(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.signals_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        paths.state_dir / "order_plan.json",
        {
            "orders": [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "estimated_quantity": 3,
                    "price": 120,
                    "arrival_mid": 120.1,
                    "final_price": 121,
                    "atr": 2.5,
                    "relative_spread": 0.001,
                }
            ]
        },
    )
    atomic_write_json(paths.state_dir / "stock_warning_gate.json", {"AAPL": {"has_warning": False}})
    atomic_write_json(paths.state_dir / "market_session_status.json", {"US": {"open": True}})
    atomic_write_json(
        paths.state_dir / "allocation_preview.json",
        {
            "status": "success",
            "summary": {"after_cash_krw": 100000, "cash_pct_after": 0.2},
            "holdings": [{"ticker": "AAPL", "after_weight": 0.1}],
            "source": "allocation_preview.json",
        },
    )
    atomic_write_json(paths.signal_file, {"AAPL": {"eligible": True, "signal": "buy_candidate"}})

    report = build_dashboard_toss_order_plan(paths)
    assert report["order_plan"]["orders"][0]["ticker"] == "AAPL"
    assert report["warnings_gate"]["AAPL"]["has_warning"] is False
    assert report["market_session"]["US"]["open"] is True
    assert report["today_signals"]["AAPL"]["eligible"] is True
    assert report["allocation_preview"]["status"] == "success"
    assert report["allocation_preview"]["summary"]["cash_pct_after"] == 0.2
    assert report["paper_order_contract"]["contract"]["intent"] == "OrderIntent"
    assert report["paper_order_contract"]["intents"][0]["ticker"] == "AAPL"
    assert report["paper_order_contract"]["approval"]["model"] == "OrderApproval"
    assert report["paper_order_contract"]["approval"]["live_order_enabled"] is False
    quality = report["paper_order_contract"]["intents"][0]["quality"]
    assert quality["score"] == 100
    assert quality["status"] == "success"
    assert {item["id"] for item in quality["checks"]} == {
        "structure",
        "signal_alignment",
        "warning_gate",
        "market_session",
        "execution_inputs",
        "approval_lock",
    }
    assert report["paper_order_contract"]["quality_summary"]["average_score"] == 100
    assert report["paper_order_contract"]["quality_summary"]["rejected_count"] == 0


def test_dashboard_toss_order_plan_reports_rejected_order_intents(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.signals_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        paths.state_dir / "order_plan.json",
        {
            "orders": [
                {"ticker": "MSFT", "action": "BUY", "estimated_quantity": 0, "price": 430},
                {"ticker": "TSLA", "action": "WATCH", "estimated_quantity": 1, "price": 400},
            ]
        },
    )
    atomic_write_json(paths.signal_file, {})

    report = build_dashboard_toss_order_plan(paths)
    contract = report["paper_order_contract"]

    assert contract["intents"] == []
    assert contract["quality_summary"]["status"] == "blocked"
    assert contract["quality_summary"]["rejected_count"] == 2
    assert contract["rejected_intents"][0]["ticker"] == "MSFT"
    assert "수량" in contract["rejected_intents"][0]["reasons"][0]
    assert contract["rejected_intents"][1]["ticker"] == "TSLA"


def test_dashboard_toss_reconciliation_with_account(tmp_path: Path, monkeypatch):
    paths = _paths(tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({
            "toss_api_key": "mock-key",
            "toss_secret_key": "mock-secret",
            "toss_account": "1",
        }),
        encoding="utf-8",
    )
    
    received_account = []
    def mock_reconcile(client, paths, *, account=None):
        received_account.append(account)
        return {"status": "success", "differences": [], "unmapped_tickers": []}
        
    monkeypatch.setattr("jayu.toss.reconcile_portfolio_with_toss", mock_reconcile)
    
    build_dashboard_toss_reconciliation(paths, account="custom-acc-seq")
    assert received_account == ["custom-acc-seq"]


def test_dashboard_toss_reconciliation_adds_mapping_and_policy_review(
    tmp_path: Path,
    monkeypatch,
):
    paths = _paths(tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "toss_api_key": "mock-key",
                "toss_secret_key": "mock-secret",
                "toss_account": "1",
            }
        ),
        encoding="utf-8",
    )
    paths.portfolio_file.write_text(
        "\n".join(
            [
                "name,ticker,quantity,market_value,currency",
                "Apple,AAPL,10,9000000,KRW",
                "Mystery,MYST,1,1000000,KRW",
            ]
        ),
        encoding="utf-8",
    )
    paths.portfolio_mapping_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        paths.portfolio_mapping_file,
        {
            "version": 1,
            "tickers": {
                "AAPL": {
                    "leverage_factor": 1.0,
                    "underlying_group": "apple",
                    "sector": "technology",
                    "factors": ["technology", "growth"],
                    "currency": "USD",
                }
            },
        },
    )

    def mock_reconcile(client, paths, *, account=None):
        return {
            "status": "synchronized",
            "differences": [],
            "unmapped_tickers": ["MYST"],
        }

    monkeypatch.setattr("jayu.toss.reconcile_portfolio_with_toss", mock_reconcile)

    report = build_dashboard_toss_reconciliation(paths, account="custom-acc-seq")

    assert report["status"] == "synchronized"
    assert report["review_status"] == "needs_review"
    assert report["review_summary"]["issue_count"] >= 4
    issue_types = {item["issue_type"] for item in report["mapping_issues"]}
    assert {"unmapped", "missing_type", "missing_sector", "overweight"} <= issue_types
    aapl_overweight = next(
        item
        for item in report["mapping_issues"]
        if item["ticker"] == "AAPL" and item["issue_type"] == "overweight"
    )
    assert aapl_overweight["observed"] == 0.9
    assert aapl_overweight["source"].startswith("portfolio.csv")
    assert report["position_policy_checks"][0]["source"] == "portfolio.csv · risk.portfolio_policy"
    assert "portfolio_type_overrides.json" in report["review_source"]
    assert report["portfolio_type_totals"]


def test_dashboard_toss_reconciliation_sync_endpoint_with_account(tmp_path: Path, monkeypatch):
    from urllib.request import Request
    paths = _paths(tmp_path)
    _write_run(paths)
    (tmp_path / "config.json").write_text(
        json.dumps({
            "toss_api_key": "mock-key",
            "toss_secret_key": "mock-secret",
            "toss_account": "1",
        }),
        encoding="utf-8",
    )
    
    received_account = []
    def mock_sync(client, paths, *, account=None):
        received_account.append(account)
        return {"status": "success", "message": "synced successfully"}
        
    monkeypatch.setattr("jayu.toss.sync_portfolio_from_toss", mock_sync)
    
    server = create_dashboard_server(paths, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    
    try:
        req = Request(
            f"http://127.0.0.1:{port}/api/v1/toss/reconciliation/sync",
            data=json.dumps({"account": "custom-sync-acc-seq"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urlopen(req, timeout=5) as response:
            res = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        
    assert res["status"] == "success"
    assert res["message"] == "synced successfully"
    assert received_account == ["custom-sync-acc-seq"]


def test_build_dashboard_analysis_structure(tmp_path, monkeypatch):
    """build_dashboard_analysis returns required top-level keys and nested data."""
    from jayu.dashboard import build_dashboard_analysis

    paths = _paths(tmp_path)

    # Mock yfinance.download to return a simple DataFrame
    import pandas as pd

    fake_dates = pd.date_range("2025-01-01", periods=5, freq="D")
    fake_df = pd.DataFrame(
        {
            "Open":  [100.0, 102.0, 101.0, 103.0, 105.0],
            "High":  [110.0, 112.0, 111.0, 113.0, 115.0],
            "Low":   [ 99.0, 101.0, 100.0, 102.0, 104.0],
            "Close": [105.0, 107.0, 106.0, 108.0, 110.0],
            "Volume": [1e6, 1.1e6, 0.9e6, 1.2e6, 1.3e6],
        },
        index=fake_dates,
    )
    monkeypatch.setattr("yfinance.download", lambda *a, **kw: fake_df)

    # Mock requests.get for FRED public CSV
    class FakeResp:
        status_code = 200
        text = "observation_date,FEDFUNDS\n2025-01-01,5.33\n2025-02-01,5.33\n2025-03-01,5.08\n"
        def raise_for_status(self): pass
    import requests as req_module
    monkeypatch.setattr(req_module, "get", lambda *a, **kw: FakeResp())

    result = build_dashboard_analysis(paths, ticker="SOXL", macro_series="FEDFUNDS", period="2y")

    # Required top-level keys
    assert "stock" in result
    assert "macro" in result
    assert "news" in result
    assert "toss" in result

    # Stock data
    stock = result["stock"]
    assert "ticker" in stock
    assert "latest_price" in stock
    assert "change_pct" in stock
    assert "fifty_two_week_high" in stock
    assert "fifty_two_week_low" in stock
    assert isinstance(stock["history"], list)
    assert len(stock["history"]) == 5
    row = stock["history"][0]
    assert "date" in row and "open" in row and "close" in row

    # Macro data
    macro = result["macro"]
    assert "series_id" in macro
    assert "name" in macro
    assert "latest_value" in macro
    assert isinstance(macro["history"], list)
    assert len(macro["history"]) == 3
    assert macro["history"][0]["value"] == 5.33

    # News is empty list (no API keys configured in test)
    assert isinstance(result["news"], list)

    # Toss portfolio is empty dict (no credentials)
    assert isinstance(result["toss"], dict)
    assert result["tradingview_details"]["status"] == "unavailable"
    assert result["tradingview_news"]["status"] == "unavailable"


def test_build_dashboard_analysis_bad_ticker(tmp_path, monkeypatch):
    """When yfinance returns empty data, stock.error is set."""
    from jayu.dashboard import build_dashboard_analysis
    import pandas as pd

    paths = _paths(tmp_path)
    monkeypatch.setattr("yfinance.download", lambda *a, **kw: pd.DataFrame())

    class FakeResp:
        status_code = 200
        text = "observation_date,FEDFUNDS\n2025-01-01,5.33\n"
        def raise_for_status(self): pass
    import requests as req_module
    monkeypatch.setattr(req_module, "get", lambda *a, **kw: FakeResp())

    result = build_dashboard_analysis(paths, ticker="BADTICKER", macro_series="FEDFUNDS", period="1y")
    assert "error" in result["stock"]


def test_build_analysis_portfolio_stats_explains_failed_runs(tmp_path):
    from jayu.dashboard import build_analysis_portfolio_stats

    paths = _paths(tmp_path)
    run_dir = paths.runs_dir / "run-failed"
    run_dir.mkdir()
    atomic_write_json(
        run_dir / "manifest.json",
        {
            "run_id": "run-failed",
            "command": "simulate",
            "status": "failed",
            "failure_code": "SURVIVORSHIP_GATE_FAILED",
            "error": "research requires universe.policy=strict",
            "started_at": "2026-06-20T00:00:00+00:00",
        },
    )

    result = build_analysis_portfolio_stats(paths)

    assert result["aggregate"]["run_count"] == 0
    assert result["diagnostics"]["checked_run_count"] == 1
    assert result["diagnostics"]["performance_run_count"] == 0
    assert result["diagnostics"]["status_counts"]["failed"] == 1
    assert result["diagnostics"]["skipped_runs"][0]["failure_code"] == "SURVIVORSHIP_GATE_FAILED"
    assert "trades.json" in result["diagnostics"]["empty_reason"]


def test_tradingview_technical_summary_maps_scores(monkeypatch):
    from jayu.dashboard import build_tradingview_technical_summary

    requested_fields = []

    class FakeResp:
        def __init__(self, fields: str):
            self.fields = fields

        def raise_for_status(self):
            return None

        def json(self):
            payload = {}
            for field in self.fields.split(","):
                base = field.split("|", 1)[0]
                if base == "Recommend.All":
                    payload[field] = 0.6
                elif base == "Recommend.MA":
                    payload[field] = 0.8
                elif base == "Recommend.Other":
                    payload[field] = 0.3
                elif base == "RSI":
                    payload[field] = 61.5
                elif base == "MACD.macd":
                    payload[field] = 1.25
                elif base == "MACD.signal":
                    payload[field] = 0.95
                elif base == "close":
                    payload[field] = 279.29
                else:
                    payload[field] = 1.0
            return payload

    def fake_get(url, *, params, headers, timeout):
        assert url == "https://scanner.tradingview.com/symbol"
        assert params["symbol"] == "AMEX:SOXL"
        assert headers["Referer"] == "https://www.tradingview.com/"
        assert timeout == 10
        requested_fields.append(params["fields"])
        return FakeResp(params["fields"])

    import requests as req_module

    monkeypatch.setattr(req_module, "get", fake_get)

    result = build_tradingview_technical_summary("SOXL")

    assert result["status"] == "ok"
    assert result["symbol"] == "AMEX:SOXL"
    assert result["consensus"]["signal"] == "strong_buy"
    assert result["consensus"]["action"] == "buy"
    assert result["consensus_score"] == 0.6
    assert len(result["timeframes"]) == 10
    assert [row["timeframe"] for row in result["timeframes"]] == [
        "1M",
        "1W",
        "1D",
        "240",
        "120",
        "60",
        "30",
        "15",
        "5",
        "1",
    ]
    assert any("Recommend.All|5" in fields for fields in requested_fields)
    assert any("Recommend.All|15" in fields for fields in requested_fields)
    assert any("Recommend.All|30" in fields for fields in requested_fields)
    assert any("Recommend.All|1W" in fields for fields in requested_fields)
    assert any("Recommend.All|1M" in fields for fields in requested_fields)
    assert result["timeframes"][0]["recommend_ma"] == 0.8
    assert result["timeframes"][0]["recommendation"]["label"] == "강한 매수"
    assert result["timeframes"][0]["oscillators"]["rsi"] == 61.5
    assert "moving_averages" in result["timeframes"][0]
    assert "nearest_pivots" in result["timeframes"][0]
    assert result["timeframes"][0]["rationale"]


def test_tradingview_technical_summary_keeps_partial_timeframes(monkeypatch):
    from jayu.dashboard import build_tradingview_technical_summary

    class FakeResp:
        def __init__(self, fields: str):
            self.fields = fields

        def raise_for_status(self):
            return None

        def json(self):
            return {
                field: (
                    0.2
                    if field.split("|", 1)[0].startswith("Recommend")
                    else 60.0
                )
                for field in self.fields.split(",")
            }

    def fake_get(url, *, params, headers, timeout):
        if any(field.endswith("|1") for field in params["fields"].split(",")):
            raise RuntimeError("minute scanner timeout")
        return FakeResp(params["fields"])

    import requests as req_module

    monkeypatch.setattr(req_module, "get", fake_get)

    result = build_tradingview_technical_summary("SOXL")

    assert result["status"] == "partial"
    assert result["consensus"]["label"] == "매수"
    assert len(result["timeframes"]) == 9
    assert result["errors"][0]["timeframe"] == "1"


def test_tradingview_symbol_details_normalizes_right_panel_fields(monkeypatch):
    from jayu.dashboard import build_tradingview_symbol_details

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "price_52_week_high": 286.1526,
                "price_52_week_low": 20.28,
                "sector": "Miscellaneous",
                "country": "United States",
                "market": "america",
                "Low.1M": 157.561,
                "High.1M": 286.1526,
                "Perf.W": 45.2366,
                "Perf.1M": 97.7414,
                "Perf.3M": 410.6784,
                "Perf.6M": 605.2778,
                "Perf.Y": 1186.1616,
                "Perf.YTD": 518.8566,
                "Recommend.All": 0.5576,
                "average_volume_10d_calc": 71218496,
                "average_volume_30d_calc": 61889092.4,
                "nav_discount_premium": -0.0432,
                "country_code_fund": "US",
                "iv": None,
                "underlying_symbol": None,
            }

    def fake_get(url, *, params, headers, timeout):
        assert url == "https://scanner.tradingview.com/symbol"
        assert params["symbol"] == "AMEX:SOXL"
        assert params["label-product"] == "right-details"
        assert headers["Referer"] == "https://www.tradingview.com/"
        assert "price_52_week_high" in params["fields"]
        assert timeout == 10
        return FakeResp()

    import requests as req_module

    monkeypatch.setattr(req_module, "get", fake_get)

    result = build_tradingview_symbol_details("SOXL")

    assert result["status"] == "ok"
    assert result["profile"]["sector"] == "Miscellaneous"
    assert result["quote"]["recommendation"]["signal"] == "strong_buy"
    assert result["quote"]["price_52_week_high"] == 286.1526
    assert result["performance"]["one_month"] == 97.7414
    assert result["volume"]["average_10d"] == 71218496
    assert result["fund"]["nav_discount_premium"] == -0.0432


def test_tradingview_news_flow_summarizes_related_symbols(monkeypatch):
    from jayu.dashboard import build_tradingview_news_flow

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "items": [
                    {
                        "id": "etfcom:1",
                        "title": "DRAM Powers Another Big Week of ETF Inflows",
                        "published": 1778533216,
                        "urgency": 2,
                        "storyPath": "/news/etfcom:1-dram-powers/",
                        "provider": {"id": "etfcom", "name": "etf.com", "url": "https://www.etf.com/"},
                        "relatedSymbols": [
                            {"symbol": "AMEX:SOXL", "logoid": "direxion"},
                            {"symbol": "NASDAQ:SMH", "logoid": "vaneck"},
                            {"symbol": "NASDAQ:QQQ", "logoid": "invesco"},
                        ],
                    },
                    {
                        "id": "etfcom:2",
                        "title": "US Stocks Reclaim the Lead",
                        "published": 1777899600,
                        "urgency": 2,
                        "storyPath": "/news/etfcom:2-us-stocks/",
                        "provider": {"id": "etfcom", "name": "etf.com"},
                        "relatedSymbols": [
                            {"symbol": "AMEX:SOXL", "logoid": "direxion"},
                            {"symbol": "NASDAQ:SMH", "logoid": "vaneck"},
                            {"symbol": "AMEX:VOO", "logoid": "vanguard"},
                        ],
                    },
                ]
            }

    def fake_get(url, *, params, headers, timeout):
        assert url == "https://news-mediator.tradingview.com/public/news-flow/v2/news"
        assert ("filter", "lang:en") in params
        assert ("filter", "symbol:AMEX:SOXL") in params
        assert ("client", "landing") in params
        assert headers["Referer"] == "https://www.tradingview.com/"
        assert timeout == 10
        return FakeResp()

    import requests as req_module

    monkeypatch.setattr(req_module, "get", fake_get)

    result = build_tradingview_news_flow("SOXL")

    assert result["status"] == "ok"
    assert result["source"] == "TradingView news-mediator"
    assert result["item_count"] == 2
    assert result["items"][0]["url"] == "https://www.tradingview.com/news/etfcom:1-dram-powers/"
    assert result["items"][0]["related_symbols"][0]["is_primary"] is True
    assert result["primary_mentions"]["count"] == 2
    assert result["related_symbols"][0]["symbol"] == "NASDAQ:SMH"
    assert result["related_symbols"][0]["count"] == 2
    assert result["related_symbols"][0]["role"]["id"] == "semiconductor"
    assert result["related_symbols"][1]["role"]["id"] == "broad_market"
    assert result["news_context"]["dominant_theme"]["id"] == "semiconductor"
    assert result["news_context"]["theme_counts"][0]["mention_count"] == 2
    assert result["news_context"]["primary_mention_rate"] == 1.0
    assert any("직접 섹터" in note["text"] for note in result["news_context"]["context_notes"])
    assert result["provider_counts"]["etf.com"] == 2
