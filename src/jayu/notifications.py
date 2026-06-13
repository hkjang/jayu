from __future__ import annotations

import json
import hashlib
import os
import stat
import time
from datetime import UTC, datetime
from typing import Any

import requests

from .io import atomic_write_json, read_json
from .paths import RuntimePaths
from .settings import Settings
from .signals import SignalAction, normalize_today_signal


def _secret(settings: Settings, field: str) -> str | None:
    value = getattr(settings, field)
    return value.get_secret_value() if value else None


class KakaoNotifier:
    send_url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    refresh_url = "https://kauth.kakao.com/oauth/token"

    def __init__(self, settings: Settings, paths: RuntimePaths):
        self.settings = settings
        self.paths = paths
        self.token_file = paths.state_dir / "kakao_tokens.json"
        self.failure_file = paths.state_dir / "notification_failures.jsonl"
        stored = read_json(self.token_file, default={}) or {}
        self.access_token = (
            os.environ.get("JAYU_KAKAO_ACCESS_TOKEN")
            or stored.get("access_token")
            or _secret(settings, "kakao_access_token")
        )
        self.refresh_token = (
            os.environ.get("JAYU_KAKAO_REFRESH_TOKEN")
            or stored.get("refresh_token")
            or _secret(settings, "kakao_refresh_token")
        )

    def _refresh(self) -> None:
        rest_api_key = _secret(self.settings, "kakao_rest_api_key")
        client_secret = _secret(self.settings, "kakao_client_secret")
        if not rest_api_key or not self.refresh_token:
            raise RuntimeError("Kakao refresh requires REST API key and refresh token")
        payload = {
            "grant_type": "refresh_token",
            "client_id": rest_api_key,
            "refresh_token": self.refresh_token,
        }
        if client_secret:
            payload["client_secret"] = client_secret
        response = requests.post(
            self.refresh_url,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
            data=payload,
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        self.access_token = body["access_token"]
        self.refresh_token = body.get("refresh_token", self.refresh_token)
        atomic_write_json(
            self.token_file,
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_in": body.get("expires_in"),
                "refresh_token_expires_in": body.get("refresh_token_expires_in"),
            },
        )
        self._secure_token_file()

    def _request(self, message: str) -> requests.Response:
        if (
            not self.access_token
            or any(ord(char) > 127 for char in self.access_token)
            or "YOUR_" in self.access_token.upper()
        ):
            raise RuntimeError("Kakao access token is not configured")
        template = {
            "object_type": "text",
            "text": message,
            "link": {
                "web_url": "https://finance.naver.com",
                "mobile_web_url": "https://finance.naver.com",
            },
        }
        return requests.post(
            self.send_url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            },
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=15,
        )

    def send(self, message: str) -> dict[str, Any]:
        message = _limit_message(message, self.settings.notification_message_limit)
        refreshed = False
        failures: list[str] = []
        for attempt in range(1, self.settings.notification_retries + 1):
            try:
                response = self._request(message)
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
                if isinstance(exc, requests.RequestException) and (
                    attempt < self.settings.notification_retries
                ):
                    time.sleep(2 ** (attempt - 1))
                    continue
                break
            if response.status_code == 200:
                return {
                    "status": "sent",
                    "attempts": attempt,
                    "refreshed": refreshed,
                    "response": response.json(),
                }
            if response.status_code == 401 and not refreshed:
                try:
                    self._refresh()
                    refreshed = True
                    continue
                except Exception as exc:
                    failures.append(f"refresh {type(exc).__name__}: {exc}")
                    break
            failures.append(f"HTTP {response.status_code}: {response.text[:200]}")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.settings.notification_retries:
                    time.sleep(2 ** (attempt - 1))
                continue
            break
        error = "Kakao notification failed: " + " | ".join(failures)
        self._record_failure(message, error)
        raise RuntimeError(error)

    def _record_failure(self, message: str, error: str) -> None:
        self.failure_file.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": datetime.now(UTC).isoformat(),
            "channel": "kakao",
            "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "message_length": len(message),
            "error": error,
        }
        with self.failure_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _secure_token_file(self) -> None:
        try:
            os.chmod(self.token_file, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def _limit_message(message: str, max_chars: int) -> str:
    if len(message) <= max_chars:
        return message
    suffix = "\n... truncated; details: signals/today_signals.json"
    return message[: max(0, max_chars - len(suffix))].rstrip() + suffix


def build_simulation_message(
    *,
    run_time: str,
    vix_value: float,
    improved_tickers: list[str],
    summary_lines: list[str],
) -> str:
    lines = [
        f"Jayu strategy run ({run_time})",
        f"VIX: {vix_value:.2f}" if vix_value > 0 else "VIX: unavailable",
        f"Improved: {', '.join(improved_tickers) if improved_tickers else 'none'}",
        "",
        *summary_lines,
    ]
    return "\n".join(lines).strip()


def build_signal_message(
    signals: dict[str, dict[str, Any]],
    *,
    max_chars: int = 900,
) -> str:
    lines = ["Jayu daily signals"]
    for ticker, signal in signals.items():
        signal = normalize_today_signal(dict(signal))
        eligible = signal.get("eligible", False) and signal.get("action") == SignalAction.BUY.value
        status = "ELIGIBLE" if eligible else "BLOCKED"
        reasons = signal.get("risk", {}).get("violations", [])
        suffix = f" | {'; '.join(reasons)}" if reasons else ""
        lines.append(f"{ticker}: {signal.get('signal', '?')} [{status}]{suffix}")
    return _limit_message("\n".join(lines), max_chars)
