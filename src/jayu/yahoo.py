from __future__ import annotations

import shutil
from pathlib import Path

import certifi
from curl_cffi import requests


def get_yahoo_session():
    """Use an ASCII-only CA path for Windows workspaces with Unicode paths."""
    ca_dir = Path.home() / ".jayu"
    ca_path = ca_dir / "cacert.pem"
    source = Path(certifi.where())
    if not ca_path.exists() or ca_path.stat().st_mtime < source.stat().st_mtime:
        ca_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, ca_path)
    return requests.Session(verify=str(ca_path))
