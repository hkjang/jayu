from pathlib import Path

import pytest

from jayu.provider_core import JsonCache, ProviderCategory, ProviderRegistry


class FakeProvider:
    def __init__(self, name: str, category: ProviderCategory):
        self.name = name
        self.category = category


def test_provider_registry_separates_categories():
    registry = ProviderRegistry()
    registry.register(FakeProvider("same_api", ProviderCategory.PRICE))
    registry.register(FakeProvider("same_api", ProviderCategory.NEWS))

    assert registry.get(ProviderCategory.PRICE, "same_api").category == ProviderCategory.PRICE
    assert registry.inventory()["news"] == ["same_api"]


def test_provider_registry_rejects_duplicate_name_within_category():
    registry = ProviderRegistry()
    registry.register(FakeProvider("duplicate", ProviderCategory.PRICE))

    with pytest.raises(ValueError, match="duplicate price provider"):
        registry.register(FakeProvider("duplicate", ProviderCategory.PRICE))


def test_json_cache_uses_namespace_and_ttl(tmp_path: Path):
    cache = JsonCache(tmp_path)
    cache.write("macro", {"series": "DGS10"}, {"value": 4.2})

    assert cache.read("macro", {"series": "DGS10"}, ttl_seconds=60) == {"value": 4.2}
    assert cache.read("macro", {"series": "DGS10"}, ttl_seconds=-1) is None
