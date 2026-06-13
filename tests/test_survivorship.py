import pytest

from jayu.settings import Settings, UniverseSettings
from jayu.survivorship import audit_survivorship


def test_survivorship_warn_policy_records_limitations():
    report = audit_survivorship(Settings())

    assert report.valid is False
    assert len(report.warnings) == 2


def test_survivorship_strict_policy_rejects_current_only_universe():
    settings = Settings(universe=UniverseSettings(policy="strict"))

    with pytest.raises(ValueError, match="survivorship audit failed"):
        audit_survivorship(settings)
