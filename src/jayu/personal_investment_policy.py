"""Personal Investment Policy Manager for checking compliance with user-defined trading rules."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Global fallback policy dictionary in case YAML parsing fails
DEFAULT_POLICY = {
    "policy": {
        "asset_allocation": {
            "max_leverage_ratio": 0.15,
            "min_cash_ratio": 0.10,
            "max_single_position_ratio": 0.25
        },
        "trading_restrictions": {
            "max_daily_trades": 5,
            "cool_down_days_after_loss": 5,
            "max_monthly_loss_krw": 2000000
        },
        "dividend_quality": {
            "min_dividend_trust_score": 80.0,
            "exclude_special_dividend_chasing": True
        }
    }
}


class PersonalInvestmentPolicy:
    """Loads and validates trading intents against the user's investment policy."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root:
            self.project_root = Path(project_root)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        self.policy_path = self.project_root / "configs" / "investment_policy.yaml"
        self.policy = self._load_policy()

    def _load_policy(self) -> dict[str, Any]:
        if not self.policy_path.exists():
            return DEFAULT_POLICY
        try:
            import yaml
            with open(self.policy_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "policy" in data:
                    return data
        except Exception:
            # Fallback regex parser in case yaml package has issues
            try:
                return self._parse_yaml_fallback()
            except Exception:
                pass
        return DEFAULT_POLICY

    def _parse_yaml_fallback(self) -> dict[str, Any]:
        text = self.policy_path.read_text(encoding="utf-8")
        parsed = {}
        current_section = ""
        current_subsection = ""
        for line in text.splitlines():
            line = line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if not line.startswith(" "):
                current_section = line.rstrip(":")
                parsed[current_section] = {}
                continue
            
            sub_match = re.match(r"^\s{2}([A-Za-z0-9_-]+):\s*$", line)
            if sub_match:
                current_subsection = sub_match.group(1)
                parsed.setdefault(current_section, {})[current_subsection] = {}
                continue
            
            val_match = re.match(r"^\s{4}([A-Za-z0-9_-]+):\s*(.+?)\s*$", line)
            if val_match and current_section and current_subsection:
                key, val = val_match.groups()
                val = val.strip()
                # Parse types
                if val.lower() == "true":
                    typed_val: Any = True
                elif val.lower() == "false":
                    typed_val = False
                else:
                    try:
                        typed_val = float(val) if "." in val else int(val)
                    except ValueError:
                        typed_val = val
                parsed[current_section][current_subsection][key] = typed_val
        return parsed if "policy" in parsed else DEFAULT_POLICY

    def get_rule(self, section: str, key: str, default: Any = None) -> Any:
        """Retrieves a specific policy rule value."""
        try:
            return self.policy["policy"][section][key]
        except KeyError:
            return default

    def evaluate_policy_compliance(
        self,
        symbol: str,
        order_amount_krw: float,
        holdings: list[dict[str, Any]],
        cash_krw: float,
        daily_trade_count: int = 0,
        monthly_loss_krw: float = 0.0,
        recent_losses: dict[str, int] = None, # symbol -> days since last loss
        dividend_trust_score: float | None = None,
        is_dividend_focus: bool = False
    ) -> dict[str, Any]:
        """Evaluates whether a proposed trade complies with all policy rules."""
        violations = []
        warnings = []
        
        # Calculate total portfolio value
        current_holdings_value = sum(float(h.get("value_krw") or h.get("price", 0) * h.get("quantity", 0)) for h in holdings)
        total_value = current_holdings_value + cash_krw
        
        # 1. Leverage checks
        # Leverage symbols often include 3x ETFs like SOXL, TQQQ
        leverage_symbols = {"SOXL", "TQQQ", "NVDL", "FNGU", "BULZ"}
        leverage_value = sum(
            float(h.get("value_krw") or h.get("price", 0) * h.get("quantity", 0))
            for h in holdings if h["symbol"].upper() in leverage_symbols
        )
        if symbol.upper() in leverage_symbols:
            leverage_value += order_amount_krw
            
        max_lev_ratio = self.get_rule("asset_allocation", "max_leverage_ratio", 0.15)
        current_lev_ratio = leverage_value / total_value if total_value > 0 else 0.0
        if current_lev_ratio > max_lev_ratio:
            violations.append(
                f"레버리지 비중 한도 초과: 허용 {max_lev_ratio*100:.1f}%, 신규 주문 적용 시 {current_lev_ratio*100:.1f}%"
            )

        # 2. Min Cash check
        min_cash_ratio = self.get_rule("asset_allocation", "min_cash_ratio", 0.10)
        remaining_cash = cash_krw - order_amount_krw
        remaining_cash_ratio = remaining_cash / total_value if total_value > 0 else 0.0
        if remaining_cash_ratio < min_cash_ratio and order_amount_krw > 0:
            violations.append(
                f"최소 현금 비중 미달: 규칙 {min_cash_ratio*100:.1f}%, 주문 후 예상 {remaining_cash_ratio*100:.1f}%"
            )

        # 3. Single Position check
        max_single_ratio = self.get_rule("asset_allocation", "max_single_position_ratio", 0.25)
        existing_pos_value = sum(
            float(h.get("value_krw") or h.get("price", 0) * h.get("quantity", 0))
            for h in holdings if h["symbol"].upper() == symbol.upper()
        )
        post_order_pos_value = existing_pos_value + order_amount_krw
        post_order_pos_ratio = post_order_pos_value / total_value if total_value > 0 else 0.0
        if post_order_pos_ratio > max_single_ratio:
            violations.append(
                f"단일 종목 비중 한도 초과: {symbol} 허용 {max_single_ratio*100:.1f}%, 주문 후 예상 {post_order_pos_ratio*100:.1f}%"
            )

        # 4. Daily trade count check
        max_daily = self.get_rule("trading_restrictions", "max_daily_trades", 5)
        if daily_trade_count >= max_daily:
            violations.append(
                f"일일 매매 횟수 초과: 최대 {max_daily}회, 현재 {daily_trade_count}회 진행됨"
            )

        # 5. Cool down after loss check
        cool_down_days = self.get_rule("trading_restrictions", "cool_down_days_after_loss", 5)
        if recent_losses and symbol.upper() in recent_losses:
            days_since = recent_losses[symbol.upper()]
            if days_since < cool_down_days:
                violations.append(
                    f"손절 후 재진입 제한: {symbol} 손절 후 {days_since}일 경과 (제한 {cool_down_days}일)"
                )

        # 6. Monthly loss limit check
        max_monthly_loss = self.get_rule("trading_restrictions", "max_monthly_loss_krw", 2000000)
        if monthly_loss_krw > max_monthly_loss:
            violations.append(
                f"월간 누적 손실 한도 초과: 한도 {max_monthly_loss:,.0f}원, 현재 누적 손실 {monthly_loss_krw:,.0f}원"
            )

        # 7. Dividend trust score check
        if is_dividend_focus and dividend_trust_score is not None:
            min_score = self.get_rule("dividend_quality", "min_dividend_trust_score", 80.0)
            if dividend_trust_score < min_score:
                violations.append(
                    f"배당 신뢰도 품질 기준 미달: {symbol} 신뢰도 {dividend_trust_score:.1f}점 (기준 {min_score:.1f}점)"
                )

        return {
            "symbol": symbol,
            "compliant": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "metrics": {
                "leverage_ratio": round(current_lev_ratio, 4),
                "remaining_cash_ratio": round(remaining_cash_ratio, 4),
                "post_order_position_ratio": round(post_order_pos_ratio, 4)
            }
        }
