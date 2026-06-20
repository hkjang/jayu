from jayu.metric_dictionary import (
    metric_definition,
    metric_definitions_for,
    metric_dictionary_payload,
)


def test_metric_dictionary_exposes_korean_explanations():
    overview = metric_definitions_for("overview")

    assert overview[0]["key"] == "data_validation"
    assert overview[0]["plain_name"] == "가격 데이터 신뢰도"
    assert "데이터 오류 확인" in overview[0]["watch_out"]


def test_metric_dictionary_payload_groups_and_specific_lookup():
    payload = metric_dictionary_payload("overview", "signals")

    assert list(payload) == ["overview", "signals"]
    assert any(item["key"] == "eligible_buy" for item in payload["signals"])
    assert metric_definition("stop_price")["label"] == "손절가"
    assert metric_definition("missing_metric") is None
