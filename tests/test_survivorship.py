import pytest

from jayu.settings import Settings, UniverseSettings
from jayu.survivorship import audit_survivorship


def test_survivorship_warn_policy_records_limitations():
    report = audit_survivorship(Settings())

    assert report.valid is False
    assert len(report.warnings) == 3
    assert sum("SURVIVORSHIP_BIAS_RISK" in warning for warning in report.warnings) == 2


def test_survivorship_strict_policy_rejects_current_only_universe():
    settings = Settings(universe=UniverseSettings(policy="strict"))

    with pytest.raises(ValueError, match="survivorship audit failed"):
        audit_survivorship(settings)


def test_survivorship_strict_policy_accepts_explicit_exception():
    settings = Settings(
        universe=UniverseSettings(
            policy="strict",
            as_of="2026-01-01",
            includes_delisted=False,
            exception_reason="Universe vendor does not expose inactive share classes.",
        )
    )

    report = audit_survivorship(settings)

    assert report.valid is True
    assert report.exception_reason is not None
