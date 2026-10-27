"""Skript-Blatt im Bot: Event-Bild, Theme, Dateiname, Nachtreihenfolge, Paket-Upload (Dalyan, 27.10.2026)."""

import asyncio
import io
import json
import os
import zipfile
from types import SimpleNamespace

import pytest

from logic import event_images
from logic.script_sheet import assets, pack_install
from tests.test_layout_v2 import summary_for
from tests.test_wizard import make_draft, store  # noqa: F401  (Fixture)


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (4, 4), (0, 0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def pack_dir(tmp_path):
    original = assets.PACK_DIR
    target = tmp_path / "volume" / "script_sheet_assets"
    yield str(target)
    assets.set_pack_dir(original)


# ── Event-Bild ───────────────────────────────────────────────────────────────


def test_image_filename_follows_format():
    assert event_images.image_filename(b"\xff\xd8\xff\xe0rest") == "event_image.jpg"
    assert event_images.image_filename(_png()) == "event_image.png"


def test_rating_change_changes_image_signature(store):
    d = make_draft(store, "preview").data
    before = event_images.image_signature(d)
    d.rating = "red"
    assert event_images.image_signature(d) != before  # neues Theme → neues Bild


def test_too_big_script_gives_no_image(store, monkeypatch):
    async def none(*a, **kw):
        return None
    monkeypatch.setattr(event_images, "generate_script_sheet", none)
    event_images._auto_cache.clear()
    draft = make_draft(store, "preview")
    assert asyncio.run(event_images.render_image(draft.data)) is None
    layout, files = summary_for(store, draft)
    assert files == []
    texts = " ".join(getattr(i, "content", "") for i in layout.walk_children())
    assert "Skript zu groß für ein Bild" in texts
    event_images._auto_cache.clear()


def test_old_posts_keep_their_png_image():
    """Posts von vor dem Skript-Blatt hängen als event_image.png an; beim Neuaufbau bleibt der Name."""
    from discord_ui.event_post import _shown_images
    url = "https://cdn.discordapp.com/attachments/1/2/event_image.png?ex=abc&is=def"
    msg = SimpleNamespace(embeds=[SimpleNamespace(image=SimpleNamespace(url=url),
                                                  thumbnail=SimpleNamespace(url=None))])
    assert _shown_images(msg) == ("event_image.png", False)


# ── Nachtreihenfolge ─────────────────────────────────────────────────────────


def test_tpi_update_stores_nightsheet(tmp_path, monkeypatch):
    from logic import script_cache
    night = {"firstNight": ["dusk", "poisoner", "dawn"], "otherNight": ["dusk", "imp", "dawn"]}
    payload = {script_cache.TPI_ROLES_URL: [{"id": "imp", "name": "Imp", "team": "demon", "edition": "tb"}],
               script_cache.TPI_JINXES_URL: [], script_cache.TPI_NIGHTSHEET_URL: night}
    monkeypatch.setattr(script_cache, "VOLUME_DIR", str(tmp_path))
    monkeypatch.setattr(script_cache, "_download_file",
                        lambda url, **kw: json.dumps(payload[url]).encode() if url in payload else None)
    monkeypatch.setattr(script_cache.time, "sleep", lambda s: None)
    result = script_cache._update_characters_sync()
    assert result.get("nightsheet") is True
    with open(tmp_path / "nightsheet.json", encoding="utf-8") as f:
        assert json.load(f) == night


# ── Asset-Paket hochladen ────────────────────────────────────────────────────


def test_install_pack_replaces_old_pack(pack_dir):
    os.makedirs(os.path.join(pack_dir, "ornaments"))
    with open(os.path.join(pack_dir, "ornaments", "alt.png"), "wb") as f:
        f.write(_png())
    manifest = pack_install.install_pack(_zip({"manifest.json": json.dumps({"version": 2, "missing": []}),
                                               "ornaments/w_37.png": _png(), "pattern_tile.png": _png()}),
                                         target=pack_dir)
    assert manifest["installed_files"] == 3 and manifest["version"] == 2
    assert os.path.exists(os.path.join(pack_dir, "ornaments", "w_37.png"))
    assert not os.path.exists(os.path.join(pack_dir, "ornaments", "alt.png"))  # altes Paket ist weg
    assert assets.PACK_DIR == pack_dir and assets.pattern_tile() is not None


def test_install_pack_accepts_zipped_folder(pack_dir):
    raw = _zip({"script_sheet_assets/manifest.json": "{}", "script_sheet_assets/washes/mask_1.png": _png()})
    assert pack_install.install_pack(raw, target=pack_dir)["installed_files"] == 2
    assert os.path.exists(os.path.join(pack_dir, "washes", "mask_1.png"))


@pytest.mark.parametrize("files, message", [
    ({"manifest.json": "{}", "../boese.png": b"x"}, "Unerlaubter Pfad"),
    ({"manifest.json": "{}", "skript.py": b"x"}, "Unerwartete Datei"),
    ({"ornaments/w_1.png": b"x"}, "manifest.json"),
    ({"manifest.json": "kein json"}, "kein gültiges JSON"),
])
def test_install_pack_rejects_bad_zip_and_keeps_old(pack_dir, files, message):
    os.makedirs(pack_dir)
    with open(os.path.join(pack_dir, "manifest.json"), "w") as f:
        f.write("{}")
    with pytest.raises(pack_install.PackError, match=message):
        pack_install.install_pack(_zip(files), target=pack_dir)
    assert os.listdir(pack_dir) == ["manifest.json"]  # unverändert
    assert not os.path.exists(pack_dir + ".neu")


def test_install_pack_rejects_non_zip(pack_dir):
    with pytest.raises(pack_install.PackError, match="keine ZIP"):
        pack_install.install_pack(b"hallo", target=pack_dir)


def test_upload_command_needs_env_and_owner(monkeypatch, pack_dir):
    from commands import script_sheet_pack

    added = []
    bot = SimpleNamespace(add_cog=lambda cog: added.append(cog))

    async def add_cog(cog):
        added.append(cog)
    bot.add_cog = add_cog
    monkeypatch.delenv(script_sheet_pack.ENV_VAR, raising=False)
    asyncio.run(script_sheet_pack.setup(bot))
    assert added == []  # ohne Variable gibt es den Befehl nicht

    monkeypatch.setenv(script_sheet_pack.ENV_VAR, "1")
    asyncio.run(script_sheet_pack.setup(bot))
    assert len(added) == 1

    async def is_owner(user):
        return user.id == 1
    bot.is_owner = is_owner
    cog = script_sheet_pack.ScriptSheetPack(bot)
    sent = []

    async def send_message(text, **kw):
        sent.append(text)

    async def read():
        return _zip({"manifest.json": "{}", "pattern_tile.png": _png()})
    stranger = SimpleNamespace(user=SimpleNamespace(id=2), response=SimpleNamespace(send_message=send_message))
    upload = SimpleNamespace(size=100, read=read)
    asyncio.run(cog.skriptblatt_paket.callback(cog, stranger, upload))
    assert sent == ["Das darf nur der Besitzer des Bots."] and not os.path.exists(pack_dir)

    monkeypatch.setattr(assets, "PACK_DIR", pack_dir)
    followups = []

    async def defer(**kw):
        pass

    async def followup(text, **kw):
        followups.append(text)
    owner = SimpleNamespace(user=SimpleNamespace(id=1), response=SimpleNamespace(defer=defer),
                            followup=SimpleNamespace(send=followup))
    asyncio.run(cog.skriptblatt_paket.callback(cog, owner, upload))
    assert "Asset-Paket installiert: 2 Dateien" in followups[0]
    assert os.path.exists(os.path.join(pack_dir, "pattern_tile.png"))
