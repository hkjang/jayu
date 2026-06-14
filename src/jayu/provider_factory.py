from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pandas as pd
import exchange_calendars as xcals
from pydantic import SecretStr

from .artifacts import RunContext
from .data import (
    MarketDataProvider,
    MassiveProvider,
    TiingoProvider,
    YahooProvider,
)
from .io import stable_hash
from .portfolio import load_portfolio_mapping
from .provider_core import (
    ProviderCategory,
    ProviderPolicy,
    ProviderRegistry,
)
from .settings import ProviderPolicySettings, Settings
from .supplemental_data import (
    AlphaVantageNewsProvider,
    FinnhubEventProvider,
    FredMacroProvider,
    OpenFigiProvider,
    SecEdgarProvider,
)


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value else None


def provider_policy(settings: Settings, name: str) -> ProviderPolicy:
    raw = settings.data.provider_policies.get(name, ProviderPolicySettings())
    return ProviderPolicy(
        timeout_seconds=raw.timeout_seconds,
        retries=raw.retries,
        rate_limit_per_minute=raw.rate_limit_per_minute,
        cache_ttl_seconds=raw.cache_ttl_seconds,
    )


def _provider_enabled(settings: Settings, name: str) -> bool:
    policy = settings.data.provider_policies.get(name)
    return policy.enabled if policy is not None else True


def build_provider_registry(settings: Settings, cache_dir: Path) -> ProviderRegistry:
    registry = ProviderRegistry()
    if _provider_enabled(settings, "yahoo"):
        registry.register(YahooProvider())
    massive_key = _secret(settings.massive_api_key)
    if massive_key and _provider_enabled(settings, "massive"):
        policy = provider_policy(settings, "massive")
        registry.register(MassiveProvider(massive_key, timeout=policy.timeout_seconds))
    tiingo_key = _secret(settings.tiingo_api_key)
    if tiingo_key and _provider_enabled(settings, "tiingo"):
        policy = provider_policy(settings, "tiingo")
        registry.register(TiingoProvider(tiingo_key, timeout=policy.timeout_seconds))
    sec_user_agent = _secret(settings.sec_user_agent)
    if sec_user_agent and _provider_enabled(settings, "sec_edgar"):
        registry.register(
            SecEdgarProvider(
                cache_dir / "fundamentals" / "sec",
                sec_user_agent,
                policy=provider_policy(settings, "sec_edgar"),
            )
        )
    fred_key = _secret(settings.fred_api_key)
    if fred_key and _provider_enabled(settings, "fred"):
        registry.register(
            FredMacroProvider(
                cache_dir / "macro" / "fred",
                fred_key,
                policy=provider_policy(settings, "fred"),
            )
        )
    if _provider_enabled(settings, "openfigi"):
        registry.register(
            OpenFigiProvider(
                cache_dir / "reference" / "openfigi",
                _secret(settings.openfigi_api_key),
                policy=provider_policy(settings, "openfigi"),
            )
        )
    alpha_key = _secret(settings.alpha_vantage_api_key)
    if alpha_key and _provider_enabled(settings, "alpha_vantage_news"):
        registry.register(
            AlphaVantageNewsProvider(
                cache_dir / "news" / "alpha_vantage",
                alpha_key,
                policy=provider_policy(settings, "alpha_vantage_news"),
            )
        )
    finnhub_key = _secret(settings.finnhub_api_key)
    if finnhub_key and _provider_enabled(settings, "finnhub_events"):
        registry.register(
            FinnhubEventProvider(
                cache_dir / "events" / "finnhub",
                finnhub_key,
                policy=provider_policy(settings, "finnhub_events"),
            )
        )
    return registry


def price_provider_sequence(
    settings: Settings,
    registry: ProviderRegistry,
) -> tuple[list[MarketDataProvider], list[str]]:
    requested = [
        settings.data_provider,
        *([settings.data_fallback_provider] if settings.data_fallback_provider != "none" else []),
        *settings.data.cross_validation_providers,
    ]
    providers: list[MarketDataProvider] = []
    unavailable: list[str] = []
    seen: set[str] = set()
    for name in requested:
        if name in seen:
            continue
        seen.add(name)
        try:
            provider = registry.get(ProviderCategory.PRICE, name)
        except KeyError:
            unavailable.append(name)
            continue
        providers.append(cast(MarketDataProvider, provider))
    if not providers or providers[0].name != settings.data_provider:
        env_name = settings.data.api_key_env_names.get(
            settings.data_provider,
            f"JAYU_{settings.data_provider.upper()}_API_KEY",
        )
        raise ValueError(f"{settings.data_provider} data provider requires {env_name}")
    return providers, unavailable


def provider_configuration_audit(
    settings: Settings,
    registry: ProviderRegistry,
) -> dict[str, Any]:
    inventory = registry.inventory()
    available_prices = set(inventory[ProviderCategory.PRICE.value])
    errors: list[str] = []
    warnings: list[str] = []
    if settings.data_provider not in available_prices:
        errors.append(f"primary price provider unavailable: {settings.data_provider}")
    validation_prices = {
        settings.data_provider,
        *settings.data.cross_validation_providers,
    }
    requested_prices = set(validation_prices)
    if settings.data_fallback_provider != "none":
        requested_prices.add(settings.data_fallback_provider)
    missing_prices = sorted(requested_prices - available_prices)
    if missing_prices:
        message = "price providers unavailable due to credentials or policy: " + ", ".join(
            missing_prices
        )
        missing_validation_prices = set(missing_prices) & validation_prices
        if settings.data.cross_validation_mode == "strict" and missing_validation_prices:
            errors.append(message)
        else:
            warnings.append(message)
    if (
        settings.mode in {"signal", "shadow", "paper", "live"}
        and settings.data.cross_validation_mode == "strict"
        and not settings.data.cross_validation_providers
    ):
        errors.append("strict operational mode requires cross_validation_providers")
    usable_requested = len(validation_prices & available_prices)
    if usable_requested < settings.data.minimum_valid_price_sources:
        errors.append(
            "minimum_valid_price_sources exceeds configured available price providers "
            f"({settings.data.minimum_valid_price_sources} > {usable_requested})"
        )
    for name in settings.data.supplemental_providers:
        category = _supplemental_category(name)
        if name not in inventory[category.value]:
            message = f"supplemental provider unavailable: {name}"
            if settings.data.supplemental_failure_policy == "block":
                errors.append(message)
            else:
                warnings.append(message)
    return {
        "valid": not errors,
        "inventory": inventory,
        "errors": errors,
        "warnings": warnings,
        "cross_validation_mode": settings.data.cross_validation_mode,
        "api_key_env_names": settings.data.api_key_env_names,
    }


def collect_supplemental_data(
    settings: Settings,
    registry: ProviderRegistry,
    context: RunContext,
) -> None:
    requested = settings.data.supplemental_providers
    if not requested:
        return
    now = datetime.now(UTC)
    mapping = load_portfolio_mapping(context.paths.portfolio_mapping_file)
    for name in requested:
        try:
            provider = registry.get(_supplemental_category(name), name)
        except KeyError as exc:
            _record_supplemental_failure(context, name, None, str(exc))
            if settings.data.supplemental_failure_policy == "block":
                raise ValueError(f"required supplemental provider unavailable: {name}") from exc
            continue
        try:
            if isinstance(provider, SecEdgarProvider):
                for ticker in settings.tickers:
                    try:
                        timeline = provider.filing_timeline(ticker)
                        facts = provider.point_in_time_facts(ticker, now)
                        _record_supplemental_success(
                            context,
                            provider.name,
                            ProviderCategory.FUNDAMENTALS,
                            ticker,
                            timeline + facts,
                            "accepted_at",
                        )
                    except Exception as exc:
                        _handle_supplemental_failure(
                            settings,
                            context,
                            provider.name,
                            ticker,
                            exc,
                        )
            elif isinstance(provider, FredMacroProvider):
                start = (now - timedelta(days=3650)).date().isoformat()
                end = now.date().isoformat()
                for series_id in settings.data.macro_series:
                    try:
                        rows = provider.observations(series_id, start=start, end=end)
                        _record_supplemental_success(
                            context,
                            provider.name,
                            ProviderCategory.MACRO,
                            series_id,
                            rows,
                            "available_at",
                        )
                    except Exception as exc:
                        _handle_supplemental_failure(
                            settings,
                            context,
                            provider.name,
                            series_id,
                            exc,
                        )
                trading_days = (
                    xcals.get_calendar("XNYS").sessions_in_range(start, end).tz_localize(None)
                )
                features = provider.feature_frame(
                    pd.DatetimeIndex(trading_days),
                    series_ids=settings.data.macro_series,
                    as_of=now,
                    start=start,
                    end=end,
                )
                feature_path = context.run_dir / "macro_regime_features.parquet"
                features.to_parquet(feature_path)
                context.record_artifact(feature_path)
            elif isinstance(provider, OpenFigiProvider):
                for ticker in settings.tickers:
                    try:
                        audit = provider.audit_ticker(
                            ticker,
                            mapping,
                            exchange_code=_openfigi_exchange_code(ticker),
                        )
                        context.record_reference_audit(ticker, audit.to_dict())
                        _record_supplemental_success(
                            context,
                            provider.name,
                            ProviderCategory.REFERENCE,
                            ticker,
                            audit.candidates,
                            None,
                        )
                    except Exception as exc:
                        _handle_supplemental_failure(
                            settings,
                            context,
                            provider.name,
                            ticker,
                            exc,
                        )
            elif isinstance(provider, AlphaVantageNewsProvider):
                for ticker in settings.tickers:
                    try:
                        rows = provider.visible_news(ticker, now)
                        recent = [
                            row
                            for row in rows
                            if datetime.fromisoformat(str(row["published_at"]))
                            >= now - timedelta(days=7)
                        ]
                        context.record_event_notes(
                            ticker,
                            [
                                {
                                    "code": "recent_news",
                                    "published_at": row["published_at"],
                                    "title": row.get("title"),
                                    "sentiment_score": row.get("sentiment_score"),
                                }
                                for row in recent[-10:]
                            ],
                        )
                        _record_supplemental_success(
                            context,
                            provider.name,
                            ProviderCategory.NEWS,
                            ticker,
                            rows,
                            "published_at",
                        )
                    except Exception as exc:
                        _handle_supplemental_failure(
                            settings,
                            context,
                            provider.name,
                            ticker,
                            exc,
                        )
            elif isinstance(provider, FinnhubEventProvider):
                for ticker in settings.tickers:
                    try:
                        rows = provider.event_snapshot(ticker, as_of=now)
                        notes = [
                            {
                                "code": str(row.get("event_type")),
                                "known_at": row.get("known_at"),
                                "event_date": row.get("event_date"),
                                "headline": row.get("headline"),
                                "mspr": row.get("mspr"),
                            }
                            for row in rows[-20:]
                        ]
                        context.record_event_notes(ticker, notes)
                        _record_supplemental_success(
                            context,
                            provider.name,
                            ProviderCategory.NEWS,
                            ticker,
                            rows,
                            "known_at",
                        )
                    except Exception as exc:
                        _handle_supplemental_failure(
                            settings,
                            context,
                            provider.name,
                            ticker,
                            exc,
                        )
        except Exception as exc:
            _record_supplemental_failure(context, name, None, str(exc))
            if settings.data.supplemental_failure_policy == "block":
                raise


def _openfigi_exchange_code(ticker: str) -> str:
    upper = ticker.upper()
    if upper.endswith(".KS"):
        return "KS"
    if upper.endswith(".KQ"):
        return "KQ"
    return "US"


def _handle_supplemental_failure(
    settings: Settings,
    context: RunContext,
    provider: str,
    symbol: str,
    exc: Exception,
) -> None:
    _record_supplemental_failure(context, provider, symbol, str(exc))
    if settings.data.supplemental_failure_policy == "block":
        raise exc


def _supplemental_category(name: str) -> ProviderCategory:
    return {
        "sec_edgar": ProviderCategory.FUNDAMENTALS,
        "fred": ProviderCategory.MACRO,
        "openfigi": ProviderCategory.REFERENCE,
        "alpha_vantage_news": ProviderCategory.NEWS,
        "finnhub_events": ProviderCategory.NEWS,
    }[name]


def _record_supplemental_success(
    context: RunContext,
    provider: str,
    category: ProviderCategory,
    symbol: str,
    rows: list[dict[str, Any]],
    timestamp_key: str | None,
) -> None:
    dates = [
        str(row[timestamp_key])
        for row in rows
        if timestamp_key and row.get(timestamp_key) is not None
    ]
    context.record_data_source(
        {
            "provider": provider,
            "category": category.value,
            "symbol": symbol,
            "status": "success",
            "rows": len(rows),
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
            "hash": stable_hash(rows),
        }
    )


def _record_supplemental_failure(
    context: RunContext,
    provider: str,
    symbol: str | None,
    error: str,
) -> None:
    context.record_data_source(
        {
            "provider": provider,
            "category": _supplemental_category(provider).value,
            "symbol": symbol,
            "status": "failed",
            "error": error,
        }
    )
