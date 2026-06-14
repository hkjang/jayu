"""Run-level safety verdict assembled from Jayu execution artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from .failure_codes import FailureCode
from .io import atomic_write_json, read_json, stable_hash

ComponentStatus = Literal["pass", "warn", "fail", "not_evaluated"]
OverallVerdict = Literal["approved", "review", "blocked"]


def build_safety_verdict(
    run_dir: Path,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_data = dict(manifest or read_json(run_dir / "manifest.json", default={}) or {})
    result = _mapping(manifest_data.get("result"))
    mode = str(result.get("mode") or manifest_data.get("execution_mode") or "unknown")
    components = {
        "data": _data_component(run_dir, manifest_data),
        "survivorship": _survivorship_component(manifest_data),
        "promotion": _promotion_component(run_dir, mode),
        "risk": _risk_component(run_dir),
    }
    overall = _overall_status(manifest_data, components)
    reasons = [
        {"component": name, "code": code, "message": message}
        for name, component in components.items()
        for code, message in _component_reason_pairs(component)
    ]
    verdict = {
        "overall": overall,
        "mode": mode,
        "run_status": manifest_data.get("status"),
        "run_id": manifest_data.get("run_id"),
        "config_hash": manifest_data.get("config_hash"),
        "data_hash": stable_hash(manifest_data.get("data_hashes", {})),
        "components": components,
        "reasons": reasons,
    }
    return verdict


def write_safety_verdict(
    run_dir: Path,
    *,
    manifest: Mapping[str, Any] | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    verdict = build_safety_verdict(run_dir, manifest=manifest)
    atomic_write_json(output or (run_dir / "safety_verdict.json"), verdict)
    return verdict


def _data_component(run_dir: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    failure_code = manifest.get("failure_code")
    data_reports = _mapping(manifest.get("data_reports"))
    provider_disagreements = manifest.get("provider_disagreements")
    disagreements = provider_disagreements if isinstance(provider_disagreements, list) else []
    if not disagreements:
        report = _mapping(read_json(run_dir / "provider_disagreement_report.json", default={}))
        file_disagreements = report.get("disagreements")
        disagreements = file_disagreements if isinstance(file_disagreements, list) else []
    price_reports = [
        report
        for report in data_reports.values()
        if isinstance(report, Mapping) and report.get("ticker")
    ]
    invalid = [
        str(report.get("ticker"))
        for report in price_reports
        if report.get("valid") is not True or report.get("price_usable") is not True
    ]
    codes = {
        FailureCode.DATA_FAILURE.value,
        FailureCode.DATA_CONTRACT_FAILED.value,
        FailureCode.DATA_DISAGREEMENT.value,
        FailureCode.UNVERIFIED_PRICE_DATA.value,
    }
    reasons: list[dict[str, Any]] = []
    if failure_code in codes:
        reasons.append({"code": str(failure_code), "message": "run failed in the data layer"})
    if invalid:
        reasons.append(
            {
                "code": FailureCode.DATA_FAILURE.value,
                "message": "one or more requested tickers did not produce usable price data",
                "tickers": invalid,
            }
        )
    if disagreements:
        reasons.append(
            {
                "code": FailureCode.DATA_DISAGREEMENT.value,
                "message": "provider disagreement exceeded configured tolerance",
                "count": len(disagreements),
            }
        )
    status: ComponentStatus
    if reasons:
        status = "fail"
    elif price_reports:
        status = "pass"
    else:
        status = "not_evaluated"
    return {
        "status": status,
        "price_dataset_count": len(price_reports),
        "provider_disagreement_count": len(disagreements),
        "reasons": reasons,
    }


def _survivorship_component(manifest: Mapping[str, Any]) -> dict[str, Any]:
    audit = _mapping(manifest.get("survivorship_audit"))
    if not audit:
        return {"status": "not_evaluated", "reasons": []}
    policy = audit.get("policy")
    valid = audit.get("valid") is True
    warnings = [str(item) for item in audit.get("warnings", []) if item]
    reasons = [{"code": "SURVIVORSHIP_BIAS_RISK", "message": item} for item in warnings]
    if valid:
        status: ComponentStatus = "pass"
    elif policy == "strict":
        status = "fail"
    else:
        status = "warn"
    return {
        "status": status,
        "policy": policy,
        "valid": valid,
        "includes_delisted": audit.get("includes_delisted"),
        "exception_reason": audit.get("exception_reason"),
        "reasons": reasons,
    }


def _promotion_component(run_dir: Path, mode: str) -> dict[str, Any]:
    promotion = _mapping(read_json(run_dir / "promotion.json", default={}))
    required = mode in {"paper", "live"}
    if not promotion:
        status: ComponentStatus = "fail" if required else "not_evaluated"
        reasons = (
            [
                {
                    "code": FailureCode.SHADOW_PROMOTION_FAILED.value,
                    "message": f"{mode} mode requires an eligible shadow promotion",
                }
            ]
            if required
            else []
        )
        return {"status": status, "required": required, "reasons": reasons}
    eligible = promotion.get("eligible") is True
    failed_criteria = [
        str(item.get("name"))
        for item in promotion.get("criteria", [])
        if isinstance(item, Mapping) and item.get("passed") is not True
    ]
    if eligible:
        status = "pass"
    elif required:
        status = "fail"
    else:
        status = "warn"
    return {
        "status": status,
        "required": required,
        "eligible": eligible,
        "failed_criteria": failed_criteria,
        "metrics": promotion.get("metrics", {}),
        "reasons": [
            {
                "code": FailureCode.SHADOW_PROMOTION_FAILED.value,
                "message": "shadow promotion criteria are not satisfied",
                "criteria": failed_criteria,
            }
        ]
        if not eligible
        else [],
    }


def _risk_component(run_dir: Path) -> dict[str, Any]:
    risk = _mapping(read_json(run_dir / "risk_explanation.json", default={}))
    if not risk:
        return {"status": "not_evaluated", "reasons": []}
    blocked = int(risk.get("blocked_count", 0) or 0)
    top_reasons = risk.get("top_block_reasons", [])
    reasons = [
        {
            "code": str(item.get("code")),
            "message": "risk gate blocked one or more signals",
            "count": item.get("count"),
        }
        for item in top_reasons
        if isinstance(item, Mapping) and item.get("code")
    ]
    status: ComponentStatus = "fail" if blocked else "pass"
    return {
        "status": status,
        "approved_count": int(risk.get("approved_count", 0) or 0),
        "blocked_count": blocked,
        "hold_count": int(risk.get("hold_count", 0) or 0),
        "reasons": reasons,
    }


def _overall_status(
    manifest: Mapping[str, Any],
    components: Mapping[str, Mapping[str, Any]],
) -> OverallVerdict:
    if manifest.get("status") == "failed":
        return "blocked"
    statuses = {str(component.get("status")) for component in components.values()}
    if "fail" in statuses:
        return "blocked"
    if statuses & {"warn", "not_evaluated"}:
        return "review"
    return "approved"


def _component_reason_pairs(component: Mapping[str, Any]) -> list[tuple[str, str]]:
    reasons = component.get("reasons", [])
    pairs: list[tuple[str, str]] = []
    if not isinstance(reasons, list):
        return pairs
    for reason in reasons:
        if isinstance(reason, Mapping):
            pairs.append((str(reason.get("code", "UNKNOWN")), str(reason.get("message", ""))))
    return pairs


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
