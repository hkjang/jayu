from __future__ import annotations

from dataclasses import asdict, dataclass

from .settings import Settings


@dataclass(frozen=True)
class SurvivorshipAudit:
    policy: str
    universe_as_of: str | None
    universe_source: str
    includes_delisted: bool
    exception_reason: str | None
    valid: bool
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_survivorship(settings: Settings) -> SurvivorshipAudit:
    warnings = []
    if settings.universe.as_of is None:
        warnings.append("universe_as_of is missing; current constituents may bias history")
    if not settings.universe.includes_delisted:
        if settings.universe.exception_reason:
            warnings.append(
                "delisted securities are excluded under an explicit exception: "
                + settings.universe.exception_reason
            )
        else:
            warnings.append(
                "SURVIVORSHIP_BIAS_RISK: delisted securities are not included in the "
                "research universe"
            )
    if settings.universe.source == "manual_current_universe":
        warnings.append(
            "SURVIVORSHIP_BIAS_RISK: manual_current_universe is not point-in-time membership"
        )
    strict_requirements_met = settings.universe.as_of is not None and (
        settings.universe.includes_delisted or settings.universe.exception_reason is not None
    )
    valid = strict_requirements_met if settings.universe.policy == "strict" else not warnings
    if settings.universe.policy == "strict" and not valid:
        raise ValueError(
            "survivorship audit failed: strict mode requires universe.as_of and either "
            "includes_delisted=true or universe.exception_reason"
        )
    return SurvivorshipAudit(
        policy=settings.universe.policy,
        universe_as_of=(settings.universe.as_of.isoformat() if settings.universe.as_of else None),
        universe_source=settings.universe.source,
        includes_delisted=settings.universe.includes_delisted,
        exception_reason=settings.universe.exception_reason,
        valid=valid,
        warnings=warnings,
    )
