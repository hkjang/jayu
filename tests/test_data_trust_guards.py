from __future__ import annotations


def _valid_order(order_id: str = "order-1") -> dict:
    return {
        "orderId": order_id,
        "symbol": "AAPL",
        "side": "BUY",
        "status": "FILLED",
        "price": "100",
        "quantity": "3",
        "currency": "USD",
        "orderedAt": "2026-03-28T09:30:00+09:00",
        "execution": {
            "filledQuantity": "3",
            "averageFilledPrice": "100",
            "filledAmount": "300",
            "commission": "1",
            "tax": "0",
            "filledAt": "2026-03-28T09:31:00+09:00",
        },
    }


def test_api_response_contract_accepts_valid_toss_order() -> None:
    from jayu.api_response_contracts import validate_api_response_contract

    report = validate_api_response_contract("orders", [_valid_order()])

    assert report["status"] == "success"
    assert report["summary"]["violation_count"] == 0


def test_api_response_contract_blocks_missing_required_order_fields() -> None:
    from jayu.api_response_contracts import validate_api_response_contract

    report = validate_api_response_contract("orders", [{"symbol": "AAPL", "status": "FILLED"}])

    assert report["status"] == "failed"
    assert report["failure_code"] == "DATA_CONTRACT_FAILED"
    assert report["summary"]["violation_count"] >= 1


def test_toss_order_integrity_flags_duplicate_and_amount_mismatch() -> None:
    from jayu.toss_order_integrity_check import check_toss_order_integrity

    bad = _valid_order("order-dup")
    bad["execution"] = dict(bad["execution"])
    bad["execution"]["filledAmount"] = "999"
    report = check_toss_order_integrity([bad, _valid_order("order-dup")])

    assert report["status"] == "failed"
    assert report["summary"]["duplicate_order_count"] == 1
    codes = {issue["code"] for issue in report["issues"]}
    assert "duplicate_order_id" in codes
    assert "filled_amount_mismatch" in codes


def test_empty_toss_order_history_is_not_a_contract_failure() -> None:
    from jayu.api_response_contracts import validate_api_response_contract
    from jayu.toss_order_integrity_check import check_toss_order_integrity

    contract = validate_api_response_contract("orders", [])
    integrity = check_toss_order_integrity([])

    assert contract["status"] == "not_evaluated"
    assert integrity["status"] == "not_evaluated"
    assert integrity["integrity_score"] == 75


def test_data_trust_gate_blocks_low_integrity_dataset() -> None:
    from jayu.data_decision_gate import evaluate_data_decision_gate
    from jayu.data_trust_score import build_data_trust_report

    trust = build_data_trust_report(
        {
            "toss_orders": {
                "contract": {"summary": {"row_count": 2, "violation_count": 3}},
                "integrity": {"integrity_score": 40},
                "hard_block": True,
                "source": "fixture",
            }
        }
    )
    gate = evaluate_data_decision_gate(trust)

    assert trust["decision"] == "block"
    assert gate["allowed"] is False
    assert gate["summary"]["blocking_count"] == 1
