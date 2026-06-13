from __future__ import annotations

import html
import json
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .costs import breakeven_transaction_cost, cost_sensitivity
from .io import atomic_write_json, read_json, stable_hash
from .performance import cost_bridge
from .stat_tests import probabilistic_sharpe_ratio


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _trade_return(trade: Mapping[str, Any]) -> float:
    if isinstance(trade.get("ret"), (int, float)):
        return float(trade["ret"])
    if isinstance(trade.get("net_return_pct"), (int, float)):
        return float(trade["net_return_pct"]) / 100
    if isinstance(trade.get("gross_return_pct"), (int, float)):
        return float(trade["gross_return_pct"]) / 100
    return 0.0


def equity_curve_svg(
    records: Sequence[Mapping[str, Any]],
    *,
    width: int = 720,
    height: int = 260,
) -> str:
    values = [
        float(record["equity"])
        for record in records
        if isinstance(record.get("equity"), (int, float))
    ]
    if len(values) < 2:
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            'xmlns="http://www.w3.org/2000/svg">'
            '<text x="24" y="40" fill="#64748b">not enough equity data</text></svg>'
        )
    min_value = min(values)
    max_value = max(values)
    span = max(max_value - min_value, 1.0)
    left = 44
    top = 20
    plot_width = width - 68
    plot_height = height - 58
    points = []
    for index, value in enumerate(values):
        x = left + (plot_width * index / (len(values) - 1))
        y = top + plot_height - ((value - min_value) / span * plot_height)
        points.append(f"{x:.1f},{y:.1f}")
    first_label = html.escape(str(records[0].get("date", "")))
    last_label = html.escape(str(records[-1].get("date", "")))
    return "\n".join(
        [
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            'xmlns="http://www.w3.org/2000/svg" role="img">',
            f'<rect width="{width}" height="{height}" fill="#f8fafc"/>',
            f'<line x1="{left}" y1="{top + plot_height}" '
            f'x2="{left + plot_width}" y2="{top + plot_height}" stroke="#cbd5e1"/>',
            f'<polyline fill="none" stroke="#2563eb" stroke-width="2.5" '
            f'points="{" ".join(points)}"/>',
            f'<text x="{left}" y="{height - 14}" fill="#64748b" font-size="12">{first_label}</text>',
            f'<text x="{width - 160}" y="{height - 14}" fill="#64748b" '
            f'font-size="12">{last_label}</text>',
            f'<text x="{left}" y="16" fill="#334155" font-size="12">max {max_value:,.0f}</text>',
            f'<text x="{left}" y="{top + plot_height - 4}" fill="#334155" '
            f'font-size="12">min {min_value:,.0f}</text>',
            "</svg>",
        ]
    )


def _iter_strategy_results(node: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(node, Mapping):
        return
    if isinstance(node.get("params"), Mapping):
        yield node
        return
    for value in node.values():
        yield from _iter_strategy_results(value)


def parameter_importance(results: Mapping[str, Any]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for result in _iter_strategy_results(results):
        metrics = result.get("val_metrics") or result.get("metrics") or {}
        fitness = metrics.get("fitness") if isinstance(metrics, Mapping) else None
        params = result.get("params")
        if not isinstance(fitness, (int, float)) or not isinstance(params, Mapping):
            continue
        for name, value in params.items():
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            buckets[str(name)][key].append(float(fitness))
    rows: list[dict[str, Any]] = []
    for name, values in buckets.items():
        averages = {value: sum(scores) / len(scores) for value, scores in values.items() if scores}
        if not averages:
            continue
        rows.append(
            {
                "parameter": name,
                "importance": max(averages.values()) - min(averages.values()),
                "best_value": max(averages, key=lambda key: averages[key]),
                "worst_value": min(averages, key=lambda key: averages[key]),
                "sample_count": sum(len(scores) for scores in values.values()),
            }
        )
    return sorted(rows, key=lambda row: row["importance"], reverse=True)


def strategy_attribution(trades: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        mode = str(trade.get("strategy_mode") or trade.get("mode") or "unknown")
        grouped[mode].append(_trade_return(trade))
    rows: list[dict[str, Any]] = []
    for mode, returns in grouped.items():
        if not returns:
            continue
        rows.append(
            {
                "strategy_mode": mode,
                "trade_count": len(returns),
                "total_return": sum(returns),
                "avg_return": sum(returns) / len(returns),
                "win_rate": sum(1 for value in returns if value > 0) / len(returns),
            }
        )
    return sorted(rows, key=lambda row: row["total_return"], reverse=True)


def trade_cost_stats(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Net + overfitting-aware summary for one strategy's trade log.

    Combines the gross→net cost bridge, breakeven round-trip cost, cost-survival
    sweep, and the Probabilistic Sharpe Ratio of net per-trade returns (vs a zero
    benchmark). PSR is only computed when at least three trades carry an explicit
    ``net_return_pct``.
    """
    trade_list: list[dict[str, Any]] = [dict(trade) for trade in trades]
    bridge = cost_bridge(trade_list)
    breakeven = breakeven_transaction_cost(trade_list)
    sensitivity = cost_sensitivity(trade_list)
    net_returns = [
        float(trade["net_return_pct"]) / 100.0
        for trade in trade_list
        if isinstance(trade.get("net_return_pct"), (int, float))
    ]
    psr = probabilistic_sharpe_ratio(net_returns, 0.0) if len(net_returns) >= 3 else None
    return {
        "trades": bridge["trades"],
        "cost_drag_pct_of_gross": bridge["cost_drag_pct_of_gross"],
        "avg_net_return_pct": bridge["avg_net_return_pct"],
        "breakeven_round_trip_bps": breakeven["breakeven_round_trip_bps"],
        "max_survivable_bps": sensitivity.get("max_survivable_bps"),
        "psr_vs_zero": round(psr, 4) if psr is not None else None,
    }


def risk_decision_rows(signals: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten per-signal risk decisions for display (criterion #12, report side).

    Prefers structured ``violation_details`` codes; falls back to the legacy
    free-text ``violations`` when only those are present.
    """
    rows: list[dict[str, Any]] = []
    for ticker, signal in signals.items():
        if not isinstance(signal, Mapping):
            continue
        risk = signal.get("risk")
        if not isinstance(risk, Mapping):
            continue
        details = risk.get("violation_details")
        if isinstance(details, list) and details:
            reasons = [str(item.get("code")) for item in details if isinstance(item, Mapping)]
        else:
            legacy = risk.get("violations")
            reasons = [str(item) for item in legacy] if isinstance(legacy, list) else []
        warnings = risk.get("warnings")
        warning_codes = (
            [str(item.get("code")) for item in warnings if isinstance(item, Mapping)]
            if isinstance(warnings, list)
            else []
        )
        rows.append(
            {
                "ticker": str(ticker),
                "action": signal.get("action"),
                "eligible": signal.get("eligible"),
                "requested_pct": risk.get("requested_position_pct"),
                "approved_pct": signal.get(
                    "approved_position_pct", risk.get("approved_position_pct")
                ),
                "resized": risk.get("resized"),
                "mapped": risk.get("mapped"),
                "reasons": reasons,
                "warnings": warning_codes,
            }
        )
    return rows


def train_oos_decay(results: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per-strategy train→out-of-sample performance decay from a run's results.

    For each ticker/regime, compares the training ``metrics`` against the
    walk-forward ``val_metrics`` already stored in ``result.json``. ``retention``
    is OOS/train; ``degraded`` flags an OOS edge that turned non-positive or
    retained below half — a fingerprint of overfitting (roadmap #118, #120).
    """
    rows: list[dict[str, Any]] = []
    for ticker, regimes in results.items():
        if not isinstance(regimes, Mapping):
            continue
        for regime, record in regimes.items():
            if not isinstance(record, Mapping):
                continue
            train = record.get("metrics")
            oos = record.get("val_metrics")
            if not isinstance(train, Mapping) or not isinstance(oos, Mapping):
                continue

            def retention(key: str, train: Any = train, oos: Any = oos) -> float | None:
                trained = train.get(key)
                out = oos.get(key)
                if (
                    isinstance(trained, (int, float))
                    and isinstance(out, (int, float))
                    and trained != 0
                ):
                    return round(float(out) / float(trained), 4)
                return None

            oos_fitness = oos.get("fitness")
            fitness_retention = retention("fitness")
            degraded = (isinstance(oos_fitness, (int, float)) and oos_fitness <= 0) or (
                fitness_retention is not None and fitness_retention < 0.5
            )
            rows.append(
                {
                    "ticker": str(ticker),
                    "regime": str(regime),
                    "train_fitness": train.get("fitness"),
                    "oos_fitness": oos_fitness,
                    "fitness_retention": fitness_retention,
                    "train_return": train.get("total_return"),
                    "oos_return": oos.get("total_return"),
                    "return_retention": retention("total_return"),
                    "degraded": bool(degraded),
                }
            )
    return rows


def post_signal_performance(
    signals: Mapping[str, Mapping[str, Any]],
    price_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    horizons: Sequence[int] = (1, 5, 20),
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for ticker, signal in signals.items():
        action = signal.get("action")
        signal_text = str(signal.get("signal", ""))
        if action != "buy" and "\ub9e4\uc218" not in signal_text:
            continue
        signal_date = signal.get("signal_date") or signal.get("date")
        signal_id = stable_hash(
            {
                "ticker": ticker,
                "signal_date": signal_date,
                "signal": signal_text,
                "action": action,
            }
        )
        prices = list(price_history.get(ticker, []))
        if len(prices) < 2:
            rows.append(
                {
                    "signal_id": signal_id,
                    "ticker": ticker,
                    "signal_date": signal_date,
                    "error": "not_enough_prices",
                }
            )
            continue
        start_index = 0
        if signal_date:
            start_index = next(
                (
                    index
                    for index, row in enumerate(prices)
                    if str(row.get("date", "")) >= str(signal_date)
                ),
                0,
            )
        start_price = float(prices[start_index].get("close", 0.0))
        horizon_returns: dict[str, float | None] = {}
        for horizon in horizons:
            end_index = start_index + horizon
            if start_price <= 0 or end_index >= len(prices):
                horizon_returns[f"{horizon}d"] = None
            else:
                end_price = float(prices[end_index].get("close", 0.0))
                horizon_returns[f"{horizon}d"] = end_price / start_price - 1
        rows.append(
            {
                "signal_id": signal_id,
                "ticker": ticker,
                "signal_date": signal_date,
                "returns": horizon_returns,
            }
        )
    aggregate: dict[str, float] = {}
    for horizon in horizons:
        key = f"{horizon}d"
        values: list[float] = []
        for row in rows:
            row_returns = row.get("returns")
            if isinstance(row_returns, Mapping) and row_returns.get(key) is not None:
                values.append(float(row_returns[key]))
        if values:
            aggregate[key] = sum(values) / len(values)
    return {
        # Raw close-to-close moves after a signal: NO fees/spread/slippage are
        # deducted, so this is a gross signal-quality view, not net tradeable PnL.
        "basis": "gross_no_costs",
        "signals_evaluated": len(rows),
        "aggregate": aggregate,
        "rows": rows,
    }


def _aggregate_signal_rows(
    rows: Sequence[Mapping[str, Any]],
    horizons: Sequence[int] = (1, 5, 20),
) -> dict[str, float]:
    aggregate: dict[str, float] = {}
    for horizon in horizons:
        key = f"{horizon}d"
        values = [
            float(row["returns"][key])
            for row in rows
            if isinstance(row.get("returns"), Mapping) and row["returns"].get(key) is not None
        ]
        if values:
            aggregate[key] = sum(values) / len(values)
    return aggregate


def _merge_signal_history(
    existing: Sequence[Mapping[str, Any]],
    latest: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged = {
        str(row.get("signal_id")): dict(row)
        for row in existing
        if isinstance(row.get("signal_id"), str)
    }
    for row in latest:
        signal_id = row.get("signal_id")
        if not isinstance(signal_id, str):
            continue
        previous = merged.get(signal_id, {})
        raw_previous_returns = previous.get("returns")
        previous_returns: Mapping[str, Any] = (
            raw_previous_returns if isinstance(raw_previous_returns, Mapping) else {}
        )
        raw_latest_returns = row.get("returns")
        latest_returns: Mapping[str, Any] = (
            raw_latest_returns if isinstance(raw_latest_returns, Mapping) else {}
        )
        combined_returns = {
            key: latest_returns.get(key)
            if latest_returns.get(key) is not None
            else previous_returns.get(key)
            for key in set(previous_returns) | set(latest_returns)
        }
        merged_row = {**previous, **dict(row), "returns": combined_returns}
        if latest_returns:
            merged_row.pop("error", None)
        merged[signal_id] = merged_row
    return sorted(
        merged.values(),
        key=lambda row: (str(row.get("signal_date") or ""), str(row.get("ticker") or "")),
    )


def write_signal_performance_report(
    signals: Mapping[str, Mapping[str, Any]],
    price_history: Mapping[str, Sequence[Mapping[str, Any]]],
    output_path: Path,
) -> dict[str, Any]:
    report = post_signal_performance(signals, price_history)
    existing = read_json(output_path, default={})
    existing_history = (
        existing.get("history_rows", [])
        if isinstance(existing, Mapping) and isinstance(existing.get("history_rows"), list)
        else []
    )
    history = _merge_signal_history(existing_history, report["rows"])
    report["history_rows"] = history
    report["history_signal_count"] = len(history)
    report["cumulative_aggregate"] = _aggregate_signal_rows(history)
    atomic_write_json(output_path, report)
    return report


def write_html_report(run_dir: Path, manifest: Mapping[str, Any] | None = None) -> Path:
    manifest_data = dict(manifest or read_json(run_dir / "manifest.json", default={}) or {})
    result = manifest_data.get("result") if isinstance(manifest_data.get("result"), Mapping) else {}
    equity_svgs: list[tuple[str, str]] = []
    for path in sorted((run_dir / "equity").glob("*.json"))[:8]:
        records = read_json(path, default=[])
        if isinstance(records, list):
            equity_svgs.append((path.name, equity_curve_svg(records)))
    importance_data = read_json(run_dir / "parameter_importance.json", default=[])
    importance = importance_data if isinstance(importance_data, list) else []
    validation_data = read_json(run_dir / "validation_report.json", default={})
    validation_rows: list[tuple[str, str, Mapping[str, Any]]] = []
    if isinstance(validation_data, Mapping):
        for ticker, regimes in validation_data.items():
            if not isinstance(regimes, Mapping):
                continue
            for regime, validation in regimes.items():
                if isinstance(validation, Mapping):
                    validation_rows.append((str(ticker), str(regime), validation))
    cost_rows: list[tuple[str, dict[str, Any]]] = []
    for path in sorted((run_dir / "trades").glob("*.json")):
        trades = read_json(path, default=[])
        if isinstance(trades, list) and trades:
            cost_rows.append((path.stem, trade_cost_stats(trades)))
    result_data = read_json(run_dir / "result.json", default={})
    decay_rows: list[dict[str, Any]] = []
    if isinstance(result_data, Mapping) and isinstance(result_data.get("results"), Mapping):
        decay_rows = train_oos_decay(result_data["results"])
    risk_signals = read_json(run_dir / "signals_risk.json", default={})
    risk_rows = risk_decision_rows(risk_signals) if isinstance(risk_signals, Mapping) else []
    rows = [
        ("run_id", manifest_data.get("run_id")),
        ("status", manifest_data.get("status")),
        ("command", manifest_data.get("command")),
        ("git_revision", manifest_data.get("git_revision")),
        ("random_seed", manifest_data.get("random_seed")),
        ("signal_count", result.get("signal_count") if isinstance(result, Mapping) else None),
        ("best_fitness", result.get("best_fitness") if isinstance(result, Mapping) else None),
    ]
    html_rows = "\n".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in rows
        if value is not None
    )
    importance_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('parameter')))}</td>"
        f"<td>{float(row.get('importance', 0.0)):.6f}</td>"
        f"<td>{html.escape(str(row.get('best_value')))}</td>"
        f"<td>{int(row.get('sample_count', 0))}</td>"
        "</tr>"
        for row in importance[:20]
        if isinstance(row, Mapping)
    )
    graph_blocks = "\n".join(
        f"<section><h3>{html.escape(name)}</h3>{svg}</section>" for name, svg in equity_svgs
    )

    def _cell(value: Any) -> str:
        return html.escape("—" if value is None else str(value))

    def _validation_value(validation: Mapping[str, Any], key: str) -> Any:
        evidence = validation.get("statistical_evidence")
        return evidence.get(key) if isinstance(evidence, Mapping) else None

    def _validation_reasons(validation: Mapping[str, Any]) -> str:
        reasons = validation.get("reasons")
        if not isinstance(reasons, Sequence) or isinstance(reasons, (str, bytes)):
            return ""
        return ", ".join(str(reason) for reason in reasons)

    def _lockbox_value(validation: Mapping[str, Any], key: str) -> Any:
        lockbox = validation.get("final_lockbox")
        return lockbox.get(key) if isinstance(lockbox, Mapping) else None

    def _selection_value(validation: Mapping[str, Any], key: str) -> Any:
        selection = validation.get("selection_bias")
        evidence = selection.get("evidence") if isinstance(selection, Mapping) else None
        return evidence.get(key) if isinstance(evidence, Mapping) else None

    cost_table_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(name)}</td>"
        f"<td>{int(stats['trades'])}</td>"
        f"<td>{_cell(stats['avg_net_return_pct'])}</td>"
        f"<td>{_cell(stats['cost_drag_pct_of_gross'])}</td>"
        f"<td>{_cell(stats['breakeven_round_trip_bps'])}</td>"
        f"<td>{_cell(stats['max_survivable_bps'])}</td>"
        f"<td>{_cell(stats['psr_vs_zero'])}</td>"
        "</tr>"
        for name, stats in cost_rows
    )
    cost_section = (
        f"""<h2>Net &amp; Overfitting</h2>
  <p>Per-strategy net (post-cost) summary. Breakeven and max-survivable are
  round-trip costs in bps; PSR is P(true Sharpe &gt; 0) on net trade returns.</p>
  <table>
    <tr><th>Strategy</th><th>Trades</th><th>Avg net %</th><th>Cost drag % of gross</th>
        <th>Breakeven bps</th><th>Max survivable bps</th><th>PSR vs 0</th></tr>
    {cost_table_rows}
  </table>"""
        if cost_rows
        else ""
    )
    validation_table_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(ticker)}</td>"
        f"<td>{html.escape(regime)}</td>"
        f"<td>{'approved' if validation.get('approved') else 'rejected'}</td>"
        f"<td>{_cell(_validation_value(validation, 'psr_vs_zero'))}</td>"
        f"<td>{_cell(_selection_value(validation, 'dsr'))}</td>"
        f"<td>{_cell(_selection_value(validation, 'pbo'))}</td>"
        f"<td>{_cell(_selection_value(validation, 'candidate_count'))}</td>"
        f"<td>{_cell(_lockbox_value(validation, 'lockbox_retention'))}</td>"
        f"<td>{_cell(_lockbox_value(validation, 'reused'))}</td>"
        f"<td>{_cell(_validation_reasons(validation))}</td>"
        "</tr>"
        for ticker, regime, validation in validation_rows
    )
    validation_section = (
        f"""<h2>OOS Validation</h2>
  <p>Approval includes purged walk-forward folds and the probability that
  out-of-sample Sharpe exceeds zero.</p>
  <table>
    <tr><th>Ticker</th><th>Regime</th><th>Status</th><th>OOS PSR vs 0</th>
        <th>DSR</th><th>PBO</th><th>Candidates</th><th>Lockbox retention</th>
        <th>Lockbox reused</th><th>Rejection reasons</th></tr>
    {validation_table_rows}
  </table>"""
        if validation_rows
        else ""
    )
    decay_table_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['ticker'])}</td>"
        f"<td>{html.escape(row['regime'])}</td>"
        f"<td>{_cell(row['train_fitness'])}</td>"
        f"<td>{_cell(row['oos_fitness'])}</td>"
        f"<td>{_cell(row['fitness_retention'])}</td>"
        f"<td>{_cell(row['train_return'])}</td>"
        f"<td>{_cell(row['oos_return'])}</td>"
        f"<td>{'⚠️ degraded' if row['degraded'] else 'ok'}</td>"
        "</tr>"
        for row in decay_rows
    )
    decay_section = (
        f"""<h2>Train → OOS Decay</h2>
  <p>How much of the in-sample edge survives out-of-sample. Retention is
  OOS/train fitness; a degraded flag marks overfitting (OOS fitness non-positive
  or under half retained).</p>
  <table>
    <tr><th>Ticker</th><th>Regime</th><th>Train fitness</th><th>OOS fitness</th>
        <th>Fitness retention</th><th>Train return %</th><th>OOS return %</th>
        <th>Health</th></tr>
    {decay_table_rows}
  </table>"""
        if decay_rows
        else ""
    )
    risk_table_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['ticker'])}</td>"
        f"<td>{_cell(row['action'])}</td>"
        f"<td>{'eligible' if row['eligible'] else 'blocked'}</td>"
        f"<td>{_cell(row['requested_pct'])}</td>"
        f"<td>{_cell(row['approved_pct'])}</td>"
        f"<td>{'yes' if row['resized'] else 'no'}</td>"
        f"<td>{_cell(', '.join(row['reasons']) or '—')}</td>"
        f"<td>{_cell(', '.join(row['warnings']) or '—')}</td>"
        "</tr>"
        for row in risk_rows
    )
    risk_section = (
        f"""<h2>Risk Decisions</h2>
  <p>Per-signal portfolio-risk approval. Reasons are structured violation codes;
  warnings (e.g. an unmapped ticker) do not block.</p>
  <table>
    <tr><th>Ticker</th><th>Action</th><th>Status</th><th>Requested</th><th>Approved</th>
        <th>Resized</th><th>Block reasons</th><th>Warnings</th></tr>
    {risk_table_rows}
  </table>"""
        if risk_rows
        else ""
    )
    content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Jayu Run Report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 32px; color: #0f172a; }}
    table {{ border-collapse: collapse; margin-bottom: 24px; min-width: 520px; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 8px 10px; text-align: left; }}
    th {{ background: #f1f5f9; }}
    section {{ margin: 24px 0; }}
  </style>
</head>
<body>
  <h1>Jayu Run Report</h1>
  <h2>Summary</h2>
  <table>{html_rows}</table>
  <h2>Equity Curves</h2>
  {graph_blocks or "<p>No equity curve artifacts found.</p>"}
  {validation_section}
  {risk_section}
  {decay_section}
  {cost_section}
  <h2>Parameter Importance</h2>
  <table>
    <tr><th>Parameter</th><th>Importance</th><th>Best Value</th><th>Samples</th></tr>
    {importance_rows}
  </table>
</body>
</html>
"""
    output = run_dir / "report.html"
    _atomic_write_text(output, content)
    return output
