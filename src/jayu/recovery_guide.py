from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .failure_codes import FailureCode
from .io import atomic_write_json, read_json

SCHEMA_VERSION = 1
DEFAULT_SOURCE = (
    "safety_verdict.json · latest run manifest · operational_status.json · "
    "recovery_guide.py"
)


@dataclass(frozen=True)
class RecoveryPlaybook:
    title: str
    severity: str
    diagnosis: str
    steps: tuple[str, ...]
    artifacts: tuple[str, ...]
    commands: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()


PLAYBOOKS: dict[str, RecoveryPlaybook] = {
    FailureCode.DATA_FAILURE.value: RecoveryPlaybook(
        title="가격 데이터 수집 실패",
        severity="blocked",
        diagnosis="가격 provider가 필요한 ticker/기간의 usable price를 만들지 못했습니다.",
        steps=(
            "데이터 품질 화면에서 실패 provider와 ticker를 확인합니다.",
            "API 키, rate limit, 캐시 만료 시간을 확인한 뒤 같은 run을 다시 검증합니다.",
            "한 provider만 실패했다면 fallback/cross-validation provider 정책을 확인합니다.",
        ),
        artifacts=("data_sources.json", "provider_disagreement_report.json", "manifest.json"),
        commands=("uv run jayu run --mode signal",),
        verification=("데이터 검증 카드가 success/pass인지 확인",),
    ),
    FailureCode.DATA_CONTRACT_FAILED.value: RecoveryPlaybook(
        title="데이터 스키마 불일치",
        severity="blocked",
        diagnosis="수집 데이터가 필수 컬럼, 날짜 정렬, 가격 사용 가능 조건을 충족하지 못했습니다.",
        steps=(
            "data_sources.json에서 rows, start/end, status를 확인합니다.",
            "누락 컬럼 또는 빈 가격 행이 있으면 provider 변환 로직과 캐시를 점검합니다.",
            "수정 후 동일 ticker로 데이터 품질 검사를 다시 실행합니다.",
        ),
        artifacts=("data_sources.json", "provider_disagreement_report.json"),
        commands=("uv run jayu run --mode signal",),
        verification=("DATA_CONTRACT_FAILED가 safety_verdict reasons에서 사라졌는지 확인",),
    ),
    FailureCode.DATA_DISAGREEMENT.value: RecoveryPlaybook(
        title="Provider 가격 불일치",
        severity="blocked",
        diagnosis="둘 이상의 가격 provider가 허용 오차를 넘는 가격/거래량 차이를 냈습니다.",
        steps=(
            "불일치 날짜와 provider 원본값을 확인합니다.",
            "액면분할, 배당 조정, 휴장일 차이처럼 설명 가능한 이벤트인지 확인합니다.",
            "설명 불가능하면 해당 ticker 신호를 보류하고 캐시를 갱신합니다.",
        ),
        artifacts=("provider_disagreement_report.json", "data_sources.json"),
        commands=("uv run jayu run --mode signal",),
        verification=("Provider disagreement count가 0이거나 정책상 review 이하인지 확인",),
    ),
    FailureCode.UNVERIFIED_PRICE_DATA.value: RecoveryPlaybook(
        title="가격 교차검증 미완료",
        severity="warning",
        diagnosis="가격 데이터가 운영 신호에 충분한 provider 교차검증을 받지 못했습니다.",
        steps=(
            "config.json의 data.cross_validation_providers를 확인합니다.",
            "보조 provider API 키가 설정되어 있는지 확인합니다.",
            "검증 불가 ticker는 자동 후보에서 제외합니다.",
        ),
        artifacts=("config.json", "data_sources.json"),
        commands=("uv run jayu validate-config --mode signal",),
        verification=("데이터 검증 provider 수가 2개 이상인지 확인",),
    ),
    FailureCode.SURVIVORSHIP_GATE_FAILED.value: RecoveryPlaybook(
        title="생존편향 게이트 실패",
        severity="blocked",
        diagnosis="리서치 universe가 시점별 구성원이 아니거나 strict 생존편향 정책을 충족하지 못했습니다.",
        steps=(
            "manual_current_universe를 연구용으로 쓰고 있는지 확인합니다.",
            "시점별 universe 파일을 사용하거나 includes_delisted 근거를 추가합니다.",
            "예외가 필요한 경우 exception_reason을 명시하고 research 모드 설정을 재검증합니다.",
        ),
        artifacts=("manifest.json survivorship_audit", "config.json"),
        commands=("uv run jayu validate-config --mode research",),
        verification=("safety_verdict.json의 survivorship component가 pass 또는 review인지 확인",),
    ),
    "SURVIVORSHIP_BIAS_RISK": RecoveryPlaybook(
        title="시점별 universe 확인 필요",
        severity="warning",
        diagnosis="현재 universe가 point-in-time membership이 아니라는 경고입니다.",
        steps=(
            "실행 manifest의 survivorship_audit warnings를 확인합니다.",
            "백테스트 연구에는 시점별 구성원 데이터 또는 명시적 연구 예외를 사용합니다.",
            "운영 신호에는 최신 보유/감시 리스트와 연구 universe를 구분합니다.",
        ),
        artifacts=("manifest.json survivorship_audit", "safety_verdict.json"),
        commands=("uv run jayu validate-config --mode research",),
        verification=("오늘 결론이 blocked가 아닌 review/warning으로 내려가는지 확인",),
    ),
    FailureCode.SAFETY_VERDICT_BLOCKED.value: RecoveryPlaybook(
        title="안전성 최종 차단",
        severity="blocked",
        diagnosis="데이터, 리스크, 생존편향, 승격 조건 중 하나 이상이 운영 승인 조건을 막았습니다.",
        steps=(
            "safety_verdict.json의 components별 status를 먼저 봅니다.",
            "fail component의 reason code에 해당하는 세부 가이드를 순서대로 처리합니다.",
            "모든 fail을 제거한 뒤 operational_status.json을 다시 생성합니다.",
        ),
        artifacts=("safety_verdict.json", "operational_status.json"),
        commands=("uv run jayu report operational-status",),
        verification=("overall verdict가 approved 또는 review로 바뀌었는지 확인",),
    ),
    FailureCode.SHADOW_PROMOTION_FAILED.value: RecoveryPlaybook(
        title="Shadow/Paper 승격 미충족",
        severity="warning",
        diagnosis="자동 또는 반자동 운용 전 필요한 shadow 실행 일수와 품질 기준이 부족합니다.",
        steps=(
            "promotion.json의 failed criteria를 확인합니다.",
            "부족한 shadow 실행 일수, health score, 신호 안정성 조건을 채웁니다.",
            "승격 조건 충족 전 live 주문 권한은 잠금 상태로 유지합니다.",
        ),
        artifacts=("promotion.json", "health.json", "signals/shadow"),
        commands=("uv run jayu promotion check",),
        verification=("promotion eligible이 true인지 확인",),
    ),
    FailureCode.SECTOR_EXPOSURE_EXCEEDED.value: RecoveryPlaybook(
        title="섹터 집중 초과",
        severity="blocked",
        diagnosis="주문 후 특정 섹터 비중이 risk.max_sector_exposure를 넘습니다.",
        steps=(
            "리스크 게이트의 observed/limit 값을 확인합니다.",
            "같은 섹터 신규 주문을 줄이거나 기존 섹터 보유를 먼저 축소합니다.",
            "자금 배분 시뮬레이터에서 주문 후 섹터 비중을 다시 확인합니다.",
        ),
        artifacts=("risk_explanation.json", "allocation_preview.json", "portfolio_mapping.json"),
        commands=("uv run jayu report allocation-preview --cash-krw <KRW>",),
        verification=("sector_breach_count가 0인지 확인",),
    ),
    FailureCode.SINGLE_POSITION_EXCEEDED.value: RecoveryPlaybook(
        title="단일 종목 비중 초과",
        severity="blocked",
        diagnosis="요청 포지션이 risk.max_single_position_pct보다 큽니다.",
        steps=(
            "승인 비중과 요청 비중을 비교합니다.",
            "주문 금액을 줄이거나 분할 매수로 변경합니다.",
            "해당 종목이 이미 보유 중이면 누적 비중 기준으로 다시 평가합니다.",
        ),
        artifacts=("risk_explanation.json", "allocation_preview.json", "today_signals.json"),
        commands=("uv run jayu report allocation-preview --cash-krw <KRW>",),
        verification=("max_position_breach_count가 0인지 확인",),
    ),
    FailureCode.MIN_CASH_BREACHED.value: RecoveryPlaybook(
        title="최소 현금 비중 미달",
        severity="blocked",
        diagnosis="주문 반영 후 현금 비중이 risk.min_cash_pct 아래로 내려갑니다.",
        steps=(
            "available cash와 주문 예정 금액을 같은 KRW 기준으로 맞춥니다.",
            "주문 금액을 줄이거나 매도/입금 후 재평가합니다.",
            "자금 배분 시뮬레이터에서 예상 현금 비중을 확인합니다.",
        ),
        artifacts=("allocation_preview.json", "order_plan.json", "risk_explanation.json"),
        commands=("uv run jayu report allocation-preview --cash-krw <KRW>",),
        verification=("cash_floor check가 success인지 확인",),
    ),
    FailureCode.LIQUIDITY_INSUFFICIENT.value: RecoveryPlaybook(
        title="유동성 부족",
        severity="blocked",
        diagnosis="주문 규모가 거래대금 또는 참여율 기준에 비해 큽니다.",
        steps=(
            "min_dollar_volume과 최근 거래대금을 비교합니다.",
            "주문을 여러 날로 분할하거나 승인 비중을 낮춥니다.",
            "스프레드와 슬리피지 가정을 보수적으로 재검증합니다.",
        ),
        artifacts=("risk_explanation.json", "data_sources.json"),
        commands=("uv run jayu run --mode signal",),
        verification=("LIQUIDITY_INSUFFICIENT 차단 사유가 사라졌는지 확인",),
    ),
    FailureCode.HEALTH_SCORE_LOW.value: RecoveryPlaybook(
        title="운영 Health 점수 낮음",
        severity="warning",
        diagnosis="최근 실행 품질, 데이터, 알림, 승격 상태가 운영 기준보다 낮습니다.",
        steps=(
            "health.json의 component별 점수를 확인합니다.",
            "실패 run과 알림 실패, provider 실패를 먼저 정리합니다.",
            "health를 다시 생성하고 승격 조건을 재확인합니다.",
        ),
        artifacts=("health.json", "operational_status.json", "notification_failures.jsonl"),
        commands=("uv run jayu report operational-status",),
        verification=("health_score가 promotion.min_health_score 이상인지 확인",),
    ),
    FailureCode.RUN_FAILED.value: RecoveryPlaybook(
        title="최근 실행 실패",
        severity="blocked",
        diagnosis="가장 최근 run이 success로 끝나지 않았습니다.",
        steps=(
            "manifest.json의 failure_code와 command를 확인합니다.",
            "해당 failure_code의 세부 복구 단계를 먼저 처리합니다.",
            "동일 mode로 다시 실행한 뒤 latest run이 success인지 확인합니다.",
        ),
        artifacts=("manifest.json", "events.jsonl", "safety_verdict.json"),
        commands=("uv run jayu run --mode signal",),
        verification=("latest run manifest status가 success인지 확인",),
    ),
}


def build_recovery_guide(
    reasons: Sequence[Mapping[str, Any]] | None = None,
    *,
    manifest: Mapping[str, Any] | None = None,
    verdict: Mapping[str, Any] | None = None,
    operational_status: Mapping[str, Any] | None = None,
    run_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = (now or datetime.now(UTC)).isoformat()
    collected = _collect_reasons(
        reasons,
        manifest=manifest,
        verdict=verdict,
        operational_status=operational_status,
    )
    items = [_guide_item(reason, run_dir=run_dir) for reason in collected]
    status = _overall_status(items)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamp,
        "status": status,
        "summary": {
            "issue_count": len(items),
            "blocked_count": sum(item["severity"] == "blocked" for item in items),
            "warning_count": sum(item["severity"] == "warning" for item in items),
            "top_code": items[0]["code"] if items else None,
            "source": DEFAULT_SOURCE,
        },
        "items": items,
        "source": DEFAULT_SOURCE,
    }


def build_recovery_guide_from_run(
    run_dir: Path | None,
    *,
    operational_status_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    manifest = _mapping(read_json(run_dir / "manifest.json", default={})) if run_dir else {}
    verdict = _mapping(read_json(run_dir / "safety_verdict.json", default={})) if run_dir else {}
    operational_status = (
        _mapping(read_json(operational_status_path, default={}))
        if operational_status_path is not None
        else {}
    )
    return build_recovery_guide(
        manifest=manifest,
        verdict=verdict,
        operational_status=operational_status,
        run_dir=run_dir,
        now=now,
    )


def write_recovery_guide(
    output_path: Path,
    *,
    reasons: Sequence[Mapping[str, Any]] | None = None,
    manifest: Mapping[str, Any] | None = None,
    verdict: Mapping[str, Any] | None = None,
    operational_status: Mapping[str, Any] | None = None,
    run_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = build_recovery_guide(
        reasons,
        manifest=manifest,
        verdict=verdict,
        operational_status=operational_status,
        run_dir=run_dir,
        now=now,
    )
    atomic_write_json(output_path, report)
    return report


def empty_recovery_guide() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "summary": {
            "issue_count": 0,
            "blocked_count": 0,
            "warning_count": 0,
            "top_code": None,
            "source": DEFAULT_SOURCE,
        },
        "items": [],
        "source": DEFAULT_SOURCE,
    }


def _collect_reasons(
    reasons: Sequence[Mapping[str, Any]] | None,
    *,
    manifest: Mapping[str, Any] | None,
    verdict: Mapping[str, Any] | None,
    operational_status: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    rows.extend(reason for reason in reasons or [] if isinstance(reason, Mapping))
    rows.extend(
        reason
        for reason in _sequence(_mapping(verdict).get("reasons"))
        if isinstance(reason, Mapping)
    )
    rows.extend(
        reason
        for reason in _sequence(_mapping(operational_status).get("readiness_reasons"))
        if isinstance(reason, Mapping)
    )
    manifest_map = _mapping(manifest)
    failure_code = manifest_map.get("failure_code")
    if failure_code:
        rows.append(
            {
                "code": str(failure_code),
                "message": "latest run manifest recorded this failure code",
                "component": "run",
            }
        )
    verdict_map = _mapping(verdict)
    if verdict_map.get("overall") == "blocked" and not rows:
        rows.append(
            {
                "code": FailureCode.SAFETY_VERDICT_BLOCKED.value,
                "message": "safety verdict blocked operation",
                "component": "safety",
            }
        )

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = _normalize_code(row.get("code"), row.get("message"))
        if not code:
            continue
        if code not in deduped:
            deduped[code] = {
                "code": code,
                "message": str(row.get("message") or ""),
                "component": str(row.get("component") or "unknown"),
                "count": _number(row.get("count")),
            }
        else:
            deduped[code]["count"] = (deduped[code].get("count") or 1) + 1
    return sorted(deduped.values(), key=_reason_sort_key)


def _guide_item(reason: Mapping[str, Any], *, run_dir: Path | None) -> dict[str, Any]:
    code = str(reason.get("code") or "UNKNOWN")
    playbook = PLAYBOOKS.get(code) or _generic_playbook(code)
    commands = [
        command.replace("<RUN_DIR>", str(run_dir)) if run_dir is not None else command
        for command in playbook.commands
    ]
    return {
        "code": code,
        "title": playbook.title,
        "severity": playbook.severity,
        "component": reason.get("component") or "unknown",
        "message": reason.get("message") or playbook.diagnosis,
        "diagnosis": playbook.diagnosis,
        "steps": list(playbook.steps),
        "artifacts": list(playbook.artifacts),
        "commands": commands,
        "verification": list(playbook.verification),
        "count": reason.get("count"),
        "source": DEFAULT_SOURCE,
    }


def _generic_playbook(code: str) -> RecoveryPlaybook:
    return RecoveryPlaybook(
        title=f"{code} 복구 확인",
        severity="warning",
        diagnosis="등록된 전용 복구 절차가 없는 실패 코드입니다.",
        steps=(
            "manifest.json과 safety_verdict.json에서 원문 message를 확인합니다.",
            "관련 대시보드 화면에서 데이터, 리스크, 설정 상태를 순서대로 봅니다.",
            "원인을 정리한 뒤 전용 playbook을 추가합니다.",
        ),
        artifacts=("manifest.json", "safety_verdict.json", "events.jsonl"),
        commands=("uv run jayu report build --run <RUN_DIR>",),
        verification=("같은 code가 다음 실행에서 반복되지 않는지 확인",),
    )


def _overall_status(items: Sequence[Mapping[str, Any]]) -> str:
    severities = {str(item.get("severity")) for item in items}
    if "blocked" in severities:
        return "blocked"
    if "warning" in severities:
        return "warning"
    return "success"


def _reason_sort_key(item: Mapping[str, Any]) -> tuple[int, str]:
    severity = PLAYBOOKS.get(str(item.get("code") or ""), _generic_playbook("UNKNOWN")).severity
    return (0 if severity == "blocked" else 1, str(item.get("code") or ""))


def _normalize_code(code: Any, message: Any = None) -> str:
    text = str(code or "").strip().upper()
    message_text = str(message or "").upper()
    if "SURVIVORSHIP_BIAS_RISK" in text or "SURVIVORSHIP_BIAS_RISK" in message_text:
        return "SURVIVORSHIP_BIAS_RISK"
    if not text:
        return ""
    return text


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
