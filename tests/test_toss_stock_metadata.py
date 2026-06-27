import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from jayu.toss_stock_metadata import TossStockMetadataManager

def test_toss_stock_metadata_manager_fallbacks(tmp_path: Path):
    manager = TossStockMetadataManager(tmp_path)
    
    # Test fallback mapping
    mapping = manager.get_stock_names(client=None)
    assert mapping["005930"] == "삼성전자"
    assert mapping["AAPL"] == "애플"
    assert mapping["TSLA"] == "테슬라"

def test_toss_stock_metadata_manager_with_client_and_user_data(tmp_path: Path):
    # Setup mock orders
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    
    orders_file = state_dir / "toss_orders.json"
    orders_data = [
        {"symbol": "MSFT"},
        {"symbol": "005930"},
        {"symbol": "NEW_TICKER"}
    ]
    with open(orders_file, "w", encoding="utf-8") as f:
        json.dump(orders_data, f)
        
    manager = TossStockMetadataManager(tmp_path)
    
    # Mock Toss client
    mock_client = MagicMock()
    # Mock client.stocks(symbols) returning metadata for NEW_TICKER
    mock_client.stocks.return_value = {
        "result": [
            {
                "symbol": "NEW_TICKER",
                "name": "새로운티커회사",
                "englishName": "NEW TICKER CO",
                "currency": "USD"
            }
        ]
    }
    
    mapping = manager.get_stock_names(mock_client)
    
    # Verify mock client was called for NEW_TICKER
    # (MSFT and 005930 are in fallback, but NEW_TICKER is queried)
    mock_client.stocks.assert_called_once()
    
    # Verify mapping has NEW_TICKER resolved
    assert mapping["NEW_TICKER"] == "새로운티커회사"
    assert mapping["005930"] == "삼성전자"
    
    # Verify cache was saved
    assert manager.cache_file.exists()
    cache = manager.load_cache()
    assert "NEW_TICKER" in cache
    assert cache["NEW_TICKER"]["name"] == "새로운티커회사"
