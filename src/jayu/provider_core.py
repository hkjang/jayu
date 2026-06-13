from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import requests

from .io import atomic_write_json, read_json, stable_hash


class ProviderCategory(StrEnum):
    PRICE = "price"
    FUNDAMENTALS = "fundamentals"
    MACRO = "macro"
    NEWS = "news"
    REFERENCE = "reference"
    OPTIONS = "options"


@dataclass(frozen=True)
class ProviderPolicy:
    timeout_seconds: float = 20.0
    retries: int = 3
    rate_limit_per_minute: int = 60
    cache_ttl_seconds: int = 14_400


class NamedProvider(Protocol):
    name: str
    category: ProviderCategory


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[ProviderCategory, dict[str, NamedProvider]] = {
            category: {} for category in ProviderCategory
        }

    def register(self, provider: NamedProvider) -> None:
        category = ProviderCategory(provider.category)
        if provider.name in self._providers[category]:
            raise ValueError(f"duplicate {category.value} provider: {provider.name}")
        self._providers[category][provider.name] = provider

    def get(self, category: ProviderCategory, name: str) -> NamedProvider:
        try:
            return self._providers[category][name]
        except KeyError as exc:
            raise KeyError(f"unknown {category.value} provider: {name}") from exc

    def providers(self, category: ProviderCategory) -> list[NamedProvider]:
        return list(self._providers[category].values())

    def inventory(self) -> dict[str, list[str]]:
        return {
            category.value: sorted(providers) for category, providers in self._providers.items()
        }


class JsonCache:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, namespace: str, key: Mapping[str, Any] | str) -> Path:
        digest = stable_hash(key)[:20]
        return self.root / namespace / f"{digest}.json"

    def read(
        self,
        namespace: str,
        key: Mapping[str, Any] | str,
        *,
        ttl_seconds: int,
    ) -> Any | None:
        path = self.path_for(namespace, key)
        if not path.exists() or time.time() - path.stat().st_mtime > ttl_seconds:
            return None
        return read_json(path, default=None)

    def write(self, namespace: str, key: Mapping[str, Any] | str, value: Any) -> Path:
        path = self.path_for(namespace, key)
        atomic_write_json(path, value)
        return path


class HttpJsonClient:
    def __init__(
        self,
        policy: ProviderPolicy,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.policy = policy
        self.session = session or requests.Session()
        self.sleep = sleep
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        if self.policy.rate_limit_per_minute <= 0:
            return
        minimum_interval = 60.0 / self.policy.rate_limit_per_minute
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < minimum_interval:
            self.sleep(minimum_interval - elapsed)

    def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        failures: list[str] = []
        for attempt in range(1, self.policy.retries + 1):
            try:
                self._throttle()
                response = self.session.request(
                    method,
                    url,
                    timeout=self.policy.timeout_seconds,
                    **kwargs,
                )
                self._last_request_at = time.monotonic()
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(
                        f"retryable HTTP {response.status_code}",
                        response=response,
                    )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                failures.append(f"attempt {attempt}: {exc}")
                if attempt < self.policy.retries:
                    self.sleep(float(attempt))
        raise RuntimeError(f"provider request failed: {' | '.join(failures)}")


def policy_dict(policy: ProviderPolicy) -> dict[str, Any]:
    return asdict(policy)
