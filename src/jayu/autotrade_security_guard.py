import json
from pathlib import Path
from typing import Any
from .toss_security_master import TossSecurityMaster
from .toss_trade_feature_store import build_toss_order_feature_store

class AutotradeSecurityGuard:
    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.security_master = TossSecurityMaster(self.project_root)
        self.orders_file = self.project_root / "state" / "toss_orders.json"

    def evaluate_order(self, symbol: str, target_amount_krw: float) -> dict[str, Any]:
        """
        Evaluates whether an autotrading order should be allowed, scaled down, or blocked.
        """
        symbol = symbol.strip().upper()
        master = self.security_master.get_security_master()
        
        sec_info = master.get(symbol)
        if not sec_info:
            return {
                "symbol": symbol,
                "verdict": "block",
                "reason": "종목 기준정보 미검증 (마스터 정보 부재)",
                "allowed_amount": 0.0
            }

        # 1. Verification of metadata
        if not sec_info.get("name") or not sec_info.get("market") or not sec_info.get("currency"):
            return {
                "symbol": symbol,
                "verdict": "block",
                "reason": "종목 필수 필드 누락 (시장/통화 미확인)",
                "allowed_amount": 0.0
            }

        # 2. Warning Registry & Risk status
        warnings = sec_info.get("warnings") or {}
        m_warning = str(warnings.get("marketWarning") or "NONE").upper()
        admin = bool(warnings.get("administrative", False))
        delist = bool(warnings.get("delistingCaution", False))
        suspended = bool(warnings.get("tradingSuspended", False))

        if suspended:
            return {
                "symbol": symbol,
                "verdict": "block",
                "reason": "거래정지 종목",
                "allowed_amount": 0.0
            }
        if admin:
            return {
                "symbol": symbol,
                "verdict": "block",
                "reason": "관리종목 지정",
                "allowed_amount": 0.0
            }
        if delist:
            return {
                "symbol": symbol,
                "verdict": "block",
                "reason": "상장폐지 우려 종목",
                "allowed_amount": 0.0
            }
        if m_warning in {"INVESTMENT_DANGER", "DANGER"}:
            return {
                "symbol": symbol,
                "verdict": "block",
                "reason": "투자위험 종목 지정",
                "allowed_amount": 0.0
            }

        # 3. Leverage limits
        leverage = float(sec_info.get("leverage_factor") or 1.0)
        multiplier = 1.0
        if leverage > 1.0:
            # Scale down order size by leverage factor
            multiplier = 1.0 / leverage

        # 4. Past chronic losses from feature store
        chronic_loss_reason = None
        if self.orders_file.exists():
            try:
                with open(self.orders_file, "r", encoding="utf-8") as f:
                    orders_payload = json.load(f)
                features = build_toss_order_feature_store(orders_payload, security_master=master)
                
                # Check symbol-level realized pnl
                for s_stat in features.get("by_symbol", []):
                    if s_stat.get("symbol") == symbol:
                        pnl = s_stat.get("realized_pnl_krw", 0.0)
                        win_rate = s_stat.get("win_rate_pct")
                        
                        # If cumulative losses exceed 1,000,000 KRW, apply a cooling period or reduction
                        if pnl < -1000000.0:
                            multiplier *= 0.5
                            chronic_loss_reason = f"과거 누적 손실 극심 ({pnl:,.0f} KRW) - 주문 크기 50% 추가 축소"
                        elif win_rate is not None and win_rate < 30.0 and s_stat.get("round_count", 0) >= 3:
                            multiplier *= 0.7
                            chronic_loss_reason = f"과거 승률 극히 저조 ({win_rate}%) - 주문 크기 30% 추가 축소"
                        break
            except Exception:
                pass

        final_amount = target_amount_krw * multiplier
        
        if multiplier < 1.0:
            reasons = []
            if leverage > 1.0:
                reasons.append(f"{leverage}x 레버리지 상품 (배율 조절)")
            if chronic_loss_reason:
                reasons.append(chronic_loss_reason)
                
            return {
                "symbol": symbol,
                "verdict": "reduce",
                "reason": " · ".join(reasons),
                "allowed_amount": round(final_amount, 2)
            }

        return {
            "symbol": symbol,
            "verdict": "allow",
            "reason": "보안 가드라인 통과",
            "allowed_amount": round(target_amount_krw, 2)
        }
