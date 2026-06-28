from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

@dataclass
class DividendReconciliation:
    symbol: str
    expected_pay_date: str
    actual_pay_date: str | None
    expected_amount: float
    actual_amount: float | None
    diff: float | None
    status: str                  # "matched", "missing", "excess", "estimated", "amount_diff"
    reason: str | None

class DividendReconciler:
    """Reconciles expected dividend forecasts against actual cash receipts."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.receipts_path = self.project_root / "state" / "dividend_actual_receipts.csv"

    def load_actual_receipts(self) -> list[dict[str, Any]]:
        """
        Loads actual dividend receipts from the CSV file.
        CSV Columns: date, symbol, amount, currency, source
        """
        if not self.receipts_path.exists():
            # Create template if not exists
            self.receipts_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.receipts_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "symbol", "amount", "currency", "source"])
            return []

        receipts = []
        try:
            with open(self.receipts_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Case-insensitive keys
                    row_lower = {k.lower().strip(): v.strip() for k, v in row.items() if k}
                    symbol = row_lower.get("symbol", "").upper()
                    date_str = row_lower.get("date", "")
                    amount = row_lower.get("amount", "0")
                    
                    if symbol and date_str:
                        receipts.append({
                            "symbol": symbol,
                            "date": date_str,
                            "amount": _to_float(amount),
                            "currency": row_lower.get("currency", "USD").upper(),
                            "source": row_lower.get("source", "manual")
                        })
        except Exception:
            pass
        return receipts

    def save_actual_receipt(self, receipt: dict[str, Any]) -> None:
        """
        Appends a new receipt to the CSV.
        """
        self.receipts_path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.receipts_path.exists()
        
        try:
            with open(self.receipts_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                if is_new:
                    writer.writerow(["date", "symbol", "amount", "currency", "source"])
                writer.writerow([
                    receipt.get("date"),
                    receipt.get("symbol", "").upper(),
                    receipt.get("amount", 0.0),
                    receipt.get("currency", "USD").upper(),
                    receipt.get("source", "manual")
                ])
        except Exception:
            pass

    def reconcile(
        self,
        forecasts: list[Any], # list of DividendForecast
        receipts: list[dict[str, Any]],
        fx_rate: float = 1350.0,
    ) -> list[DividendReconciliation]:
        """
        Compares expected forecasts against actual receipts.
        """
        reconciled = []
        matched_receipt_indices = set()

        # Sort forecasts by expected month or approximate date
        for f in forecasts:
            symbol = f.symbol
            forecast_month = f.forecast_month # YYYY-MM
            expected_amount = f.net_amount # Compare net amount in KRW
            if expected_amount <= 0:
                expected_amount = f.expected_amount_krw
            
            # Find matching receipt in the same month or ±5 days of the month
            matched_rec = None
            matched_idx = -1
            
            for idx, r in enumerate(receipts):
                if idx in matched_receipt_indices:
                    continue
                if r["symbol"] != symbol:
                    continue
                
                # Compare month
                try:
                    rec_dt = datetime.strptime(r["date"], "%Y-%m-%d")
                    rec_month = rec_dt.strftime("%Y-%m")
                    if rec_month == forecast_month:
                        matched_rec = r
                        matched_idx = idx
                        break
                except Exception:
                    pass

            if matched_rec:
                matched_receipt_indices.add(matched_idx)
                actual_amount = self._receipt_amount_krw(matched_rec, fx_rate)
                
                diff = actual_amount - expected_amount
                diff_pct = abs(diff) / expected_amount if expected_amount > 0 else 0.0
                
                status = "matched"
                reason = None
                if diff_pct > 0.05:
                    status = "amount_diff"
                    reason = (
                        f"금액 차이 초과: 예상 {round(expected_amount, 1)}원 대비 "
                        f"실제 {round(actual_amount, 1)}원"
                    )

                reconciled.append(DividendReconciliation(
                    symbol=symbol,
                    expected_pay_date=f"{forecast_month}-15", # approximate
                    actual_pay_date=matched_rec["date"],
                    expected_amount=expected_amount,
                    actual_amount=actual_amount,
                    diff=diff,
                    status=status,
                    reason=reason
                ))
            else:
                # Missing receipt (Expected but not received)
                # Only mark as missing if the month has passed
                now_month = datetime.now().strftime("%Y-%m")
                status = "missing" if forecast_month < now_month else "estimated"
                
                reconciled.append(DividendReconciliation(
                    symbol=symbol,
                    expected_pay_date=f"{forecast_month}-15",
                    actual_pay_date=None,
                    expected_amount=expected_amount,
                    actual_amount=0.0,
                    diff=-expected_amount,
                    status=status,
                    reason="예상 지급월이 경과했으나 입금 내역이 없습니다." if status == "missing" else "지급 대기 중"
                ))

        # Check for excess receipts (Received but not expected)
        for idx, r in enumerate(receipts):
            if idx not in matched_receipt_indices:
                actual_amount = self._receipt_amount_krw(r, fx_rate)
                reconciled.append(DividendReconciliation(
                    symbol=r["symbol"],
                    expected_pay_date="N/A",
                    actual_pay_date=r["date"],
                    expected_amount=0.0,
                    actual_amount=actual_amount,
                    diff=actual_amount,
                    status="excess",
                    reason="예상치 못한 배당 입금입니다."
                ))

        return reconciled

    @staticmethod
    def _receipt_amount_krw(receipt: dict[str, Any], fx_rate: float) -> float:
        amount = _to_float(receipt.get("amount", 0.0))
        currency = str(receipt.get("currency", "KRW")).upper()
        if currency == "USD":
            return round(amount * fx_rate, 2)
        return round(amount, 2)


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    text = str(value).replace(",", "").replace("₩", "").replace("$", "").strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0
