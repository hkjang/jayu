from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jayu.decision_inbox import build_decision_inbox, build_unified_quality_snapshot
from jayu.investment_decision_graph import build_investment_decision_graph
from jayu.toss_freshness_ledger import build_toss_freshness_ledger
from jayu.unified_quality_policy import evaluate_unified_quality_policy


def test_unified_quality_policy_normalizes_mixed_domain_reports() -> None:
    report = evaluate_unified_quality_policy(
        {
            "price": {"domain": "market", "status": "success", "score": 95, "source": "provider"},
            "dividend": {"domain": "dividend", "decision": "review", "trust_score": 72, "source": "gate"},
            "orders": {"domain": "toss", "status": "failed", "score": 42, "source": "contract"},
        }
    )

    assert report["decision"] == "block"
    assert report["allowed"] is False
    assert report["summary"]["block_count"] == 1
    assert report["summary"]["review_count"] == 1
    assert {item["domain"] for item in report["items"]} == {"market", "dividend", "toss"}


def test_toss_freshness_ledger_scores_state_files(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    now = datetime(2026, 6, 28, 9, 0, tzinfo=UTC)
    snapshot = {
        "generated_at": (now - timedelta(hours=2)).isoformat(),
        "accounts": {"result": {"accounts": [{"accountSeq": "1"}]}},
        "holdings": {"result": {"holdings": [{"symbol": "AAPL", "holdingQuantity": "1", "currency": "USD"}]}},
        "commissions": {"result": {"commissionRate": "0.001"}},
        "exchange_rate": {"result": {"baseCurrency": "USD", "quoteCurrency": "KRW", "rate": "1400"}},
        "errors": {},
    }
    (state_dir / "toss_account_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    orders_path = state_dir / "toss_orders.json"
    orders_path.write_text(json.dumps([_order("o1", "AAPL", "BUY", 1, 100)]), encoding="utf-8")
    old = (now - timedelta(hours=96)).timestamp()
    os.utime(orders_path, (old, old))
    (state_dir / "toss_fx_cache.json").write_text(
        json.dumps({"timestamp": (now - timedelta(hours=1)).timestamp(), "usd_krw": 1400}),
        encoding="utf-8",
    )

    ledger = build_toss_freshness_ledger(tmp_path, now=now)
    by_endpoint = {row["endpoint"]: row for row in ledger["endpoints"]}

    assert by_endpoint["holdings"]["decision"] == "pass"
    assert by_endpoint["orders"]["decision"] == "block"
    assert by_endpoint["orders"]["cache_status"] == "stale"
    assert ledger["summary"]["critical_block_count"] >= 1
    assert (state_dir / "toss_freshness_ledger.json").exists()


def test_investment_decision_graph_blocks_loss_pattern_symbol(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "toss_orders.json").write_text(
        json.dumps(
            [
                _order("b1", "SOXL", "BUY", 10, 100, "2026-01-02T09:30:00+09:00"),
                _order("b2", "SOXL", "BUY", 5, 90, "2026-01-05T09:30:00+09:00"),
                _order("s1", "SOXL", "SELL", 15, 80, "2026-01-10T09:30:00+09:00"),
                _order("b3", "AAPL", "BUY", 1, 100, "2026-02-01T09:30:00+09:00"),
                _order("s2", "AAPL", "SELL", 1, 130, "2026-03-01T09:30:00+09:00"),
            ]
        ),
        encoding="utf-8",
    )
    signals = [{"ticker": "SOXL", "action": "BUY", "score": 0.8, "status": "success"}]
    dividend_dashboard = {
        "holdings_table": [{"symbol": "SOXL", "trust_score": 90, "decision": "pass", "source": "fixture"}]
    }

    graph = build_investment_decision_graph(
        tmp_path,
        signals_payload=signals,
        dividend_dashboard=dividend_dashboard,
        data_trust={"gate": {"status": "success", "decision": "pass", "overall_score": 95, "allowed": True}},
        toss_freshness={"status": "success", "decision": "pass", "allowed": True, "summary": {"average_trust_score": 95}},
    )

    soxl = next(row for row in graph["graphs"] if row["symbol"] == "SOXL")
    assert graph["status"] == "blocked"
    assert soxl["decision"] == "block"
    assert "averaging_down_loss" in soxl["reason_codes"]
    assert any(node["id"] == "historical_risk" and node["decision"] == "block" for node in soxl["nodes"])


def test_decision_inbox_collects_cross_menu_review_items(tmp_path: Path) -> None:
    data_trust = {
        "status": "blocked",
        "gate": {
            "status": "blocked",
            "decision": "block",
            "allowed": False,
            "blocking": [{"dataset": "toss_orders", "decision": "block", "reasons": ["duplicate_order_id"]}],
        },
        "source": "fixture data trust",
    }
    toss_freshness = {
        "status": "blocked",
        "decision": "block",
        "allowed": False,
        "summary": {"average_trust_score": 45},
        "endpoints": [
            {
                "endpoint": "orders",
                "label": "Toss order history",
                "decision": "block",
                "status": "blocked",
                "cache_status": "stale",
                "age_hours": 96,
                "reasons": ["source_file_stale"],
                "source": "state/toss_orders.json",
            }
        ],
    }
    dividend_dashboard = {
        "alerts": [{"type": "ex_date_proximity", "symbol": "SCHD", "message": "SCHD ex-date is near."}],
        "data_quality_summary": {
            "blocked_count": 1,
            "review_count": 0,
            "average_trust_score": 55,
            "unmapped_items": [{"symbol": "KR123", "reason": "mapping missing"}],
        },
        "autotrading_guard": {"status": "pass", "reasons": []},
    }
    order_history_summary = {
        "status": "failed",
        "risk_gate": {
            "blocked_signals": [
                {"ticker": "SOXL", "message": "SOXL blocked by loss pattern.", "source": "historical gate"}
            ]
        },
        "autotrade_guard": {
            "rules": [{"symbol": "SOXL", "rule": "repeated_loss_symbol", "action": "block_auto_order"}]
        },
    }
    decision_graph = {
        "graphs": [
            {
                "symbol": "SOXL",
                "decision": "block",
                "headline": "SOXL blocked.",
                "source": "graph",
            }
        ]
    }

    inbox = build_decision_inbox(
        tmp_path,
        data_trust=data_trust,
        toss_freshness=toss_freshness,
        dividend_dashboard=dividend_dashboard,
        order_history_summary=order_history_summary,
        decision_graph=decision_graph,
    )
    snapshot = build_unified_quality_snapshot(
        data_trust=data_trust,
        toss_freshness=toss_freshness,
        dividend_dashboard=dividend_dashboard,
        order_history_summary=order_history_summary,
    )

    assert inbox["status"] == "blocked"
    assert inbox["summary"]["blocked_count"] >= 4
    assert any(item["menu"] == "Autotrading" for item in inbox["items"])
    assert any(item["symbol"] == "SCHD" for item in inbox["items"])
    assert snapshot["decision"] == "block"


def _order(
    order_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    ordered_at: str = "2026-03-28T09:30:00+09:00",
) -> dict[str, object]:
    return {
        "orderId": order_id,
        "symbol": symbol,
        "side": side,
        "status": "FILLED",
        "price": str(price),
        "quantity": str(quantity),
        "currency": "USD",
        "orderedAt": ordered_at,
        "execution": {
            "filledQuantity": str(quantity),
            "averageFilledPrice": str(price),
            "filledAmount": str(quantity * price),
            "commission": "1",
            "tax": "0",
        },
    }
