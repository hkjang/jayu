"""Compatibility entry point for Kakao notifications."""

from pathlib import Path
import sys

from jayu.legacy_cli import run_legacy_command
from jayu.notifications import KakaoNotifier
from jayu.settings import load_settings


def send_kakao(message: str):
    root = Path(__file__).resolve().parent
    config = root / "config.json"
    settings = load_settings(config if config.exists() else None)
    return KakaoNotifier(settings, settings.runtime_paths(root)).send(message)


if __name__ == "__main__":
    raise SystemExit(
        run_legacy_command(
            ("notify", "--channel", "kakao"),
            sys.argv[1:],
            script_name="stock_kakao.py",
            replacement="jayu notify --channel kakao",
        )
    )
