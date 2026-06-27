from __future__ import annotations

from jayu.autotrade_guard_from_history import build_autotrade_guard_from_history
from jayu.historical_trade_risk_gate import evaluate_historical_trade_risk_gate
from jayu.order_history_summary import build_order_history_summary
from jayu.toss_order_feature_store import build_toss_order_feature_store
from jayu.trade_journal_from_orders import build_trade_journal_from_orders
from jayu.trade_memory_score import build_trade_memory_score
from jayu.trade_pattern_miner import mine_trade_patterns


def _orders() -> list[dict[str, object]]:
    return [
        _order("b1", "SOXL", "BUY", "2026-01-02T09:30:00+09:00", 10, 100, "USD", commission=1),
        _order("b2", "SOXL", "BUY", "2026-01-05T09:30:00+09:00", 5, 90, "USD", commission=1),
        _order("s1", "SOXL", "SELL", "2026-01-10T09:30:00+09:00", 15, 80, "USD", commission=1),
        _order("b3", "SOXL", "BUY", "2026-01-12T09:30:00+09:00", 4, 82, "USD", commission=1),
        _order("b4", "AAPL", "BUY", "2026-02-01T09:30:00+09:00", 10, 100, "USD", commission=1),
        _order("s2", "AAPL", "SELL", "2026-03-05T09:30:00+09:00", 10, 130, "USD", commission=1),
        _order("b5", "TQQQ", "BUY", "2026-04-01T09:30:00+09:00", 3, 50, "USD", commission=1),
        _order("s3", "TQQQ", "SELL", "2026-04-04T09:30:00+09:00", 3, 45, "USD", commission=1),
    ]


def _order(
    order_id: str,
    symbol: str,
    side: str,
    ordered_at: str,
    quantity: float,
    price: float,
    currency: str,
    *,
    commission: float,
) -> dict[str, object]:
    return {
        "orderId": order_id,
        "symbol": symbol,
        "side": side,
        "status": "FILLED",
        "price": str(price),
        "quantity": str(quantity),
        "currency": currency,
        "orderedAt": ordered_at,
        "execution": {
            "filledQuantity": str(quantity),
            "averageFilledPrice": str(price),
            "filledAmount": str(quantity * price),
            "commission": str(commission),
            "tax": "0",
        },
    }


def test_order_feature_store_builds_symbol_period_and_trade_round_features() -> None:
    store = build_toss_order_feature_store(
        _orders(),
        portfolio_mapping={"tickers": {"SOXL": {"portfolio_types": ["short_term"]}}},
    )

    assert store["status"] == "success"
    assert store["summary"]["trade_count"] == 8
    assert store["summary"]["round_count"] >= 4
    soxl = next(row for row in store["by_symbol"] if row["symbol"] == "SOXL")
    assert soxl["portfolio_type"] == "short_term"
    assert soxl["realized_pnl_krw"] < 0
    assert soxl["loss_count"] >= 2


def test_trade_patterns_memory_gate_and_guard_use_historical_losses() -> None:
    store = build_toss_order_feature_store(_orders())
    patterns = mine_trade_patterns(store)
    memory = build_trade_memory_score(store, patterns)
    risk_gate = evaluate_historical_trade_risk_gate(
        [{"ticker": "SOXL", "action": "BUY"}, {"ticker": "AAPL", "action": "BUY"}],
        store,
        patterns,
        memory,
    )
    guard = build_autotrade_guard_from_history(store, patterns, memory)
    journal = build_trade_journal_from_orders(store, patterns)

    pattern_codes = {item["code"] for item in patterns["patterns"] if item["symbol"] == "SOXL"}
    assert {"repeated_loss_symbol", "quick_loss_reentry", "averaging_down_loss"} <= pattern_codes
    scores = {item["symbol"]: item["score"] for item in memory["symbol_scores"]}
    assert scores["SOXL"] < scores["AAPL"]
    assert risk_gate["status"] == "blocked"
    assert any(item["ticker"] == "SOXL" for item in risk_gate["blocked_signals"])
    assert any(item["symbol"] == "SOXL" and item["action"] == "block_auto_order" for item in guard["rules"])
    assert any(item["label"] == "loser" for item in journal["entries"])


def test_order_history_summary_rolls_up_all_order_memory_outputs() -> None:
    summary = build_order_history_summary(
        _orders(),
        signals_payload=[{"ticker": "SOXL", "action": "BUY"}],
        portfolio_mapping={"tickers": {"SOXL": {"portfolio_types": ["short_term"]}}},
    )

    assert summary["status"] == "failed"
    assert summary["summary"]["pattern_count"] >= 3
    assert summary["summary"]["risk_block_count"] == 1
    assert summary["feature_store"]["summary"]["round_count"] >= 4
    assert summary["autotrade_guard"]["summary"]["block_rule_count"] >= 1
