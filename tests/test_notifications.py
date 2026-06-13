from unittest.mock import Mock, patch

from jayu.notifications import KakaoNotifier, build_signal_message
from jayu.paths import RuntimePaths
from jayu.settings import Settings


def test_kakao_401_refreshes_once_and_retries(tmp_path):
    settings = Settings(
        kakao_access_token="old",
        kakao_refresh_token="refresh",
        kakao_rest_api_key="rest-key",
    )
    paths = RuntimePaths.from_root(tmp_path)
    paths.ensure_runtime_dirs()
    unauthorized = Mock(status_code=401, text="expired")
    refreshed = Mock(
        status_code=200,
        json=lambda: {"access_token": "new", "expires_in": 100},
    )
    refreshed.raise_for_status = Mock()
    sent = Mock(status_code=200, json=lambda: {"result_code": 0})

    with patch(
        "jayu.notifications.requests.post",
        side_effect=[unauthorized, refreshed, sent],
    ):
        result = KakaoNotifier(settings, paths).send("hello")

    assert result["status"] == "sent"
    assert result["refreshed"] is True
    assert (paths.state_dir / "kakao_tokens.json").exists()


def test_signal_message_is_truncated_with_detail_pointer():
    signals = {
        f"TICKER{index}": {
            "signal": "buy " + ("x" * 100),
            "eligible": True,
        }
        for index in range(20)
    }

    message = build_signal_message(signals, max_chars=200)

    assert len(message) <= 200
    assert "signals/today_signals.json" in message


def test_kakao_retries_with_exponential_backoff_and_records_failure(tmp_path):
    settings = Settings(
        kakao_access_token="token",
        notification_retries=3,
    )
    paths = RuntimePaths.from_root(tmp_path)
    paths.ensure_runtime_dirs()
    failed = Mock(status_code=500, text="server error")

    with (
        patch("jayu.notifications.requests.post", return_value=failed),
        patch("jayu.notifications.time.sleep") as sleep,
    ):
        try:
            KakaoNotifier(settings, paths).send("hello")
        except RuntimeError:
            pass

    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]
    assert (paths.state_dir / "notification_failures.jsonl").exists()
