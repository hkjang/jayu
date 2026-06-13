from __future__ import annotations

import html
import json
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_json


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
        prices = list(price_history.get(ticker, []))
        if len(prices) < 2:
            rows.append({"ticker": ticker, "error": "not_enough_prices"})
            continue
        signal_date = signal.get("signal_date") or signal.get("date")
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
        rows.append({"ticker": ticker, "signal_date": signal_date, "returns": horizon_returns})
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


def write_signal_performance_report(
    signals: Mapping[str, Mapping[str, Any]],
    price_history: Mapping[str, Sequence[Mapping[str, Any]]],
    output_path: Path,
) -> dict[str, Any]:
    report = post_signal_performance(signals, price_history)
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
