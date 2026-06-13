from __future__ import annotations

from dataclasses import asdict, dataclass

from .settings import Settings


@dataclass(frozen=True)
class SurvivorshipAudit:
    policy: str
    universe_as_of: str | None
    universe_source: str
    includes_delisted: bool
    valid: bool
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_survivorship(settings: Settings) -> SurvivorshipAudit:
    warnings = []
    if settings.universe.as_of is None:
        warnings.append("universe_as_of is missing; current constituents may bias history")
    if not settings.universe.includes_delisted:
        warnings.append("delisted securities are not included in the research universe")
    valid = not warnings
    if settings.universe.policy == "strict" and not valid:
        raise ValueError("survivorship audit failed: " + "; ".join(warnings))
    return SurvivorshipAudit(
        policy=settings.universe.policy,
        universe_as_of=(settings.universe.as_of.isoformat() if settings.universe.as_of else None),
        universe_source=settings.universe.source,
        includes_delisted=settings.universe.includes_delisted,
        valid=valid,
        warnings=warnings,
    )
