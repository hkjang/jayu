from __future__ import annotations

import json
import random

from collections.abc import Mapping
from datetime import UTC, date as date_type, datetime
from pathlib import Path
from typing import Annotated, Any, cast

import typer
import numpy as np

from .account_attribution import write_account_attribution_report
from . import engine
from .allocation_simulator import write_allocation_preview_report
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
from .data_lineage import write_data_lineage_report
from .dashboard import serve_dashboard
from .failure_codes import FailureCode, ProcessExitCode, process_exit_code
from .failure_patterns import write_failure_patterns_report
from .io import atomic_write_json, file_sha256, read_json, stable_hash
from .monitoring import classify_failure, compute_health_score, prune_runs, update_health
from .notifications import KakaoNotifier, build_signal_message
from .operational_status import (
    build_operational_status,
    latest_run_dir,
    write_operational_status,
    write_operational_status_bundle,
)
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
from .recovery_guide import write_recovery_guide
from .reports import (
    parameter_importance,
    write_cost_sensitivity_report,
    write_html_report,
    write_markdown_report,
    write_shadow_performance_report,
    write_signal_performance_report,
)
from .risk import apply_data_trust, apply_portfolio_risk, risk_explanation
from .risk_ledger import record_portfolio_snapshot
from .run_evidence import write_run_evidence_report
from .runtime_lock import OperationalRunConflict, OperationalRunLock
from .safety import (
    SafetyGateError,
    enforce_live_price_safety,
    enforce_research_universe,
    enforce_shadow_promotion,
    evaluate_shadow_promotion,
    write_promotion_report,
)
from .settings import ExecutionMode, Settings, load_settings
from .safety_verdict import write_safety_verdict
from .session_replay import write_session_replay_report
from .signal_outcome import write_signal_outcome_report
from .signal_replay import write_signal_replay_artifact
from .signal_stability import write_signal_stability_report
from .stock_lifecycle import write_stock_lifecycle_report
from .strategy_space import load_strategy_spaces, validate_strategy_spaces
from .survivorship import audit_survivorship
from .toss import TOSS_GET_ENDPOINTS, TossCredentialsError, TossInvestClient


app = typer.Typer(no_args_is_help=True, help="Jayu stock research automation")
portfolio_app = typer.Typer(no_args_is_help=True, help="Portfolio maintenance and risk")
report_app = typer.Typer(no_args_is_help=True, help="Run and signal reports")
experiments_app = typer.Typer(help="Experiment registry and comparisons")
promotion_app = typer.Typer(no_args_is_help=True, help="Shadow-to-live promotion")
toss_app = typer.Typer(no_args_is_help=True, help="Read-only Toss Securities Open API")
run_app = typer.Typer(no_args_is_help=True, help="Run management and comparison")
backup_app = typer.Typer(no_args_is_help=True, help="System backup and restore management")
notebook_app = typer.Typer(no_args_is_help=True, help="Jupyter Notebook export and research tools")
goal_app = typer.Typer(no_args_is_help=True, help="Investment goal planning")
cashflow_app = typer.Typer(no_args_is_help=True, help="Monthly cashflow planning")
coach_app = typer.Typer(no_args_is_help=True, help="Investor coaching and diet mode")

app.add_typer(portfolio_app, name="portfolio")
app.add_typer(report_app, name="report")
app.add_typer(experiments_app, name="experiments")
app.add_typer(promotion_app, name="promotion")
app.add_typer(toss_app, name="toss")
app.add_typer(run_app, name="run")
app.add_typer(backup_app, name="backup")
app.add_typer(notebook_app, name="notebook")
app.add_typer(goal_app, name="goal")
app.add_typer(cashflow_app, name="cashflow")
app.add_typer(coach_app, name="coach")


@app.command()
def dashboard(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8765,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Serve the read-only Jayu operations console."""
    _, paths = _load(config)
    serve_dashboard(paths, host=host, port=port, open_browser=open_browser)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load(config: Path | None) -> tuple[Settings, RuntimePaths]:
    root = _project_root()
    config_path = config or root / "config.json"
    settings = load_settings(config_path if config_path.exists() else None)
    paths = settings.runtime_paths(root)
    paths.ensure_runtime_dirs()
    return settings, paths


def _secret_value(value: Any) -> str | None:
    return value.get_secret_value() if value else None


def _echo_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _toss_client(config: Path | None) -> TossInvestClient:
    settings, _ = _load(config)
    api_key = _secret_value(settings.toss_api_key)
    secret_key = _secret_value(settings.toss_secret_key)
    if not api_key or not secret_key:
        raise typer.BadParameter(
            "Toss Open API requires TS_API_KEY and TS_SECRET_KEY in .env or environment"
        )
    return TossInvestClient(
        api_key,
        secret_key,
        account=_secret_value(settings.toss_account),
        policy=provider_policy(settings, "toss"),
        auth_style=settings.toss_oauth_auth_style,
    )


def _run_toss(config: Path | None, action: Any) -> None:
    try:
        _echo_json(action(_toss_client(config)))
    except (TossCredentialsError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


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
        cross_validate=(
            settings.data.cross_validation_mode != "off"
            and bool(settings.data.cross_validation_providers)
        ),
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
    mapping = load_portfolio_mapping(paths.portfolio_mapping_file)
    fx_rates = get_fx_rates(["USD", "EUR", "JPY", "HKD"])

    toss_snap_file = paths.state_dir / "toss_account_snapshot.json"
    toss_positions = None
    toss_cash_total = None
    toss_used = False

    if toss_snap_file.exists():
        try:
            toss_evidence = read_json(toss_snap_file)
            if toss_evidence and not toss_evidence.get("errors", {}).get("holdings") and not toss_evidence.get("errors", {}).get("buying_power_krw"):
                from .toss import load_live_toss_positions
                toss_positions = load_live_toss_positions(toss_evidence, mapping, fx_rates["USD"])
                toss_cash_krw = float(toss_evidence.get("buying_power_krw", {}).get("amount") or toss_evidence.get("buying_power_krw", {}).get("buyingPower") or 0.0)
                toss_cash_usd = float(toss_evidence.get("buying_power_usd", {}).get("amount") or toss_evidence.get("buying_power_usd", {}).get("buyingPower") or 0.0)
                toss_cash_total = toss_cash_krw + (toss_cash_usd * fx_rates["USD"])
                toss_used = True
        except Exception:
            pass

    if toss_used and toss_positions is not None:
        portfolio = portfolio_summary(
            toss_positions,
            account_value_krw=None,
            cash_balance_krw=toss_cash_total,
        )
    elif paths.portfolio_file.exists():
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
    else:
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
        return apply_data_trust(
            evaluated,
            price_trust=context.price_trust,
            reference_audits=context.reference_audits,
            event_notes=context.event_notes,
            require_verified_price=settings.data.require_verified_price_for_eligibility,
            reference_conflict_policy=settings.data.reference_conflict_policy,
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

    import time
    decision_tree = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "portfolio_source": "toss_live" if toss_used else "portfolio_csv",
        "toss_evidence_attached": toss_used,
        "cash_balance_krw": portfolio.get("cash_balance_krw"),
        "account_value_krw": portfolio.get("account_value_krw"),
        "positions": [pos["ticker"] for pos in portfolio.get("positions", [])],
        "signals_eligibility": {
            ticker: {
                "eligible": sig.get("eligible"),
                "approved_pct": sig.get("approved_position_pct"),
                "violations": sig.get("risk", {}).get("violations", []) if isinstance(sig.get("risk"), dict) else [],
            }
            for ticker, sig in evaluated.items()
        }
    }
    atomic_write_json(paths.state_dir / "risk_decision_tree.json", decision_tree)

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
                metrics = regime_data.get(key)
                if not isinstance(metrics, dict):
                    continue
                value = metrics.get("fitness")
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


def _output_policy(
    *,
    replay: bool,
    shadow_mode: bool,
    paper_mode: bool = False,
) -> dict[str, bool]:
    non_operational = shadow_mode or paper_mode
    return {
        "persist_state": not replay,
        "persist_signal": False,
        "write_primary_signal": not replay and not non_operational,
        "update_health": not replay,
        "prune_runs": not replay,
    }


def _enforce_inline_notification_readiness(
    verdict: Mapping[str, Any],
    *,
    health_score: int,
    min_health_score: int,
) -> None:
    if verdict.get("overall") != "approved":
        raise SafetyGateError(
            FailureCode.SAFETY_VERDICT_BLOCKED,
            [f"safety verdict must be approved, got {verdict.get('overall', 'unknown')}"],
        )
    if health_score < min_health_score:
        raise SafetyGateError(
            FailureCode.HEALTH_SCORE_LOW,
            [f"health score {health_score} is below required {min_health_score}"],
        )


def _update_health_and_operational_status(
    paths: RuntimePaths,
    settings: Settings,
    *,
    run_id: str,
    status: str,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
    failure_code: str | None = None,
) -> dict[str, Any]:
    update_health(
        paths.state_dir / "health.json",
        run_id=run_id,
        status=status,
        summary=summary,
        error=error,
        failure_code=failure_code,
    )
    return write_operational_status_bundle(paths, settings)


def _write_signal_publication_status(
    paths: RuntimePaths,
    *,
    run_id: str,
    signal_date: str,
    mode: str,
    status: str,
    signal_hash: str | None = None,
    content_hash: str | None = None,
    safety_verdict: str | None = None,
    failure_code: str | None = None,
) -> dict[str, Any]:
    payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "signal_date": signal_date,
        "mode": mode,
        "status": status,
        "signal_hash": signal_hash,
        "content_hash": content_hash,
        "safety_verdict": safety_verdict,
        "failure_code": failure_code,
    }
    atomic_write_json(paths.signal_status_file, payload)
    return payload


def _publish_primary_signal(
    paths: RuntimePaths,
    signals: dict[str, Any],
    *,
    run_id: str,
    signal_date: str,
    mode: str,
    signal_hash: str,
    verdict: Mapping[str, Any],
    health_score: int,
    min_health_score: int,
) -> dict[str, Any]:
    overall = verdict.get("overall")
    if overall == "blocked":
        raise SafetyGateError(
            FailureCode.SAFETY_VERDICT_BLOCKED,
            ["blocked safety verdict prevents primary signal publication"],
        )
    if mode == "live":
        _enforce_inline_notification_readiness(
            verdict,
            health_score=health_score,
            min_health_score=min_health_score,
        )
    atomic_write_json(paths.signal_file, signals)
    content_hash = stable_hash(signals)
    return _write_signal_publication_status(
        paths,
        run_id=run_id,
        signal_date=signal_date,
        mode=mode,
        status="published",
        signal_hash=signal_hash,
        content_hash=content_hash,
        safety_verdict=str(overall or "unknown"),
    )


def _load_published_signal(
    paths: RuntimePaths,
    *,
    signal_date: str,
) -> dict[str, Any]:
    before = read_json(paths.signal_status_file, default={})
    before_map = before if isinstance(before, dict) else {}
    if before_map.get("status") != "published" or before_map.get("signal_date") != signal_date:
        raise SafetyGateError(
            FailureCode.SIGNAL_PUBLICATION_MISSING,
            ["primary signal publication is not approved for the requested date"],
        )
    signals = read_json(paths.signal_file, default={})
    if not isinstance(signals, dict):
        raise SafetyGateError(
            FailureCode.SIGNAL_PUBLICATION_INVALID,
            ["primary signal payload is not a JSON object"],
        )
    after = read_json(paths.signal_status_file, default={})
    if before != after:
        raise SafetyGateError(
            FailureCode.SIGNAL_PUBLICATION_INVALID,
            ["primary signal publication changed while it was being read"],
        )
    if before_map.get("content_hash") != stable_hash(signals):
        raise SafetyGateError(
            FailureCode.SIGNAL_PUBLICATION_INVALID,
            ["primary signal content hash does not match its publication record"],
        )
    return signals


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
    execution_mode: ExecutionMode | None = None,
) -> None:
    settings, paths = _load(config)
    overrides: dict[str, Any] = {}
    if tickers:
        overrides["tickers"] = tickers
    if runs is not None:
        overrides["sim_runs"] = runs
    if seed is not None:
        overrides["random_seed"] = seed
    if execution_mode is not None:
        overrides["mode"] = execution_mode
    elif not optimize and settings.mode not in {"signal", "shadow", "paper", "live"}:
        overrides["mode"] = "signal"
    if overrides:
        settings = Settings.model_validate({**settings.model_dump(), **overrides})
    shadow_mode = settings.mode == "shadow"
    paper_mode = settings.mode == "paper"
    output_policy = _output_policy(
        replay=replay,
        shadow_mode=shadow_mode,
        paper_mode=paper_mode,
    )
    signal_date = replay_date or date_type.today().isoformat()
    effective_notify = bool(notify_user and settings.mode == "live" and not replay)
    runtime_lock: OperationalRunLock | None = None
    if settings.mode in {"signal", "shadow", "paper", "live"} and not replay:
        runtime_lock = OperationalRunLock(
            paths.operational_lock_file,
            command=command,
            mode=settings.mode,
            timeout_minutes=settings.operational_lock_timeout_minutes,
        )
        try:
            runtime_lock.acquire()
        except OperationalRunConflict as exc:
            typer.echo(f"error: {exc.code.value}: {exc}", err=True)
            raise typer.Exit(code=process_exit_code(exc.code)) from exc
    if output_policy["prune_runs"]:
        prune_runs(
            paths.runs_dir,
            max_age_days=settings.run_retention_days,
            max_runs=settings.run_retention_count,
        )
    random.seed(settings.random_seed)
    np.random.seed(settings.random_seed)
    try:
        context = RunContext.create(paths, settings, command, verbose=verbose)
        registry = ExperimentRegistry(paths.state_dir / "experiments.sqlite")
        registry.start(context)
    except Exception:
        if runtime_lock is not None:
            runtime_lock.release()
        raise
    if output_policy["write_primary_signal"] and settings.mode in {"signal", "live"}:
        _write_signal_publication_status(
            paths,
            run_id=context.run_id,
            signal_date=signal_date,
            mode=settings.mode,
            status="pending",
        )
        paths.signal_file.unlink(missing_ok=True)
    try:
        _record_signal_inputs(context, paths)
        provider_registry = build_provider_registry(settings, paths.cache_dir)
        if optimize:
            research_safety = enforce_research_universe(settings)
            research_safety_path = context.run_dir / "research_universe_safety.json"
            atomic_write_json(research_safety_path, research_safety)
            context.record_artifact(research_safety_path)
        if settings.mode in {"signal", "shadow", "paper", "live"} and not replay:
            live_price_safety = enforce_live_price_safety(settings, provider_registry)
            live_price_path = context.run_dir / "price_safety.json"
            atomic_write_json(live_price_path, live_price_safety)
            context.record_artifact(live_price_path)
        if settings.mode in {"paper", "live"} and not replay and not optimize:
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
        if shadow_mode or paper_mode:
            signals = _annotate_shadow_signals(signals, reason=f"mode={settings.mode}")
        ensure_contract("signal_dataframe", validate_signal_contract(signals))
        if shadow_mode:
            shadow_path = paths.signals_dir / "shadow" / f"{signal_date}.json"
            atomic_write_json(shadow_path, signals)
        if paper_mode:
            paper_path = paths.signals_dir / "paper" / f"{signal_date}.json"
            atomic_write_json(paper_path, signals)
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
        importance_path = context.run_dir / "parameter_importance.json"
        atomic_write_json(importance_path, parameter_importance(best_all))
        context.record_artifact(importance_path)
        context.write_manifest(status="success", result=summary)
        if shadow_mode:
            promotion = write_promotion_report(
                paths.state_dir / "promotion.json",
                paths.signals_dir / "shadow",
                paths.state_dir / "health.json",
                settings.promotion,
            )
            promotion_path = context.run_dir / "promotion.json"
            atomic_write_json(promotion_path, promotion)
            context.record_artifact(promotion_path)
        verdict = write_safety_verdict(context.run_dir)
        summary["safety_verdict"] = verdict["overall"]
        safety_path = context.run_dir / "safety_verdict.json"
        context.record_artifact(safety_path)
        context.write_manifest(status="success", result=summary)
        if output_policy["write_primary_signal"]:
            publication = _publish_primary_signal(
                paths,
                signals,
                run_id=context.run_id,
                signal_date=signal_date,
                mode=settings.mode,
                signal_hash=signal_replay["signal_hash"],
                verdict=verdict,
                health_score=health_score,
                min_health_score=settings.promotion.min_health_score,
            )
            summary["signal_publication"] = publication["status"]
            publication_path = context.run_dir / "signal_publication.json"
            atomic_write_json(publication_path, publication)
            context.record_artifact(publication_path)
            context.write_manifest(status="success", result=summary)
        if effective_notify:
            _enforce_inline_notification_readiness(
                verdict,
                health_score=health_score,
                min_health_score=settings.promotion.min_health_score,
            )
            notification_result = KakaoNotifier(settings, paths).send(
                build_signal_message(
                    signals,
                    max_chars=settings.notification_message_limit,
                    health_score=health_score,
                )
            )
            summary["notification"] = notification_result
            notification_path = context.run_dir / "notification.json"
            atomic_write_json(notification_path, notification_result)
            context.record_artifact(notification_path)
            context.write_manifest(status="success", result=summary)
        report_path = write_html_report(context.run_dir)
        context.record_artifact(report_path)
        markdown_path = write_markdown_report(context.run_dir)
        context.record_artifact(markdown_path)
        context.write_manifest(status="success", result=summary)
        if output_policy["update_health"]:
            _update_health_and_operational_status(
                paths,
                settings,
                run_id=context.run_id,
                status="success",
                summary=summary,
            )
        registry.finish(context, status="success", result=summary)
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
        try:
            write_safety_verdict(context.run_dir)
            context.record_artifact(context.run_dir / "safety_verdict.json")
            context.write_manifest(
                status="failed",
                error=str(exc),
                failure_code=failure_code,
            )
        except Exception:
            context.logger.exception(
                "failed to write safety verdict after command failure",
                extra={
                    "run_id": context.run_id,
                    "event": "safety_verdict_refresh_failure",
                    "error_code": failure_code,
                },
            )
        registry.finish(
            context,
            status="failed",
            error=str(exc),
            failure_code=failure_code,
        )
        if output_policy["update_health"]:
            try:
                _update_health_and_operational_status(
                    paths,
                    settings,
                    run_id=context.run_id,
                    status="failed",
                    error=str(exc),
                    failure_code=failure_code,
                )
            except Exception:
                context.logger.exception(
                    "failed to refresh operational status after command failure",
                    extra={
                        "run_id": context.run_id,
                        "event": "operational_status_refresh_failure",
                        "error_code": failure_code,
                    },
                )
        if output_policy["write_primary_signal"] and settings.mode in {"signal", "live"}:
            try:
                publication = _write_signal_publication_status(
                    paths,
                    run_id=context.run_id,
                    signal_date=signal_date,
                    mode=settings.mode,
                    status="blocked",
                    failure_code=failure_code,
                )
                publication_path = context.run_dir / "signal_publication.json"
                atomic_write_json(publication_path, publication)
                context.record_artifact(publication_path)
                context.write_manifest(
                    status="failed",
                    error=str(exc),
                    failure_code=failure_code,
                )
            except Exception:
                context.logger.exception(
                    "failed to mark primary signal publication as blocked",
                    extra={
                        "run_id": context.run_id,
                        "event": "signal_publication_status_failure",
                        "error_code": failure_code,
                    },
                )
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=process_exit_code(failure_code)) from exc
    finally:
        if runtime_lock is not None:
            runtime_lock.release()


@app.command("validate-config")
def validate_config(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    mode: Annotated[str | None, typer.Option("--mode")] = None,
) -> None:
    settings, paths = _load(config)
    if mode is not None:
        settings = Settings.model_validate({**settings.model_dump(), "mode": mode})
    strategy_space_audit = validate_strategy_spaces(load_strategy_spaces())
    provider_registry = build_provider_registry(settings, paths.cache_dir)
    provider_audit = provider_configuration_audit(settings, provider_registry)
    mode_errors: list[str] = []
    survivorship_audit: dict[str, Any]
    try:
        survivorship_audit = audit_survivorship(settings).to_dict()
    except ValueError as exc:
        survivorship_audit = {
            "policy": settings.universe.policy,
            "valid": False,
            "error": str(exc),
        }
    if settings.mode in {"research", "backtest"}:
        if settings.universe.policy != "strict":
            mode_errors.append(f"{settings.mode} mode requires universe.policy=strict")
        if survivorship_audit.get("valid") is not True:
            mode_errors.append("research universe failed survivorship validation")
    promotion_audit: dict[str, Any] | None = None
    if settings.mode in {"shadow", "paper", "live"}:
        promotion_audit = evaluate_shadow_promotion(
            paths.signals_dir / "shadow",
            paths.state_dir / "health.json",
            settings.promotion,
        )
        if settings.mode in {"paper", "live"} and promotion_audit.get("eligible") is not True:
            mode_errors.append(f"{settings.mode} mode requires an eligible shadow promotion")
    if not provider_audit["valid"] or mode_errors:
        errors = [str(error) for error in provider_audit["errors"]] + mode_errors
        raise ValueError("configuration is invalid: " + "; ".join(errors))
    typer.echo(json.dumps(settings.public_dict(), ensure_ascii=False, indent=2))
    typer.echo(
        json.dumps(
            {
                "strategy_space_audit": strategy_space_audit,
                "provider_audit": provider_audit,
                "survivorship_audit": survivorship_audit,
                "promotion_audit": promotion_audit,
                "execution_mode": settings.mode,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    typer.echo(f"state_dir={paths.state_dir}")
    typer.echo("configuration is valid")


@app.command("status")
def status(
    config: Annotated[Path | None, typer.Option("--config")] = None,
    write: Annotated[bool, typer.Option("--write/--no-write")] = True,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    markdown: Annotated[bool, typer.Option("--markdown/--no-markdown")] = True,
    markdown_output: Annotated[Path | None, typer.Option("--markdown-output")] = None,
    brief: Annotated[bool, typer.Option("--brief/--json")] = False,
    fail_on_not_ready: Annotated[
        bool,
        typer.Option("--fail-on-not-ready/--no-fail-on-not-ready"),
    ] = False,
) -> None:
    settings, paths = _load(config)
    if write and markdown:
        report = write_operational_status_bundle(
            paths,
            settings,
            output=output,
            markdown_output=markdown_output,
        )
    elif write:
        report = write_operational_status(paths, settings, output=output)
    else:
        report = build_operational_status(paths, settings)
    if brief:
        typer.echo(_format_status_brief(report))
    else:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if fail_on_not_ready and report.get("live_ready") is not True:
        raise typer.Exit(code=ProcessExitCode.SAFETY_GATE_FAILED)


def _format_status_brief(report: dict[str, Any]) -> str:
    summary = report.get("readiness_summary") if isinstance(report, dict) else None
    summary_map = summary if isinstance(summary, dict) else {}
    latest = report.get("latest_run") if isinstance(report, dict) else None
    latest_map = latest if isinstance(latest, dict) else {}
    promotion = report.get("promotion") if isinstance(report, dict) else None
    promotion_map = promotion if isinstance(promotion, dict) else {}
    reason_codes = summary_map.get("reason_codes", [])
    actions = summary_map.get("next_actions", [])
    lines = [
        f"status: {summary_map.get('overall', 'unknown')}",
        f"message: {summary_map.get('message', 'not evaluated')}",
        f"health: {report.get('health_score')} ({report.get('health_status')})",
        (
            "latest_run: "
            f"{latest_map.get('run_id', 'none')} "
            f"safety={latest_map.get('safety_verdict')} "
            f"age_hours={latest_map.get('run_age_hours')}"
        ),
        f"promotion: {'eligible' if promotion_map.get('eligible') is True else 'blocked'}",
    ]
    if isinstance(reason_codes, list) and reason_codes:
        lines.append("reason_codes: " + ", ".join(str(code) for code in reason_codes))
    if isinstance(actions, list) and actions:
        lines.append("next_actions:")
        lines.extend(f"- {action}" for action in actions)
    return "\n".join(lines)


@app.command()
def simulate(
    ticker: Annotated[list[str] | None, typer.Option("--ticker", "-t")] = None,
    runs: Annotated[int | None, typer.Option("--runs", min=1)] = None,
    notify: Annotated[bool, typer.Option("--notify/--no-notify")] = False,
    refresh_data: Annotated[bool, typer.Option("--refresh-data")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
    seed: Annotated[int | None, typer.Option("--seed", min=0)] = None,
    mode: Annotated[str, typer.Option("--mode")] = "research",
) -> None:
    if mode not in {"research", "backtest"}:
        raise typer.BadParameter("simulate --mode must be research or backtest")
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
        execution_mode=cast(ExecutionMode, mode),
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
    mode: Annotated[str | None, typer.Option("--mode")] = None,
    attach_toss_readiness: Annotated[bool, typer.Option("--attach-toss-readiness")] = False,
) -> None:
    if mode is not None and mode not in {"signal", "shadow", "paper", "live"}:
        raise typer.BadParameter("signal --mode must be signal, shadow, paper, or live")
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
        execution_mode=cast(ExecutionMode, mode) if mode is not None else None,
    )
    if attach_toss_readiness:
        client = _toss_client(config)
        _, paths = _load(config)
        from .toss import attach_toss_readiness_to_signals
        res = attach_toss_readiness_to_signals(client, paths)
        _echo_json(res)


@app.command()
def notify(
    channel: Annotated[str, typer.Option("--channel")] = "kakao",
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    if channel != "kakao":
        raise typer.BadParameter("supported channel: kakao")
    settings, paths = _load(config)
    if settings.mode != "live":
        raise typer.BadParameter("notify requires mode=live")
    readiness = write_operational_status_bundle(paths, settings)
    if readiness.get("live_ready") is not True:
        typer.echo("error: operational readiness check failed", err=True)
        typer.echo(_format_status_brief(readiness), err=True)
        raise typer.Exit(code=ProcessExitCode.SAFETY_GATE_FAILED)
    try:
        signals = _load_published_signal(
            paths,
            signal_date=date_type.today().isoformat(),
        )
    except SafetyGateError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=process_exit_code(exc.code)) from exc
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


@portfolio_app.command("reconcile-toss")
def portfolio_reconcile_toss(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Reconcile portfolio.csv with Toss live holdings, showing differences and unmapped tickers."""
    settings, paths = _load(config)
    client = _toss_client(config)
    from .toss import reconcile_portfolio_with_toss
    report = reconcile_portfolio_with_toss(client, paths)
    _echo_json(report)


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
    left_verdict = read_json(left_artifact / "safety_verdict.json", default={})
    right_verdict = read_json(right_artifact / "safety_verdict.json", default={})
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
        "safety_verdict": _pair(
            _safety_verdict_status(left_verdict, left_result),
            _safety_verdict_status(right_verdict, right_result),
        ),
    }


def _pair(left: Any, right: Any) -> dict[str, Any]:
    return {"left": left, "right": right, "changed": left != right}


def _cost_status(cost_payload: Any, result: dict[str, Any]) -> Any:
    if isinstance(cost_payload, dict) and cost_payload.get("cost_survival_status"):
        return cost_payload.get("cost_survival_status")
    return result.get("cost_survival")


def _safety_verdict_status(verdict_payload: Any, result: dict[str, Any]) -> Any:
    if isinstance(verdict_payload, dict) and verdict_payload.get("overall"):
        return verdict_payload.get("overall")
    return result.get("safety_verdict")


def _comparison_table(comparison: dict[str, Any]) -> str:
    rows = ["field | left | right | changed", "--- | --- | --- | ---"]
    for field in (
        "config_hash",
        "data_hash",
        "signal_hash",
        "validation_status",
        "cost_survival",
        "risk_status",
        "safety_verdict",
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
    markdown: Annotated[bool, typer.Option("--markdown/--no-markdown")] = True,
) -> None:
    output = write_html_report(run)
    typer.echo(str(output))
    if markdown:
        typer.echo(str(write_markdown_report(run)))


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


@report_app.command("signal-outcome")
def report_signal_outcome(
    price_json: Annotated[Path, typer.Option("--price-json", exists=True)],
    signals: Annotated[Path | None, typer.Option("--signals")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    signal_path = signals or paths.signal_file
    output_path = output or (paths.state_dir / "signal_outcome.json")
    signal_data = read_json(signal_path, default={})
    price_data = read_json(price_json, default={})
    if not isinstance(signal_data, dict) or not isinstance(price_data, dict):
        raise typer.BadParameter("signals and price-json must be JSON objects")
    report = write_signal_outcome_report(
        cast("dict[str, dict[str, Any]]", signal_data),
        cast("dict[str, list[dict[str, Any]]]", price_data),
        output_path,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("stock-lifecycle")
def report_stock_lifecycle(
    signals: Annotated[Path | None, typer.Option("--signals")] = None,
    holdings_json: Annotated[Path | None, typer.Option("--holdings-json", exists=True)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    signal_path = signals or paths.signal_file
    output_path = output or (paths.state_dir / "stock_lifecycle.json")
    signal_data = read_json(signal_path, default={})
    holdings_data = read_json(holdings_json, default=[]) if holdings_json else []
    if not isinstance(signal_data, dict):
        raise typer.BadParameter("signals must be a JSON object")
    report = write_stock_lifecycle_report(
        cast("dict[str, dict[str, Any]]", signal_data),
        cast("list[dict[str, Any]] | dict[str, Any]", holdings_data),
        output_path,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("signal-stability")
def report_signal_stability(
    output: Annotated[Path | None, typer.Option("--output")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 240,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    report = write_signal_stability_report(
        paths.runs_dir,
        output or (paths.state_dir / "signal_stability.json"),
        limit=limit,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("allocation-preview")
def report_allocation_preview(
    order_plan: Annotated[Path | None, typer.Option("--order-plan", exists=True)] = None,
    holdings_json: Annotated[Path | None, typer.Option("--holdings-json", exists=True)] = None,
    signals: Annotated[Path | None, typer.Option("--signals")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    cash_krw: Annotated[float | None, typer.Option("--cash-krw")] = None,
    usd_krw: Annotated[float | None, typer.Option("--usd-krw")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    settings, paths = _load(config)
    order_plan_path = order_plan or (paths.state_dir / "order_plan.json")
    signal_path = signals or paths.signal_file
    default_holdings_path = paths.state_dir / "toss_account_snapshot.json"
    selected_holdings_path = holdings_json or (
        default_holdings_path if default_holdings_path.exists() else None
    )
    order_plan_data = read_json(order_plan_path, default={})
    signal_data = read_json(signal_path, default={})
    holdings_data = read_json(selected_holdings_path, default=[]) if selected_holdings_path else []
    fx_rates = {"KRW": 1.0}
    if usd_krw is not None:
        fx_rates["USD"] = usd_krw
    if not isinstance(order_plan_data, (dict, list)):
        raise typer.BadParameter("order-plan must be a JSON object or array")
    if not isinstance(signal_data, dict):
        raise typer.BadParameter("signals must be a JSON object")
    if not isinstance(holdings_data, (dict, list)):
        raise typer.BadParameter("holdings-json must be a JSON object or array")
    report = write_allocation_preview_report(
        cast("dict[str, Any] | list[dict[str, Any]]", order_plan_data),
        cast("dict[str, Any] | list[dict[str, Any]]", holdings_data),
        output or (paths.state_dir / "allocation_preview.json"),
        signals=cast("dict[str, Any]", signal_data),
        cash_krw=cash_krw,
        settings=settings,
        fx_rates=fx_rates,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("account-attribution")
def report_account_attribution(
    previous_json: Annotated[Path, typer.Option("--previous-json", exists=True)],
    current_json: Annotated[Path, typer.Option("--current-json", exists=True)],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    previous_data = read_json(previous_json, default={})
    current_data = read_json(current_json, default={})
    if not isinstance(previous_data, (dict, list)):
        raise typer.BadParameter("previous-json must be a JSON object or array")
    if not isinstance(current_data, (dict, list)):
        raise typer.BadParameter("current-json must be a JSON object or array")
    report = write_account_attribution_report(
        cast("dict[str, Any] | list[dict[str, Any]]", previous_data),
        cast("dict[str, Any] | list[dict[str, Any]]", current_data),
        output or (paths.state_dir / "account_attribution.json"),
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("recovery-guide")
def report_recovery_guide(
    run: Annotated[Path | None, typer.Option("--run", exists=True, file_okay=False)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    selected_run = run or latest_run_dir(paths.runs_dir)
    manifest = read_json(selected_run / "manifest.json", default={}) if selected_run else {}
    verdict = read_json(selected_run / "safety_verdict.json", default={}) if selected_run else {}
    operational_status = read_json(paths.state_dir / "operational_status.json", default={})
    if not isinstance(manifest, dict):
        raise typer.BadParameter("manifest.json must be a JSON object")
    if not isinstance(verdict, dict):
        raise typer.BadParameter("safety_verdict.json must be a JSON object")
    if not isinstance(operational_status, dict):
        raise typer.BadParameter("operational_status.json must be a JSON object")
    report = write_recovery_guide(
        output or (paths.state_dir / "recovery_guide.json"),
        manifest=cast("dict[str, Any]", manifest),
        verdict=cast("dict[str, Any]", verdict),
        operational_status=cast("dict[str, Any]", operational_status),
        run_dir=selected_run,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("session-replay")
def report_session_replay(
    run: Annotated[Path | None, typer.Option("--run", exists=True, file_okay=False)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    selected_run = run or latest_run_dir(paths.runs_dir)
    report = write_session_replay_report(
        selected_run,
        output or (paths.state_dir / "session_replay.json"),
        project_root=paths.project_root,
        state_dir=paths.state_dir,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("data-lineage")
def report_data_lineage(
    run: Annotated[Path | None, typer.Option("--run", exists=True, file_okay=False)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    selected_run = run or latest_run_dir(paths.runs_dir)
    report = write_data_lineage_report(
        selected_run,
        output or (paths.state_dir / "data_lineage.json"),
        project_root=paths.project_root,
        state_dir=paths.state_dir,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("failure-patterns")
def report_failure_patterns(
    output: Annotated[Path | None, typer.Option("--output")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    report = write_failure_patterns_report(
        paths.runs_dir,
        output or (paths.state_dir / "failure_patterns.json"),
        limit=limit,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("run-evidence")
def report_run_evidence(
    run: Annotated[Path | None, typer.Option("--run", exists=True, file_okay=False)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _, paths = _load(config)
    selected_run = run or latest_run_dir(paths.runs_dir)
    report = write_run_evidence_report(
        selected_run,
        output or (paths.state_dir / "run_evidence.json"),
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


@promotion_app.command("check")
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


@toss_app.command("doctor")
def toss_doctor(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Diagnose Toss credentials and connection status, showing formatting report."""
    settings, paths = _load(config)
    client = _toss_client(config)
    from .toss import doctor_diagnose
    report = doctor_diagnose(client, paths)
    _echo_json(report)


@toss_app.command("endpoints")
def toss_endpoints(
    sync_check: Annotated[bool, typer.Option("--sync-check")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """List implemented Toss Open API GET endpoints, with optional sync status check."""
    if sync_check:
        settings, paths = _load(config)
        client = _toss_client(config)
        from .toss import sync_endpoints
        report = sync_endpoints(client, paths)
        _echo_json(report)
    else:
        _echo_json(
            [
                {
                    "operation_id": endpoint.operation_id,
                    "method": "GET",
                    "path": endpoint.path,
                    "requires_account": endpoint.requires_account,
                }
                for endpoint in TOSS_GET_ENDPOINTS
            ]
        )


@toss_app.command("snapshot")
def toss_snapshot(
    redact: Annotated[bool, typer.Option("--redact/--no-redact")] = True,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Query live account metadata, balances, and calendar, and create snapshot."""
    settings, paths = _load(config)
    client = _toss_client(config)
    from .toss import create_snapshot
    snapshot = create_snapshot(client, paths, redact=redact)
    _echo_json(snapshot)



@toss_app.command("orderbook")
def toss_orderbook(
    symbol: Annotated[str, typer.Option("--symbol")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.orderbook(symbol))


@toss_app.command("prices")
def toss_prices(
    symbols: Annotated[str, typer.Option("--symbols", help="Comma-separated symbols")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.prices(symbols))


@toss_app.command("trades")
def toss_trades(
    symbol: Annotated[str, typer.Option("--symbol")],
    count: Annotated[int, typer.Option("--count", min=1, max=50)] = 50,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.trades(symbol, count=count))


@toss_app.command("price-limits")
def toss_price_limits(
    symbol: Annotated[str, typer.Option("--symbol")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.price_limits(symbol))


@toss_app.command("candles")
def toss_candles(
    symbol: Annotated[str, typer.Option("--symbol")],
    interval: Annotated[str, typer.Option("--interval")] = "1d",
    count: Annotated[int, typer.Option("--count", min=1, max=200)] = 100,
    before: Annotated[str | None, typer.Option("--before")] = None,
    adjusted: Annotated[bool, typer.Option("--adjusted/--raw")] = True,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(
        config,
        lambda client: client.candles(
            symbol,
            interval=cast("Any", interval),
            count=count,
            before=before,
            adjusted=adjusted,
        ),
    )


@toss_app.command("stocks")
def toss_stocks(
    symbols: Annotated[str, typer.Option("--symbols", help="Comma-separated symbols")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.stocks(symbols))


@toss_app.command("stock-warnings")
def toss_stock_warnings(
    symbol: Annotated[str, typer.Option("--symbol")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.stock_warnings(symbol))


@toss_app.command("exchange-rate")
def toss_exchange_rate(
    base_currency: Annotated[str, typer.Option("--base-currency")],
    quote_currency: Annotated[str, typer.Option("--quote-currency")],
    date_time: Annotated[str | None, typer.Option("--date-time")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(
        config,
        lambda client: client.exchange_rate(
            base_currency=base_currency,
            quote_currency=quote_currency,
            date_time=date_time,
        ),
    )


@toss_app.command("market-calendar")
def toss_market_calendar(
    region: Annotated[str, typer.Option("--region", help="KR or US")],
    date: Annotated[str | None, typer.Option("--date")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    region_code = region.strip().upper()
    if region_code == "KR":
        _run_toss(config, lambda client: client.market_calendar_kr(date=date))
    elif region_code == "US":
        _run_toss(config, lambda client: client.market_calendar_us(date=date))
    else:
        raise typer.BadParameter("region must be KR or US")


@toss_app.command("accounts")
def toss_accounts(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.accounts())


@toss_app.command("holdings")
def toss_holdings(
    account: Annotated[str | None, typer.Option("--account")] = None,
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.holdings(account=account, symbol=symbol))


@toss_app.command("orders")
def toss_orders(
    status: Annotated[str, typer.Option("--status", help="OPEN or CLOSED")],
    account: Annotated[str | None, typer.Option("--account")] = None,
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    from_date: Annotated[str | None, typer.Option("--from")] = None,
    to_date: Annotated[str | None, typer.Option("--to")] = None,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 20,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(
        config,
        lambda client: client.orders(
            status=cast("Any", status.strip().upper()),
            account=account,
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            cursor=cursor,
            limit=limit,
        ),
    )


@toss_app.command("order")
def toss_order(
    order_id: Annotated[str, typer.Option("--order-id")],
    account: Annotated[str | None, typer.Option("--account")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.order(order_id, account=account))


@toss_app.command("buying-power")
def toss_buying_power(
    currency: Annotated[str, typer.Option("--currency")],
    account: Annotated[str | None, typer.Option("--account")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.buying_power(currency=currency, account=account))


@toss_app.command("sellable-quantity")
def toss_sellable_quantity(
    symbol: Annotated[str, typer.Option("--symbol")],
    account: Annotated[str | None, typer.Option("--account")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.sellable_quantity(symbol, account=account))


@toss_app.command("commissions")
def toss_commissions(
    account: Annotated[str | None, typer.Option("--account")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    _run_toss(config, lambda client: client.commissions(account=account))


@run_app.command("compare-dashboard")
def compare_dashboard(
    left: Annotated[str, typer.Option("--left", help="이전/왼쪽 실행 ID (또는 'latest')")],
    right: Annotated[str, typer.Option("--right", help="현재/오른쪽 실행 ID (또는 'latest')")],
    format: Annotated[str, typer.Option("--format", help="출력 형식: markdown, json, both")] = "markdown",
    config: Annotated[Path | None, typer.Option("--config", help="설정 파일 경로")] = None,
) -> None:
    """두 실행(left vs right)의 설정, 데이터 품질, 신호, 리스크, 의사결정, 산출물 차이를 한국어로 비교합니다."""
    from .run_compare import compare_runs, generate_compare_markdown
    _, paths = _load(config)
    try:
        diff_data = compare_runs(paths, left, right)
    except Exception as e:
        typer.echo(f"오류: 비교를 수행할 수 없습니다 - {e}", err=True)
        raise typer.Exit(code=1)
        
    if format == "json":
        _echo_json(diff_data)
    elif format == "markdown":
        typer.echo(generate_compare_markdown(diff_data))
    else:
        # both
        typer.echo("=== JSON OUTPUT ===")
        _echo_json(diff_data)
        typer.echo("\n=== MARKDOWN OUTPUT ===")
        typer.echo(generate_compare_markdown(diff_data))


@backup_app.command("create")
def backup_create(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Create a new system backup."""
    settings, paths = _load(config)
    from .backup_manager import BackupManager
    manager = BackupManager(paths.project_root, paths.state_dir)
    try:
        zip_path, manifest = manager.create_backup()
        typer.echo(f"Backup created successfully: {zip_path.name}")
        typer.echo(f"SHA256: {manifest['zip_sha256']}")
    except Exception as e:
        typer.echo(f"Error creating backup: {e}", err=True)
        raise typer.Exit(code=1)


@backup_app.command("restore")
def backup_restore(
    file: Annotated[Path, typer.Argument(help="Path to the backup zip file")],
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run", help="Verify backup without extracting")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Restore system state from a backup."""
    settings, paths = _load(config)
    from .backup_manager import BackupManager
    manager = BackupManager(paths.project_root, paths.state_dir)
    try:
        report = manager.restore_backup(file, dry_run=dry_run)
        if dry_run:
            typer.echo("Dry-run verification completed.")
            typer.echo(f"Valid: {report['valid']}")
            typer.echo(f"Number of actions: {len(report['actions'])}")
            for action in report["actions"]:
                typer.echo(f" - {action['action']}: {action['path']} ({action['size']} bytes)")
            if report["errors"]:
                typer.echo("Errors found:", err=True)
                for err in report["errors"]:
                    typer.echo(f" - {err}", err=True)
        else:
            typer.echo(f"Backup restored successfully from {file.name}")
    except Exception as e:
        typer.echo(f"Error restoring backup: {e}", err=True)
        raise typer.Exit(code=1)


@notebook_app.command("export")
def notebook_export(
    run_id: Annotated[str, typer.Option("--run-id", help="The run ID to export")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Custom output notebook path")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Export a specific run's results into a Jupyter Notebook."""
    settings, paths = _load(config)
    from .notebook_export import NotebookExporter
    exporter = NotebookExporter(paths.project_root)
    try:
        out_path = exporter.export(run_id, output_file=str(output) if output else None)
        typer.echo(f"Jupyter Notebook exported successfully to: {out_path}")
    except Exception as e:
        typer.echo(f"Error exporting notebook: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("agent")
def agent_command(
    request: Annotated[str, typer.Argument(help="Korean natural language instruction")],
) -> None:
    """Ask the Jayu Agent to perform tasks using natural language."""
    from .agent_mode import JayuAgentMode
    JayuAgentMode().run_plan(request, auto_approve=True)


@app.command("mcp")
def mcp_command(
    action: Annotated[str, typer.Argument(help="Action to perform (start)")] = "start",
) -> None:
    """Start the Model Context Protocol (MCP) server for external AI agents."""
    if action != "start":
        raise typer.BadParameter("Supported action: start")
    from .jayu_mcp_server import JayuMcpServer
    server = JayuMcpServer()
    server.run()


# Investment Goal Planner Commands
@goal_app.command("set")
def goal_set(
    goal_id: Annotated[str, typer.Option("--id", help="Goal identifier")],
    name: Annotated[str, typer.Option("--name", help="Goal name")],
    target_amount: Annotated[float, typer.Option("--target-amount", help="Target money amount")],
    target_date: Annotated[str, typer.Option("--target-date", help="YYYY-MM-DD format")],
    current_amount: Annotated[float, typer.Option("--current-amount", help="Current starting money")],
    monthly_deposit: Annotated[float, typer.Option("--monthly-deposit", help="Monthly deposit money")],
    expected_return: Annotated[float, typer.Option("--expected-return", help="Expected annual return rate, e.g. 0.08")] = 0.08,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Set or update an investment goal."""
    _, paths = _load(config)
    from .investment_goal_planner import InvestmentGoalPlanner
    planner = InvestmentGoalPlanner(paths.project_root)
    goal = planner.set_goal(
        goal_id=goal_id,
        name=name,
        target_amount=target_amount,
        target_date=target_date,
        current_amount=current_amount,
        monthly_deposit=monthly_deposit,
        expected_return=expected_return
    )
    typer.echo(f"Goal set successfully: {json.dumps(goal, ensure_ascii=False, indent=2)}")


@goal_app.command("show")
def goal_show(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Show and analyze all investment goals."""
    _, paths = _load(config)
    from .investment_goal_planner import InvestmentGoalPlanner
    planner = InvestmentGoalPlanner(paths.project_root)
    goals = planner.load_goals()
    analyses = [planner.calculate_analysis(g) for g in goals]
    typer.echo(json.dumps(analyses, ensure_ascii=False, indent=2))


@goal_app.command("delete")
def goal_delete(
    goal_id: Annotated[str, typer.Option("--id", help="Goal identifier to delete")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Delete a specific investment goal."""
    _, paths = _load(config)
    from .investment_goal_planner import InvestmentGoalPlanner
    planner = InvestmentGoalPlanner(paths.project_root)
    success = planner.delete_goal(goal_id)
    if success:
        typer.echo(f"Deleted goal: {goal_id}")
    else:
        typer.echo(f"Goal not found: {goal_id}", err=True)


# Monthly Cashflow Commands
@cashflow_app.command("add")
def cashflow_add(
    month: Annotated[str, typer.Option("--month", help="YYYY-MM")],
    salary: Annotated[float, typer.Option("--salary", help="Monthly salary deposit")],
    dividends: Annotated[float, typer.Option("--dividends", help="Expected dividends")] = 0.0,
    extra: Annotated[float, typer.Option("--extra", help="Extra deposit cash")] = 0.0,
    buys: Annotated[float, typer.Option("--buys", help="Planned purchases value")] = 0.0,
    reserved: Annotated[float, typer.Option("--reserved", help="Reserved emergency cash")] = 0.0,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Add a monthly cashflow record."""
    _, paths = _load(config)
    from .cashflow_planner import CashflowPlanner
    planner = CashflowPlanner(paths.project_root)
    rec = planner.add_cashflow(
        month=month,
        salary_deposit=salary,
        expected_dividends=dividends,
        extra_deposits=extra,
        planned_buys=buys,
        reserved_cash=reserved
    )
    typer.echo(f"Cashflow record added: {json.dumps(rec, ensure_ascii=False, indent=2)}")


@cashflow_app.command("show")
def cashflow_show(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Show monthly cashflow plans and allocations."""
    _, paths = _load(config)
    from .cashflow_planner import CashflowPlanner
    planner = CashflowPlanner(paths.project_root)
    records = planner.load_cashflows()
    budgets = [planner.calculate_monthly_budget(r) for r in records]
    typer.echo(json.dumps(budgets, ensure_ascii=False, indent=2))


@cashflow_app.command("delete")
def cashflow_delete(
    month: Annotated[str, typer.Option("--month", help="YYYY-MM to delete")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Delete a monthly cashflow record."""
    _, paths = _load(config)
    from .cashflow_planner import CashflowPlanner
    planner = CashflowPlanner(paths.project_root)
    success = planner.delete_cashflow(month)
    if success:
        typer.echo(f"Deleted cashflow for: {month}")
    else:
        typer.echo(f"Cashflow not found: {month}", err=True)


# Investor Coach & Diet Commands
@coach_app.command("behavior")
def coach_behavior(
    limit: Annotated[int, typer.Option("--limit")] = 50,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Show behavioral bias warnings and healthy habits analysis."""
    _, paths = _load(config)
    from .investor_behavior_insights import InvestorBehaviorInsights
    insights = InvestorBehaviorInsights(paths.project_root)
    report = insights.analyze_behavior(limit=limit)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@coach_app.command("diet")
def coach_diet(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Show portfolio diet pruning targets and redundancy warnings."""
    _, paths = _load(config)
    from .portfolio_diet_mode import PortfolioDietMode
    diet = PortfolioDietMode(paths.project_root)
    report = diet.analyze_portfolio_diet()
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


# Monthly report, benchmark, and dividend simulations commands
@report_app.command("monthly")
def report_monthly(
    year: Annotated[int, typer.Option("--year", help="Year of the report")],
    month: Annotated[int, typer.Option("--month", help="Month of the report")],
    return_pct: Annotated[float, typer.Option("--return-pct")] = 0.0,
    dividend_krw: Annotated[float, typer.Option("--dividend-krw")] = 0.0,
    cost_krw: Annotated[float, typer.Option("--cost-krw")] = 0.0,
    fx_effect_krw: Annotated[float, typer.Option("--fx-effect-krw")] = 0.0,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Generate HTML and Markdown monthly investment report."""
    _, paths = _load(config)
    from .monthly_investment_report import MonthlyInvestmentReport
    reporter = MonthlyInvestmentReport(paths.project_root)
    
    # Compile mock/given metrics for generator
    data = {
        "return_pct": return_pct,
        "dividend_krw": dividend_krw,
        "cost_krw": cost_krw,
        "fx_effect_krw": fx_effect_krw,
        "risk_blocks_count": 0,
        "signals_count": 0,
        "win_rate_pct": 65.4,
        "goal_achievement_pct": 74.2,
        "generated_at": datetime.now().isoformat()
    }
    paths_dict = reporter.generate_report(year, month, data)
    typer.echo(f"Generated monthly reports successfully:\n{json.dumps(paths_dict, indent=2)}")


@report_app.command("benchmark")
def report_benchmark(
    return_pct: Annotated[float, typer.Option("--return-pct", help="Portfolio return pct")],
    volatility_pct: Annotated[float, typer.Option("--volatility-pct", help="Portfolio volatility pct")],
    mdd_pct: Annotated[float, typer.Option("--mdd-pct", help="Portfolio MDD pct")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Compare portfolio return against major index benchmarks."""
    _, paths = _load(config)
    from .benchmark_comparison import BenchmarkComparison
    comp = BenchmarkComparison()
    report = comp.compare_portfolio(return_pct, volatility_pct, mdd_pct)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@report_app.command("dividend-simulate")
def report_dividend_simulate(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Estimate expected monthly dividend cashflow and compound growth scenarios."""
    _, paths = _load(config)
    from .dividend_cashflow_simulator import DividendCashflowSimulator
    sim = DividendCashflowSimulator(paths.project_root)
    report = sim.simulate_cashflow()
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
