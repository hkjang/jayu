from __future__ import annotations

import json
import random

from pathlib import Path
from typing import Annotated, Any, cast

import typer
import numpy as np

from . import engine
from .artifacts import RunContext
from .data import (
    CachedMarketDataService,
    MarketDataProvider,
    MassiveProvider,
    YahooProvider,
)
from .io import atomic_write_json, read_json
from .monitoring import classify_failure, prune_runs, update_health
from .notifications import KakaoNotifier, build_signal_message
from .portfolio import (
    get_fx_rates,
    load_portfolio,
    load_portfolio_mapping,
    portfolio_summary,
    unmapped_ticker_report,
)
from .portfolio_build import build_portfolio_csv
from .paths import RuntimePaths
from .registry import ExperimentRegistry
from .reports import (
    parameter_importance,
    write_html_report,
    write_signal_performance_report,
)
from .risk import apply_portfolio_risk
from .risk_ledger import record_portfolio_snapshot
from .settings import Settings, load_settings
from .strategy_space import load_strategy_spaces, validate_strategy_spaces
from .survivorship import audit_survivorship


app = typer.Typer(no_args_is_help=True, help="Jayu stock research automation")
portfolio_app = typer.Typer(no_args_is_help=True, help="Portfolio maintenance and risk")
report_app = typer.Typer(no_args_is_help=True, help="Run and signal reports")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(report_app, name="report")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load(config: Path | None) -> tuple[Settings, RuntimePaths]:
    root = _project_root()
    config_path = config or root / "config.json"
    settings = load_settings(config_path if config_path.exists() else None)
    paths = settings.runtime_paths(root)
    paths.ensure_runtime_dirs()
    return settings, paths


def _data_service(
    settings: Settings,
    paths: RuntimePaths,
    context: RunContext,
    refresh: bool,
):
    providers: list[MarketDataProvider] = []
    massive_key = settings.massive_api_key.get_secret_value() if settings.massive_api_key else None
    if settings.data_provider == "yahoo":
        providers.append(YahooProvider())
    elif massive_key:
        providers.append(MassiveProvider(massive_key))
    else:
        raise ValueError("massive data provider requires JAYU_MASSIVE_API_KEY")
    if (
        settings.data_fallback_provider != "none"
        and settings.data_fallback_provider != settings.data_provider
    ):
        if settings.data_fallback_provider == "yahoo":
            providers.append(YahooProvider())
        elif massive_key:
            providers.append(MassiveProvider(massive_key))
    service = CachedMarketDataService(
        paths.cache_dir,
        providers,
        run_context=context,
        refresh_all=refresh,
    )
    return service


def _apply_risk(
    settings: Settings,
    paths: RuntimePaths,
    signals: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not paths.portfolio_file.exists():
        for signal in signals.values():
            if signal.get("action") == "buy":
                signal["eligible"] = False
                signal["risk"] = {
                    "violations": ["portfolio file unavailable; risk cannot be evaluated"]
                }
        return signals
    mapping = load_portfolio_mapping(paths.portfolio_mapping_file)
    fx_rates = get_fx_rates(["USD", "EUR", "JPY", "HKD"])
    portfolio = portfolio_summary(
        load_portfolio(
            paths.portfolio_file,
            fx_rates["USD"],
            mapping=mapping,
            fx_rates=fx_rates,
        ),
        account_value_krw=settings.account_value_krw,
        cash_balance_krw=settings.cash_balance_krw,
    )
    atomic_write_json(
        paths.state_dir / "portfolio_unmapped_tickers.json",
        unmapped_ticker_report(portfolio),
    )
    portfolio["risk_status"] = record_portfolio_snapshot(
        paths.state_dir / "portfolio_snapshots.jsonl",
        account_value_krw=float(portfolio["account_value_krw"]),
        cash_balance_krw=float(portfolio["cash_balance_krw"]),
    )
    return apply_portfolio_risk(signals, portfolio, settings.risk, mapping=mapping)


def _best_fitness(best_all: dict[str, Any]) -> float | None:
    values = []
    for ticker_data in best_all.values():
        if not isinstance(ticker_data, dict):
            continue
        for regime_data in ticker_data.values():
            if not isinstance(regime_data, dict):
                continue
            for key in ("val_metrics", "metrics"):
                value = regime_data.get(key, {}).get("fitness")
                if isinstance(value, (int, float)):
                    values.append(float(value))
    return max(values) if values else None


def _run_engine(
    command: str,
    *,
    config: Path | None,
    tickers: list[str] | None,
    runs: int | None,
    optimize: bool,
    notify_user: bool,
    refresh_data: bool,
    verbose: bool,
    seed: int | None,
) -> None:
    settings, paths = _load(config)
    overrides: dict[str, Any] = {}
    if tickers:
        overrides["tickers"] = tickers
    if runs is not None:
        overrides["sim_runs"] = runs
    if seed is not None:
        overrides["random_seed"] = seed
    if overrides:
        settings = Settings.model_validate({**settings.model_dump(), **overrides})
    prune_runs(
        paths.runs_dir,
        max_age_days=settings.run_retention_days,
        max_runs=settings.run_retention_count,
    )
    random.seed(settings.random_seed)
    np.random.seed(settings.random_seed)
    context = RunContext.create(paths, settings, command, verbose=verbose)
    registry = ExperimentRegistry(paths.state_dir / "experiments.sqlite")
    registry.start(context)
    try:
        best_all, _, improved, signals = engine.run(
            settings,
            paths,
            data_service=_data_service(settings, paths, context, refresh_data),
            optimize=optimize,
            notify=False,
            run_context=context,
            require_approved=True,
        )
        signals = _apply_risk(settings, paths, signals)
        atomic_write_json(paths.signal_file, signals)
        risk_signal_path = context.run_dir / "signals_risk.json"
        atomic_write_json(risk_signal_path, signals)
        context.record_artifact(risk_signal_path)
        notification_result = None
        if notify_user:
            notification_result = KakaoNotifier(settings, paths).send(
                build_signal_message(
                    signals,
                    max_chars=settings.notification_message_limit,
                )
            )
            atomic_write_json(context.run_dir / "notification.json", notification_result)
        successful_tickers = {
            str(report.get("ticker"))
            for report in context.data_reports.values()
            if report.get("valid") and report.get("ticker") in settings.tickers
        }
        summary = {
            "run_id": context.run_id,
            "random_seed": settings.random_seed,
            "fitness_version": settings.research.fitness_version,
            "improved_tickers": improved,
            "signal_count": len(signals),
            "successful_ticker_count": len(successful_tickers),
            "failed_ticker_count": len(settings.tickers) - len(successful_tickers),
            "best_fitness": _best_fitness(best_all),
            "eligible_signal_count": sum(
                bool(signal.get("eligible")) for signal in signals.values()
            ),
            "notification": notification_result,
        }
        importance_path = context.run_dir / "parameter_importance.json"
        atomic_write_json(importance_path, parameter_importance(best_all))
        context.record_artifact(importance_path)
        context.write_manifest(status="success", result=summary)
        report_path = write_html_report(context.run_dir)
        context.record_artifact(report_path)
        context.write_manifest(status="success", result=summary)
        registry.finish(context, status="success", result=summary)
        update_health(
            paths.state_dir / "health.json",
            run_id=context.run_id,
            status="success",
            summary=summary,
        )
        typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        failure_code = classify_failure(exc)
        context.logger.exception(
            "command failed",
            extra={
                "run_id": context.run_id,
                "event": "command_failure",
                "error_code": failure_code,
            },
        )
        context.write_manifest(
            status="failed",
            error=str(exc),
            failure_code=failure_code,
        )
        registry.finish(
            context,
            status="failed",
            error=str(exc),
            failure_code=failure_code,
        )
        update_health(
            paths.state_dir / "health.json",
            run_id=context.run_id,
            status="failed",
            error=str(exc),
            failure_code=failure_code,
        )
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("validate-config")
def validate_config(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    settings, paths = _load(config)
    strategy_space_audit = validate_strategy_spaces(load_strategy_spaces())
    typer.echo(json.dumps(settings.public_dict(), ensure_ascii=False, indent=2))
    typer.echo(
        json.dumps(
            {
                "strategy_space_audit": strategy_space_audit,
                "survivorship_audit": audit_survivorship(settings).to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    typer.echo(f"state_dir={paths.state_dir}")
    typer.echo("configuration is valid")


@app.command()
def simulate(
    ticker: Annotated[list[str] | None, typer.Option("--ticker", "-t")] = None,
    runs: Annotated[int | None, typer.Option("--runs", min=1)] = None,
    notify: Annotated[bool, typer.Option("--notify/--no-notify")] = False,
    refresh_data: Annotated[bool, typer.Option("--refresh-data")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
    seed: Annotated[int | None, typer.Option("--seed", min=0)] = None,
) -> None:
    _run_engine(
        "simulate",
        config=config,
        tickers=ticker,
        runs=runs,
        optimize=True,
        notify_user=notify,
        refresh_data=refresh_data,
        verbose=verbose,
        seed=seed,
    )


@app.command()
def signal(
    date: Annotated[str, typer.Option("--date")] = "today",
    ticker: Annotated[list[str] | None, typer.Option("--ticker", "-t")] = None,
    notify: Annotated[bool, typer.Option("--notify/--no-notify")] = False,
    refresh_data: Annotated[bool, typer.Option("--refresh-data")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    seed: Annotated[int | None, typer.Option("--seed", min=0)] = None,
) -> None:
    if date != "today":
        raise typer.BadParameter("only --date today is supported")
    _run_engine(
        "signal",
        config=config,
        tickers=ticker,
        runs=None,
        optimize=False,
        notify_user=notify,
        refresh_data=refresh_data,
        verbose=False,
        seed=seed,
    )


@app.command()
def notify(
    channel: Annotated[str, typer.Option("--channel")] = "kakao",
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    if channel != "kakao":
        raise typer.BadParameter("supported channel: kakao")
    settings, paths = _load(config)
    signals = read_json(paths.signal_file, default={})
    result = KakaoNotifier(settings, paths).send(
        build_signal_message(
            signals,
            max_chars=settings.notification_message_limit,
        )
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@portfolio_app.command("build")
def portfolio_build(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    report = build_portfolio_csv(
        paths.portfolio_file,
        ticker_map_file=paths.project_root / "configs" / "portfolio_ticker_map.json",
        mapping_file=paths.portfolio_mapping_file,
    )
    typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


@portfolio_app.command("analyze")
def portfolio_analyze(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    details: Annotated[bool, typer.Option("--details")] = False,
    top: Annotated[int, typer.Option("--top", min=1, max=100)] = 20,
) -> None:
    settings, paths = _load(config)
    if not paths.portfolio_file.exists():
        raise typer.BadParameter(f"portfolio file not found: {paths.portfolio_file}")
    mapping = load_portfolio_mapping(paths.portfolio_mapping_file)
    fx_rates = get_fx_rates(["USD", "EUR", "JPY", "HKD"])
    summary = portfolio_summary(
        load_portfolio(
            paths.portfolio_file,
            fx_rates["USD"],
            mapping=mapping,
            fx_rates=fx_rates,
        ),
        account_value_krw=settings.account_value_krw,
        cash_balance_krw=settings.cash_balance_krw,
    )
    summary["mapping"] = {
        "version": mapping.version,
        "source": mapping.source,
    }
    atomic_write_json(
        paths.state_dir / "portfolio_unmapped_tickers.json",
        unmapped_ticker_report(summary),
    )
    summary["risk_status"] = record_portfolio_snapshot(
        paths.state_dir / "portfolio_snapshots.jsonl",
        account_value_krw=float(summary["account_value_krw"]),
        cash_balance_krw=float(summary["cash_balance_krw"]),
    )
    if not details:
        summary.pop("positions", None)
        exposures = summary["underlying_exposure_pct"]
        summary["underlying_exposure_pct"] = dict(
            sorted(exposures.items(), key=lambda item: item[1], reverse=True)[:top]
        )
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@app.command("experiments")
def experiments(
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 20,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    rows = ExperimentRegistry(paths.state_dir / "experiments.sqlite").latest(limit)
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))


@report_app.command("build")
def report_build(
    run: Annotated[Path, typer.Option("--run", exists=True, file_okay=False)],
) -> None:
    output = write_html_report(run)
    typer.echo(str(output))


@report_app.command("signal-performance")
def report_signal_performance(
    price_json: Annotated[Path, typer.Option("--price-json", exists=True)],
    signals: Annotated[Path | None, typer.Option("--signals")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    signal_path = signals or paths.signal_file
    output_path = output or (paths.state_dir / "signal_performance.json")
    signal_data = read_json(signal_path, default={})
    price_data = read_json(price_json, default={})
    if not isinstance(signal_data, dict) or not isinstance(price_data, dict):
        raise typer.BadParameter("signals and price-json must be JSON objects")
    report = write_signal_performance_report(
        cast("dict[str, dict[str, Any]]", signal_data),
        cast("dict[str, list[dict[str, Any]]]", price_data),
        output_path,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
