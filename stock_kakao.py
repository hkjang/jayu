"""Compatibility entry point for Kakao notifications."""

from pathlib import Path

from jayu.notifications import KakaoNotifier
from jayu.settings import load_settings


def send_kakao(message: str):
    root = Path(__file__).resolve().parent
    config = root / "config.json"
    settings = load_settings(config if config.exists() else None)
    return KakaoNotifier(settings, settings.runtime_paths(root)).send(message)


if __name__ == "__main__":
    raise SystemExit("Use: jayu notify --channel kakao")
