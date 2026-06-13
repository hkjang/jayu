from __future__ import annotations

import json
import random

from datetime import date as date_type
from pathlib import Path
from typing import Annotated, Any, cast

import typer
import numpy as np

from . import engine
from .artifacts import RunContext
from .contracts import (
    ensure_contract,
    validate_portfolio_snapshot_contract,
    validate_signal_contract,
)
from .data import (
    CachedMarketDataService,
    MarketDataProvider,
)
from .failure_codes import FailureCode
from .io import atomic_write_json, file_sha256, read_json, stable_hash
from .monitoring import classify_failure, compute_health_score, prune_runs, update_health
from .notifications import KakaoNotifier, build_signal_message
from .portfolio import (
    get_fx_rates,
    load_portfolio,
    load_portfolio_mapping,
    portfolio_summary,
    unmapped_ticker_report,
)
from .portfolio_build import build_portfolio_csv
from .provider_factory import (
    build_provider_registry,
    collect_supplemental_data,
    price_provider_sequence,
    provider_configuration_audit,
    provider_policy,
)
from .provider_core import ProviderCategory, ProviderRegistry
from .paths import RuntimePaths
from .registry import ExperimentRegistry
from .reports import (
    parameter_importance,
    write_cost_sensitivity_report,
    write_html_report,
    write_shadow_performance_report,
    write_signal_performance_report,
)
from .risk import apply_data_trust, apply_portfolio_risk, risk_explanation
from .risk_ledger import record_portfolio_snapshot
from .safety import (
    enforce_live_price_safety,
    enforce_research_universe,
    enforce_shadow_promotion,
    write_promotion_report,
)
from .settings import Settings, load_settings
from .signal_replay import write_signal_replay_artifact
from .strategy_space import load_strategy_spaces, validate_strategy_spaces
from .survivorship import audit_survivorship


app = typer.Typer(no_args_is_help=True, help="Jayu stock research automation")
portfolio_app = typer.Typer(no_args_is_help=True, help="Portfolio maintenance and risk")
report_app = typer.Typer(no_args_is_help=True, help="Run and signal reports")
experiments_app = typer.Typer(help="Experiment registry and comparisons")
promotion_app = typer.Typer(no_args_is_help=True, help="Shadow-to-live promotion")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(report_app, name="report")
app.add_typer(experiments_app, name="experiments")
app.add_typer(promotion_app, name="promotion")


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
    provider_registry: ProviderRegistry,
):
    providers, unavailable = price_provider_sequence(settings, provider_registry)
    for name in unavailable:
        context.record_data_source(
            {
                "provider": name,
                "category": ProviderCategory.PRICE.value,
                "status": "failed",
                "error": "provider credentials are not configured",
            }
        )
    primary_policy = provider_policy(settings, settings.data_provider)
    price_policies = {
        provider.name: provider_policy(settings, provider.name) for provider in providers
    }
    service = CachedMarketDataService(
        paths.cache_dir,
        cast(list[MarketDataProvider], providers),
        run_context=context,
        retries=primary_policy.retries,
        refresh_all=refresh,
        cross_validate=bool(settings.data.cross_validation_providers),
        minimum_valid_sources=settings.data.minimum_valid_price_sources,
        disagreement_policy=settings.data.price_disagreement_policy,
        max_row_count_delta=settings.data.max_row_count_delta,
        max_index_mismatches=settings.data.max_index_mismatches,
        max_relative_price_delta=settings.data.max_relative_price_delta,
        max_relative_volume_delta=settings.data.max_relative_volume_delta,
        cache_ttl_seconds=primary_policy.cache_ttl_seconds,
        provider_retries={name: policy.retries for name, policy in price_policies.items()},
        provider_rate_limits_per_minute={
            name: policy.rate_limit_per_minute for name, policy in price_policies.items()
        },
    )
    return service


def _apply_risk(
    settings: Settings,
    paths: RuntimePaths,
    signals: dict[str, dict[str, Any]],
    context: RunContext,
) -> dict[str, dict[str, Any]]:
    if not paths.portfolio_file.exists():
        context.record_data(
            "portfolio_snapshot",
            data_hash=stable_hash({"available": False}),
            quality_report={
                "kind": "portfolio_snapshot",
                "available": False,
                "valid": False,
            },
        )
        for signal in signals.values():
            if signal.get("action") == "buy":
                signal["eligible"] = False
                signal["risk"] = {
                    "violations": ["portfolio file unavailable; risk cannot be evaluated"],
                    "violation_details": [
                        {
                            "code": FailureCode.PORTFOLIO_FILE_UNAVAILABLE.value,
                            "message": "portfolio file unavailable; risk cannot be evaluated",
                            "metric": "portfolio_file",
                            "observed": False,
                            "limit": True,
                        }
                    ],
                }
        evaluated = signals
    else:
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
        ensure_contract(
            "portfolio_snapshot",
            validate_portfolio_snapshot_contract(
                {
                    "account_value_krw": portfolio.get("account_value_krw"),
                    "cash_balance_krw": portfolio.get("cash_balance_krw", 0.0),
                }
            ),
        )
        context.record_data(
            "portfolio_snapshot",
            data_hash=stable_hash(portfolio),
            quality_report={
                "kind": "portfolio_snapshot",
                "available": True,
                "valid": True,
                "position_count": len(portfolio.get("positions", [])),
            },
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
        evaluated = apply_portfolio_risk(signals, portfolio, settings.risk, mapping=mapping)
    return apply_data_trust(
        evaluated,
        price_trust=context.price_trust,
        reference_audits=context.reference_audits,
        event_notes=context.event_notes,
        require_verified_price=settings.data.require_verified_price_for_eligibility,
        reference_conflict_policy=settings.data.reference_conflict_policy,
    )


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


def _failed_market_tickers(settings: Settings, context: RunContext) -> list[str]:
    successful = {
        str(report.get("ticker"))
        for report in context.data_reports.values()
        if report.get("valid")
        and report.get("price_usable")
        and report.get("ticker") in settings.tickers
    }
    return sorted(set(settings.tickers) - successful)


def _resolve_signal_date(value: str, *, replay: bool) -> str | None:
    if value == "today":
        return None
    try:
        parsed = date_type.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("--date must be today or YYYY-MM-DD") from exc
    if not replay:
        raise typer.BadParameter("--date YYYY-MM-DD is supported only with --replay")
    return parsed.isoformat()


def _annotate_shadow_signals(
    signals: dict[str, dict[str, Any]],
    *,
    reason: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for ticker, signal in signals.items():
        item = dict(signal)
        if item.get("action") == "buy":
            item.setdefault("shadow_status", "pending")
            item.setdefault("shadow_reason", reason)
        else:
            item.setdefault("shadow_status", "not_applicable")
            item.setdefault("shadow_reason", "not_buy_signal")
        item.setdefault("future_return_1d", None)
        item.setdefault("future_return_5d", None)
        item.setdefault("future_return_20d", None)
        result[ticker] = item
    return result


def _write_risk_explanation(
    context: RunContext,
    signals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    explanation = risk_explanation(signals)
    path = context.run_dir / "risk_explanation.json"
    atomic_write_json(path, explanation)
    context.record_artifact(path)
    return explanation


def _validation_status(run_dir: Path) -> str:
    payload = read_json(run_dir / "validation_report.json", default={})
    decisions: list[bool] = []
    if isinstance(payload, dict):
        for regimes in payload.values():
            if not isinstance(regimes, dict):
                continue
            for validation in regimes.values():
                if isinstance(validation, dict) and "approved" in validation:
                    decisions.append(validation.get("approved") is True)
    if not decisions:
        return "not_evaluated"
    return "approved" if all(decisions) else "rejected"


def _record_signal_inputs(context: RunContext, paths: RuntimePaths) -> None:
    inputs = {
        "best_strategy_state": paths.best_strategy_file,
        "portfolio_mapping": paths.portfolio_mapping_file,
    }
    for key, path in inputs.items():
        available = path.exists() and path.is_file()
        context.record_data(
            key,
            data_hash=file_sha256(path) if available else stable_hash({"available": False}),
            quality_report={
                "kind": "signal_input",
                "path": str(path),
                "available": available,
                "valid": available,
            },
        )


def _output_policy(*, replay: bool, shadow_mode: bool) -> dict[str, bool]:
    return {
        "persist_state": not replay,
        "persist_signal": not replay and not shadow_mode,
        "write_primary_signal": not replay and not shadow_mode,
        "update_health": not replay,
        "prune_runs": not replay,
    }


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
    replay_date: str | None = None,
    replay: bool = False,
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
    shadow_mode = settings.mode == "shadow"
    output_policy = _output_policy(replay=replay, shadow_mode=shadow_mode)
    signal_date = replay_date or date_type.today().isoformat()
    effective_notify = bool(notify_user and not shadow_mode and not replay)
    if output_policy["prune_runs"]:
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
        _record_signal_inputs(context, paths)
        provider_registry = build_provider_registry(settings, paths.cache_dir)
        if optimize:
            research_safety = enforce_research_universe(settings)
            research_safety_path = context.run_dir / "research_universe_safety.json"
            atomic_write_json(research_safety_path, research_safety)
            context.record_artifact(research_safety_path)
        if settings.mode == "live" and not replay and not optimize:
            live_price_safety = enforce_live_price_safety(settings, provider_registry)
            live_price_path = context.run_dir / "live_price_safety.json"
            atomic_write_json(live_price_path, live_price_safety)
            context.record_artifact(live_price_path)
            promotion = enforce_shadow_promotion(
                paths.state_dir / "promotion.json",
                paths.signals_dir / "shadow",
                paths.state_dir / "health.json",
                settings.promotion,
            )
            promotion_path = context.run_dir / "promotion.json"
            atomic_write_json(promotion_path, promotion)
            context.record_artifact(promotion_path)
        collect_supplemental_data(settings, provider_registry, context)
        best_all, _, improved, signals = engine.run(
            settings,
            paths,
            data_service=_data_service(
                settings,
                paths,
                context,
                refresh_data,
                provider_registry,
            ),
            optimize=optimize,
            notify=False,
            run_context=context,
            require_approved=True,
            as_of_date=replay_date,
            persist_state=output_policy["persist_state"],
            persist_signal=output_policy["persist_signal"],
        )
        failed_market_tickers = _failed_market_tickers(settings, context)
        if failed_market_tickers:
            raise RuntimeError(
                "market data provider failed verification for requested tickers: "
                + ", ".join(failed_market_tickers)
            )
        signals = _apply_risk(settings, paths, signals, context)
        if shadow_mode:
            signals = _annotate_shadow_signals(signals, reason="mode=shadow")
        ensure_contract("signal_dataframe", validate_signal_contract(signals))
        if output_policy["write_primary_signal"]:
            atomic_write_json(paths.signal_file, signals)
        if shadow_mode:
            shadow_path = paths.signals_dir / "shadow" / f"{signal_date}.json"
            atomic_write_json(shadow_path, signals)
        risk_signal_path = context.run_dir / "signals_risk.json"
        atomic_write_json(risk_signal_path, signals)
        context.record_artifact(risk_signal_path)
        signal_replay = write_signal_replay_artifact(
            context.run_dir / "signal_replay.json",
            signals,
            config_hash=context.config_hash,
            data_hashes=context.data_hashes,
            seed=context.seed,
            signal_date=signal_date,
            replay=replay,
        )
        context.record_artifact(context.run_dir / "signal_replay.json")
        risk_summary = _write_risk_explanation(context, signals)
        cost_report = write_cost_sensitivity_report(
            context.run_dir,
            current_round_trip_bps=(settings.transaction_fee + settings.slippage) * 2.0 * 10_000.0,
            approval_buffer_bps=settings.research.cost_survival_buffer_bps,
            signals=signals,
        )
        context.record_artifact(context.run_dir / "cost_sensitivity.json")
        successful_tickers = set(settings.tickers)
        summary = {
            "run_id": context.run_id,
            "random_seed": settings.random_seed,
            "fitness_version": settings.research.fitness_version,
            "improved_tickers": improved,
            "signal_count": len(signals),
            "successful_ticker_count": len(successful_tickers),
            "failed_ticker_count": len(settings.tickers) - len(successful_tickers),
            "best_fitness": _best_fitness(best_all),
            "eligible_signal_count": risk_summary.get("approved_count", 0),
            "blocked_signal_count": risk_summary.get("blocked_count", 0),
            "hold_signal_count": risk_summary.get("hold_count", 0),
            "top_block_reasons": risk_summary.get("top_block_reasons", []),
            "mode": settings.mode,
            "replay": replay,
            "signal_date": signal_date,
            "signal_hash": signal_replay["signal_hash"],
            "config_hash": context.config_hash,
            "data_hash": stable_hash(context.data_hashes),
            "validation_status": _validation_status(context.run_dir),
            "cost_survival": cost_report.get("cost_survival_status"),
            "risk_status": "passed" if risk_summary.get("blocked_count", 0) == 0 else "blocked",
            "notification": None,
        }
        previous_health = read_json(paths.state_dir / "health.json", default={})
        previous_failure = (
            previous_health.get("last_failure") if isinstance(previous_health, dict) else None
        )
        health_score = compute_health_score(
            status="success",
            summary=summary,
            failure_code=None,
            previous_failure=previous_failure,
        )
        if effective_notify:
            notification_result = KakaoNotifier(settings, paths).send(
                build_signal_message(
                    signals,
                    max_chars=settings.notification_message_limit,
                    health_score=health_score,
                )
            )
            summary["notification"] = notification_result
            atomic_write_json(context.run_dir / "notification.json", notification_result)
        importance_path = context.run_dir / "parameter_importance.json"
        atomic_write_json(importance_path, parameter_importance(best_all))
        context.record_artifact(importance_path)
        context.write_manifest(status="success", result=summary)
        report_path = write_html_report(context.run_dir)
        context.record_artifact(report_path)
        context.write_manifest(status="success", result=summary)
        registry.finish(context, status="success", result=summary)
        if output_policy["update_health"]:
            update_health(
                paths.state_dir / "health.json",
                run_id=context.run_id,
                status="success",
                summary=summary,
            )
            if shadow_mode:
                write_promotion_report(
                    paths.state_dir / "promotion.json",
                    paths.signals_dir / "shadow",
                    paths.state_dir / "health.json",
                    settings.promotion,
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
        if output_policy["update_health"]:
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
    provider_registry = build_provider_registry(settings, paths.cache_dir)
    provider_audit = provider_configuration_audit(settings, provider_registry)
    if not provider_audit["valid"]:
        raise ValueError(
            "provider configuration is invalid: "
            + "; ".join(str(error) for error in provider_audit["errors"])
        )
    typer.echo(json.dumps(settings.public_dict(), ensure_ascii=False, indent=2))
    typer.echo(
        json.dumps(
            {
                "strategy_space_audit": strategy_space_audit,
                "provider_audit": provider_audit,
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
    replay: Annotated[bool, typer.Option("--replay")] = False,
    ticker: Annotated[list[str] | None, typer.Option("--ticker", "-t")] = None,
    notify: Annotated[bool, typer.Option("--notify/--no-notify")] = False,
    refresh_data: Annotated[bool, typer.Option("--refresh-data")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    seed: Annotated[int | None, typer.Option("--seed", min=0)] = None,
) -> None:
    replay_date = _resolve_signal_date(date, replay=replay)
    _run_engine(
        "signal_replay" if replay else "signal",
        config=config,
        tickers=ticker,
        runs=None,
        optimize=False,
        notify_user=False if replay else notify,
        refresh_data=refresh_data,
        verbose=False,
        seed=seed,
        replay_date=replay_date,
        replay=replay,
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
    health = read_json(paths.state_dir / "health.json", default={})
    score = health.get("health_score") if isinstance(health, dict) else None
    result = KakaoNotifier(settings, paths).send(
        build_signal_message(
            signals,
            max_chars=settings.notification_message_limit,
            health_score=score if isinstance(score, int) else None,
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


@experiments_app.callback(invoke_without_command=True)
def experiments(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 20,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    _, paths = _load(config)
    rows = ExperimentRegistry(paths.state_dir / "experiments.sqlite").latest(limit)
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))


@experiments_app.command("compare")
def experiments_compare(
    left: Annotated[str, typer.Option("--left")],
    right: Annotated[str, typer.Option("--right")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    _, paths = _load(config)
    registry = ExperimentRegistry(paths.state_dir / "experiments.sqlite")
    left_row = registry.get(left)
    right_row = registry.get(right)
    if left_row is None or right_row is None:
        missing = [run_id for run_id, row in ((left, left_row), (right, right_row)) if row is None]
        raise typer.BadParameter(f"unknown run_id: {', '.join(missing)}")
    comparison = _compare_experiment_rows(left_row, right_row)
    table = _comparison_table(comparison)
    typer.echo(table)
    typer.echo(json.dumps(comparison, ensure_ascii=False, indent=2))
    if output:
        atomic_write_json(output, comparison)


def _json_field(row: dict[str, Any], key: str, default: Any) -> Any:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _compare_experiment_rows(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_result = _json_field(left, "result_json", {})
    right_result = _json_field(right, "result_json", {})
    left_data = _json_field(left, "data_hashes_json", {})
    right_data = _json_field(right, "data_hashes_json", {})
    left_artifact = Path(str(left.get("artifact_dir")))
    right_artifact = Path(str(right.get("artifact_dir")))
    left_cost = read_json(left_artifact / "cost_sensitivity.json", default={})
    right_cost = read_json(right_artifact / "cost_sensitivity.json", default={})
    return {
        "left": left.get("run_id"),
        "right": right.get("run_id"),
        "metrics": {
            "best_fitness": _pair(
                left_result.get("best_fitness"), right_result.get("best_fitness")
            ),
            "eligible_signal_count": _pair(
                left_result.get("eligible_signal_count"),
                right_result.get("eligible_signal_count"),
            ),
            "blocked_signal_count": _pair(
                left_result.get("blocked_signal_count"),
                right_result.get("blocked_signal_count"),
            ),
        },
        "config_hash": _pair(left.get("config_hash"), right.get("config_hash")),
        "data_hash": _pair(stable_hash(left_data), stable_hash(right_data)),
        "signal_hash": _pair(left_result.get("signal_hash"), right_result.get("signal_hash")),
        "validation_status": _pair(
            left_result.get("validation_status"),
            right_result.get("validation_status"),
        ),
        "cost_survival": _pair(
            _cost_status(left_cost, left_result),
            _cost_status(right_cost, right_result),
        ),
        "risk_status": _pair(left_result.get("risk_status"), right_result.get("risk_status")),
    }


def _pair(left: Any, right: Any) -> dict[str, Any]:
    return {"left": left, "right": right, "changed": left != right}


def _cost_status(cost_payload: Any, result: dict[str, Any]) -> Any:
    if isinstance(cost_payload, dict) and cost_payload.get("cost_survival_status"):
        return cost_payload.get("cost_survival_status")
    return result.get("cost_survival")


def _comparison_table(comparison: dict[str, Any]) -> str:
    rows = ["field | left | right | changed", "--- | --- | --- | ---"]
    for field in (
        "config_hash",
        "data_hash",
        "signal_hash",
        "validation_status",
        "cost_survival",
        "risk_status",
    ):
        item = comparison[field]
        rows.append(f"{field} | {item.get('left')} | {item.get('right')} | {item.get('changed')}")
    metrics = comparison.get("metrics", {})
    if isinstance(metrics, dict):
        for name, item in metrics.items():
            if isinstance(item, dict):
                rows.append(
                    f"metric.{name} | {item.get('left')} | {item.get('right')} | "
                    f"{item.get('changed')}"
                )
    return "\n".join(rows)


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


@report_app.command("shadow-performance")
def report_shadow_performance(
    price_json: Annotated[Path, typer.Option("--price-json", exists=True)],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    settings, paths = _load(config)
    price_data = read_json(price_json, default={})
    if not isinstance(price_data, dict):
        raise typer.BadParameter("price-json must be a JSON object")
    report = write_shadow_performance_report(
        paths.signals_dir / "shadow",
        cast("dict[str, list[dict[str, Any]]]", price_data),
        output or (paths.state_dir / "shadow_performance.json"),
    )
    report["promotion"] = write_promotion_report(
        paths.state_dir / "promotion.json",
        paths.signals_dir / "shadow",
        paths.state_dir / "health.json",
        settings.promotion,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@promotion_app.command("status")
def promotion_status(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    settings, paths = _load(config)
    report = write_promotion_report(
        paths.state_dir / "promotion.json",
        paths.signals_dir / "shadow",
        paths.state_dir / "health.json",
        settings.promotion,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
