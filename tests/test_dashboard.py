import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import pytest

from jayu.dashboard import (
    build_dashboard_decision,
    build_dashboard_data_quality,
    build_dashboard_overview,
    build_dashboard_promotion,
    build_dashboard_risk,
    build_dashboard_settings_validation,
    build_dashboard_signals,
    build_dashboard_trader_lens,
    build_dashboard_toss_accounts,
    build_dashboard_toss_market_snapshot,
    build_dashboard_toss_portfolio,
    build_dashboard_toss_status,
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
    assert report["decision"]["top_reasons"][0]["code"] == "DATA_DISAGREEMENT"
    assert report["recommended_actions"][0]["page"] == "data-quality"


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
    atomic_write_json(
        run_dir / "signal_publication.json",
        {
            "status": "blocked",
            "run_id": "run-001",
            "signal_date": "2026-06-14",
            "failure_code": "SAFETY_VERDICT_BLOCKED",
        },
    )

    report = build_dashboard_signals(paths, run_id="run-001")

    assert report["summary"]["blocked_count"] == 1
    assert report["publication"]["status"] == "blocked"
    row = report["rows"][0]
    assert row["ticker"] == "SOXL"
    assert row["entry_price"] == 100.0
    assert row["stop_price"] == 92.0
    assert row["target_price"] == 118.0
    assert row["failed"][0]["code"] == "SECTOR_EXPOSURE_EXCEEDED"


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


def test_dashboard_settings_validation_blocks_loose_operational_mode(tmp_path: Path):
    paths = _paths(tmp_path)

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
    us_holding = next(item for item in report["holdings"] if item["symbol"] == "AAPL")
    assert us_holding["market_region"] == "US"
    assert us_holding["market_value_krw"] == 336000
    assert us_holding["fx_rate_to_krw"] == 1400
    assert us_holding["day_change_pct"] == 0.04
    assert "UP_3PCT_TODAY" in us_holding["situation_tags"]
    assert report["fx_rates"][1]["base_currency"] == "USD"
    assert report["fx_rates"][1]["rate"] == 1400
    assert {item["region"]: item["count"] for item in report["region_totals"]} == {"KR": 1, "US": 1}
    assert {item["currency"]: item["count"] for item in report["currency_totals"]} == {
        "KRW": 1,
        "USD": 1,
    }
    assert {item["category"]: item["count"] for item in report["category_totals"]} == {"STOCK": 2}
    assert {item["sector"]: item["count"] for item in report["sector_totals"]} == {
        "TECHNOLOGY": 2
    }
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


def test_dashboard_static_assets_are_bundled_without_order_actions():
    static_dir = dashboard_static_dir()
    assert (static_dir / "index.html").exists()
    assert (static_dir / "styles.css").exists()
    assert (static_dir / "app.js").exists()
    content = (static_dir / "app.js").read_text(encoding="utf-8")
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    assert "Toss Account" in html
    assert "Toss Market" in html
    assert "Trader Lens" in html
    assert "account-summary" in html
    assert "READ_ONLY_GET" in content
    assert "READ_ONLY_ACCOUNT" in content
    assert "renderTossAccountDashboard" in content
    assert "renderTossRegionTabs" in content
    assert "renderExposureDonut" in content
    assert "renderSituationTags" in content
    assert "Category split" in content
    assert "Sector exposure" in content
    assert "renderTraderLens" in content
    assert "data-toss-account" in content
    assert "주문 실행" not in content
    assert "매수 실행" not in content
    assert "No run-local signals found" not in content
    assert "Promotion eligible" not in content
    assert "Settings Validation" not in content


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
