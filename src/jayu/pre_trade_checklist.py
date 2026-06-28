from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Attempt to import yaml, fallback to simple parser if unavailable
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


class PreTradeChecklistEvaluator:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self.rules = self._load_rules()

    def _load_rules(self) -> dict[str, Any]:
        default_rules = {
            "data_freshness": {"max_delay_minutes": 15, "fail_severity": "blocked"},
            "risk_gate": {"require_all_passed": True, "fail_severity": "blocked"},
            "market_hours": {"market": "US", "regular_hours_only": True, "fail_severity": "blocked"},
            "account_cash": {"min_cash_usd": 500.0, "min_cash_krw": 500000.0, "fail_severity": "warning"},
            "signal_rating": {"min_score": 0.6, "fail_severity": "warning"},
            "user_approval": {"require_explicit_approval": True, "fail_severity": "blocked"},
        }
        
        if not self.config_path.exists():
            return default_rules

        try:
            if yaml is not None:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    rules = yaml.safe_load(f)
                    if isinstance(rules, dict):
                        return {**default_rules, **rules}
            else:
                # Simple fallback parser for basic YAML if PyYAML is not installed
                rules = {}
                current_section = ""
                with open(self.config_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.split("#")[0].strip()
                        if not line:
                            continue
                        if line.endswith(":"):
                            current_section = line[:-1].strip()
                            rules[current_section] = {}
                        elif ":" in line and current_section:
                            k, v = line.split(":", 1)
                            k = k.strip()
                            v = v.strip()
                            # Convert types
                            if v.lower() == "true":
                                val: Any = True
                            elif v.lower() == "false":
                                val = False
                            else:
                                try:
                                    val = float(v) if "." in v else int(v)
                                except ValueError:
                                    val = v.strip('"\'')
                            rules[current_section][k] = val
                return {**default_rules, **rules}
        except Exception:
            return default_rules
        return default_rules

    def evaluate(
        self,
        *,
        signal_data: dict[str, Any],
        account_data: dict[str, Any],
        market_time: datetime | None = None,
        is_approved: bool = False,
        last_data_update: datetime | None = None,
    ) -> dict[str, Any]:
        """Evaluates the pre-trade checklist rules against current inputs.
        Returns a dict containing:
          - status: "pass" | "blocked" | "warning"
          - checks: dict of detailed check results
          - reasons: list of Korean failure/warning messages
        """
        now_utc = datetime.now(UTC)
        eval_market_time = market_time or now_utc
        
        checks = {}
        reasons = []
        highest_severity = "pass"  # pass < warning < blocked

        def update_status(severity: str, message: str) -> None:
            nonlocal highest_severity
            reasons.append(message)
            if severity == "blocked":
                highest_severity = "blocked"
            elif severity == "warning" and highest_severity != "blocked":
                highest_severity = "warning"

        # 1. Data Freshness Check
        fresh_rules = self.rules.get("data_freshness", {})
        max_delay = fresh_rules.get("max_delay_minutes", 15)
        fresh_severity = fresh_rules.get("fail_severity", "blocked")
        
        if last_data_update is not None:
            # Ensure last_data_update is timezone-aware in UTC
            if last_data_update.tzinfo is None:
                last_data_update = last_data_update.replace(tzinfo=UTC)
            delay = (now_utc - last_data_update).total_seconds() / 60.0
            if delay > max_delay:
                checks["data_freshness"] = {"passed": False, "value": delay, "limit": max_delay}
                update_status(
                    fresh_severity,
                    f"데이터 지연 시간 초과: 최신 업데이트가 {delay:.1f}분 경과하여 허용치({max_delay}분)를 초과했습니다."
                )
            else:
                checks["data_freshness"] = {"passed": True, "value": delay}
        else:
            checks["data_freshness"] = {"passed": False, "value": None}
            update_status(fresh_severity, "데이터 업데이트 시각 정보가 없어 신선도를 확인할 수 없습니다.")

        # 2. Risk Gate Check
        risk_rules = self.rules.get("risk_gate", {})
        require_passed = risk_rules.get("require_all_passed", True)
        risk_severity = risk_rules.get("fail_severity", "blocked")
        
        passed_risk = signal_data.get("risk_passed", True) and not signal_data.get("blocked", False)
        if require_passed and not passed_risk:
            checks["risk_gate"] = {"passed": False}
            update_status(
                risk_severity,
                f"리스크 통제 차단: 신호가 리스크 필터를 통과하지 못했거나 차단되었습니다. (사유: {signal_data.get('block_reason', '불명')})"
            )
        else:
            checks["risk_gate"] = {"passed": True}

        # 3. Market Hours Check
        hours_rules = self.rules.get("market_hours", {})
        market = hours_rules.get("market", "US")
        reg_hours_only = hours_rules.get("regular_hours_only", True)
        market_severity = hours_rules.get("fail_severity", "blocked")

        if market == "US":
            # Convert eval_market_time to New York time
            ny_time = eval_market_time.astimezone(ZoneInfo("America/New_York"))
            weekday = ny_time.weekday()  # 0: Mon, 6: Sun
            is_weekend = weekday >= 5
            
            # Regular Market Hours: 09:30 - 16:00
            market_start = ny_time.replace(hour=9, minute=30, second=0, microsecond=0)
            market_end = ny_time.replace(hour=16, minute=0, second=0, microsecond=0)
            
            in_hours = not is_weekend and (market_start <= ny_time <= market_end)
            
            if reg_hours_only and not in_hours:
                checks["market_hours"] = {"passed": False, "market_time": ny_time.isoformat()}
                update_status(
                    market_severity,
                    f"미국 정규장 시간 외: 현재 시각({ny_time.strftime('%H:%M:%S')})은 미국 정규 거래 시간(09:30~16:00, 평일)이 아닙니다."
                )
            else:
                checks["market_hours"] = {"passed": True, "market_time": ny_time.isoformat()}
        else:
            # Simple fallback for non-US
            checks["market_hours"] = {"passed": True}

        # 4. Account Cash Check
        cash_rules = self.rules.get("account_cash", {})
        min_usd = cash_rules.get("min_cash_usd", 500.0)
        min_krw = cash_rules.get("min_cash_krw", 500000.0)
        cash_severity = cash_rules.get("fail_severity", "warning")
        
        avail_usd = account_data.get("cash_usd", 0.0)
        avail_krw = account_data.get("cash_krw", 0.0)
        
        cash_passed = True
        cash_reasons = []
        if avail_usd < min_usd:
            cash_passed = False
            cash_reasons.append(f"USD 잔고 부족 (보유: ${avail_usd:.2f} < 최소기준: ${min_usd:.2f})")
        if avail_krw < min_krw:
            cash_passed = False
            cash_reasons.append(f"KRW 잔고 부족 (보유: {avail_krw:,.0f}원 < 최소기준: {min_krw:,.0f}원)")
            
        if not cash_passed:
            checks["account_cash"] = {"passed": False, "usd": avail_usd, "krw": avail_krw}
            update_status(cash_severity, f"계좌 가용 현금 경고: {', '.join(cash_reasons)}")
        else:
            checks["account_cash"] = {"passed": True, "usd": avail_usd, "krw": avail_krw}

        # 5. Signal Rating Check
        rating_rules = self.rules.get("signal_rating", {})
        min_score = rating_rules.get("min_score", 0.6)
        rating_severity = rating_rules.get("fail_severity", "warning")
        
        sig_score = signal_data.get("score", 0.0)
        if sig_score < min_score:
            checks["signal_rating"] = {"passed": False, "score": sig_score, "limit": min_score}
            update_status(
                rating_severity,
                f"신호 신뢰도 미달: 생성된 신호의 강도({sig_score:.2f})가 최소 기준치({min_score:.2f})보다 낮습니다."
            )
        else:
            checks["signal_rating"] = {"passed": True, "score": sig_score}

        # 6. User Approval Check
        approval_rules = self.rules.get("user_approval", {})
        require_approval = approval_rules.get("require_explicit_approval", True)
        approval_severity = approval_rules.get("fail_severity", "blocked")
        
        if require_approval and not is_approved:
            checks["user_approval"] = {"passed": False}
            update_status(
                approval_severity,
                "사용자 의사결정 승인 대기: 해당 신호에 대해 명시적인 사용자 '승인(Approve)' 처리가 완료되지 않았습니다."
            )
        else:
            checks["user_approval"] = {"passed": True}

        # 7. Dividend Chasing Guard Check
        symbol = signal_data.get("symbol") or signal_data.get("ticker")
        if symbol:
            try:
                from .dividend_chasing_guard import DividendChasingGuard
                project_root = self.config_path.parent.parent
                guard = DividendChasingGuard(project_root)
                
                # We can pass the signal's price if available, otherwise let it fetch
                sig_price = signal_data.get("price") or signal_data.get("current_price")
                guard_res = guard.evaluate_symbol_simple(str(symbol), price=sig_price)
                
                if guard_res.get("verdict") in {"warning", "block"}:
                    guard_severity = "blocked" if guard_res.get("verdict") == "block" else "warning"
                    checks["dividend_chasing_guard"] = {
                        "passed": False,
                        "verdict": guard_res.get("verdict"),
                        "reasons": guard_res.get("reasons")
                    }
                    for check_item in guard_res.get("checks", []):
                        update_status(guard_severity, f"배당 보호 경고 [{check_item.get('type')}]: {check_item.get('message')}")
                else:
                    checks["dividend_chasing_guard"] = {"passed": True}
            except Exception as e:
                checks["dividend_chasing_guard"] = {"passed": False, "error": str(e)}

        return {
            "status": highest_severity,
            "checks": checks,
            "reasons": reasons,
        }
