"""Homebrew-Icons: eigene Kennung (imgur blockt python-requests), Zwischenspeicher, Standardbild zuerst."""

import io

from PIL import Image

from logic import script_cache


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (200, 0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


class Resp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


def test_fetch_sends_user_agent_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(script_cache, "HOMEBREW_ICON_DIR", str(tmp_path))
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(headers)
        ua = (headers or {}).get("User-Agent", "python-requests/2.32")
        return Resp(429) if ua.startswith("python-requests") else Resp(200, _png())
    monkeypatch.setattr(script_cache.requests, "get", fake_get)
    assert script_cache.fetch_icon("https://i.imgur.com/x.png")
    assert script_cache.fetch_icon("https://i.imgur.com/x.png")  # zweites Mal aus dem Zwischenspeicher
    assert len(calls) == 1 and "VillageIdiotBot" in calls[0]["User-Agent"]


def test_homebrew_uses_first_image_even_for_evil(tmp_path, monkeypatch):
    """Erstes Bild = Standardbild des Charakters (bei Minions/Demons schon das böse)."""
    monkeypatch.setattr(script_cache, "HOMEBREW_ICON_DIR", str(tmp_path))
    fetched = []
    monkeypatch.setattr(script_cache, "fetch_icon", lambda url: fetched.append(url) or _png())
    assert script_cache.load_icon("caesarfallofrome", evil=True, icon_urls=["red.png", "blue.png"]) is not None
    assert fetched == ["red.png"]
