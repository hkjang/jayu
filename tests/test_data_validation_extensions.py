from __future__ import annotations


def test_price_consensus_blocks_provider_disagreement() -> None:
    from jayu.price_consensus_validator import validate_price_consensus

    report = validate_price_consensus(
        {
            "yahoo": [{"symbol": "SOXL", "date": "2026-06-26", "close": 100, "volume": 1000}],
            "toss": [{"symbol": "SOXL", "date": "2026-06-26", "close": 102, "volume": 1000}],
        },
        max_relative_price_delta=0.005,
    )

    assert report["status"] == "failed"
    assert report["summary"]["blocked_symbols"] == ["SOXL"]
    assert report["disagreements"][0]["failure_code"] == "DATA_DISAGREEMENT"


def test_fx_consistency_blocks_large_usd_krw_delta() -> None:
    from jayu.fx_consistency_validator import validate_fx_consistency

    report = validate_fx_consistency(
        {"toss": {"rate": 1350}, "external": {"rate": 1360}},
        max_relative_delta=0.003,
    )

    assert report["status"] == "failed"
    assert report["summary"]["disagreement_count"] == 1


def test_outlier_quarantine_separates_bad_rows() -> None:
    from jayu.outlier_quarantine import quarantine_outliers

    report = quarantine_outliers(
        [
            {"symbol": "AAPL", "close": 100},
            {"symbol": "AAPL", "close": 300},
            {"symbol": "AAPL", "close": 301},
        ],
        dataset="prices",
        max_abs_return=0.5,
    )

    assert report["status"] == "warning"
    assert report["summary"]["verified_count"] == 2
    assert report["summary"]["quarantined_count"] == 1
    assert report["quarantined"][0]["reasons"] == ["price_jump_outlier"]
