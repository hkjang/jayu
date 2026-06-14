"""Compatibility entry point for Kakao notifications."""

from pathlib import Path
import sys
import warnings

from jayu.cli import app
from jayu.notifications import KakaoNotifier
from jayu.settings import load_settings


def send_kakao(message: str):
    root = Path(__file__).resolve().parent
    config = root / "config.json"
    settings = load_settings(config if config.exists() else None)
    return KakaoNotifier(settings, settings.runtime_paths(root)).send(message)


if __name__ == "__main__":
    warnings.warn(
        "stock_kakao.py is deprecated; use `jayu notify --channel kakao`. "
        "Removal date: 2026-09-30.",
        FutureWarning,
        stacklevel=1,
    )
    app(args=["notify", "--channel", "kakao", *sys.argv[1:]], prog_name="jayu")
