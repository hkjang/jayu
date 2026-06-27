from __future__ import annotations

from typing import Any


def build_autotrade_guard_from_history(
    feature_store: dict[str, Any],
    patterns_report: dict[str, Any] | None = None,
    memory_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = []
    for pattern in (patterns_report or {}).get("patterns") or []:
        sym = str(pattern.get("symbol") or "").upper()
        code = str(pattern.get("code") or "")
        if not sym:
            continue
        if code in {"repeated_loss_symbol", "quick_loss_reentry", "averaging_down_loss", "leveraged_loss"}:
            rules.append(
                {
                    "symbol": sym,
                    "rule": code,
                    "action": "block_auto_order",
                    "cooldown_days": 14 if code != "quick_loss_reentry" else 21,
                    "order_size_multiplier": 0.0,
                    "message": pattern.get("message"),
                    "source": "trade_pattern_miner.py - autotrade_guard_from_history.py",
                }
            )
    for row in (memory_report or {}).get("symbol_scores") or []:
        sym = str(row.get("symbol") or "").upper()
        score = float(row.get("score") or 0.0)
        if not sym:
            continue
        if score < 45 and not _has_rule(rules, sym, "low_trade_memory_score"):
            rules.append(
                {
                    "symbol": sym,
                    "rule": "low_trade_memory_score",
                    "action": "block_auto_order",
                    "cooldown_days": 14,
                    "order_size_multiplier": 0.0,
                    "message": f"{sym} trade memory score is {score:.1f}, below the auto-trading threshold.",
                    "source": "trade_memory_score.py - autotrade_guard_from_history.py",
                }
            )
        elif score < 65 and not _has_rule(rules, sym, "weak_trade_memory_score"):
            rules.append(
                {
                    "symbol": sym,
                    "rule": "weak_trade_memory_score",
                    "action": "reduce_order_size",
                    "cooldown_days": 0,
                    "order_size_multiplier": 0.5,
                    "message": f"{sym} needs half-size review because trade memory score is {score:.1f}.",
                    "source": "trade_memory_score.py - autotrade_guard_from_history.py",
                }
            )
    block_count = sum(1 for item in rules if item.get("action") == "block_auto_order")
    reduce_count = sum(1 for item in rules if item.get("action") == "reduce_order_size")
    return {
        "status": "failed" if block_count else "warning" if reduce_count else "success" if feature_store.get("orders") else "not_evaluated",
        "summary": {
            "rule_count": len(rules),
            "block_rule_count": block_count,
            "reduce_rule_count": reduce_count,
        },
        "rules": sorted(rules, key=lambda item: (item.get("symbol") or "", item.get("rule") or "")),
        "source": "Toss order history patterns - autotrade_guard_from_history.py",
    }


def _has_rule(rules: list[dict[str, Any]], symbol: str, rule: str) -> bool:
    return any(item.get("symbol") == symbol and item.get("rule") == rule for item in rules)
