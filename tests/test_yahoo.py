from __future__ import annotations

import os

import jayu.yahoo as yahoo


class _FakeSession:
    """Stand-in for curl_cffi Session so the test never opens a connection."""

    def __init__(self, *args, **kwargs):
        self.verify = kwargs.get("verify")
        self.impersonate = kwargs.get("impersonate")


def _patch(tmp_path, monkeypatch, *, source_text="NEW-CA"):
    home = tmp_path / "home"
    source = tmp_path / "source_cacert.pem"
    source.write_text(source_text, encoding="utf-8")
    monkeypatch.setattr(yahoo.Path, "home", lambda: home)
    monkeypatch.setattr(yahoo.certifi, "where", lambda: str(source))
    monkeypatch.setattr(yahoo.requests, "Session", _FakeSession)
    return home, source


def test_first_call_copies_ca_and_sets_verify(tmp_path, monkeypatch):
    home, _ = _patch(tmp_path, monkeypatch)

    session = yahoo.get_yahoo_session()

    ca_path = home / ".jayu" / "cacert.pem"
    assert ca_path.exists()
    assert ca_path.read_text(encoding="utf-8") == "NEW-CA"
    # Session verifies against the ASCII-safe copied bundle.
    assert session.verify == str(ca_path)
    assert session.impersonate == "chrome"


def test_fresh_ca_is_not_recopied(tmp_path, monkeypatch):
    home, source = _patch(tmp_path, monkeypatch)
    ca_path = home / ".jayu" / "cacert.pem"
    ca_path.parent.mkdir(parents=True)
    ca_path.write_text("OLD-CA", encoding="utf-8")
    newer = source.stat().st_mtime + 100
    os.utime(ca_path, (newer, newer))  # ca newer than source -> keep

    yahoo.get_yahoo_session()

    assert ca_path.read_text(encoding="utf-8") == "OLD-CA"


def test_stale_ca_is_refreshed(tmp_path, monkeypatch):
    home, source = _patch(tmp_path, monkeypatch)
    ca_path = home / ".jayu" / "cacert.pem"
    ca_path.parent.mkdir(parents=True)
    ca_path.write_text("OLD-CA", encoding="utf-8")
    older = source.stat().st_mtime - 100
    os.utime(ca_path, (older, older))  # ca older than source -> refresh

    yahoo.get_yahoo_session()

    assert ca_path.read_text(encoding="utf-8") == "NEW-CA"
