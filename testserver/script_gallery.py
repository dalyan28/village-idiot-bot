"""#skript-bilder: zehn Skript-Blätter zum Vergleichen (Dalyan, 27.10.2026).

Basis-Skripte und die Test-Skripte aus test_scripts/, gerendert wie im Event-Post (generate_script_sheet,
Theme reihum grün/gelb/rot). `/testserver skript-bilder` löscht die alten Bilder im Channel und postet neu,
z. B. nach einem neuen Asset-Paket.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time

import discord

from logic.script_cache import PROJECT_ROOT, get_base_script, validate_script_json
from logic.script_sheet import assets, generate_script_sheet

logger = logging.getLogger(__name__)

CHANNEL_KEY = "sheets"
MESSAGES_KEY = "sheets"
TEST_SCRIPT_DIR = os.path.join(PROJECT_ROOT, "test_scripts")

# (Quelle, Theme): Basis-Skript-Schlüssel oder Dateiname in test_scripts/
GALLERY = [
    ("trouble_brewing", "green"),
    ("bad_moon_rising", "yellow"),
    ("sects_and_violets", "red"),
    ("Boozling.json", "green"),
    ("Everyone_Can_Play.json", "yellow"),
    ("Irrational_Behaviour.json", "red"),
    ("Kill_Suffer_Return.json", "green"),
    ("Onion_Pies.json", "yellow"),
    ("A Vacation in Carcosa.json", "red"),
    ("To tell the truth.json", "green"),
]
THEME_NAMES = {"green": "grün", "yellow": "gelb", "red": "rot"}


def load_script(source: str) -> dict | None:
    """{name, author, characters, content} wie im Wizard, oder None."""
    if not source.endswith(".json"):
        base = get_base_script(source)
        return {"name": base["name"], "author": "", "characters": base["characters"], "content": None} if base else None
    try:
        with open(os.path.join(TEST_SCRIPT_DIR, source), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    api = isinstance(data, dict)  # Antwort der botcscripts-API: Skript-JSON unter „content“
    parsed, _ = validate_script_json(data.get("content") if api else data)
    if parsed and api:
        parsed["name"] = data.get("name") or parsed["name"]
        parsed["author"] = data.get("author") or parsed["author"]
    return parsed


async def render(source: str, theme: str) -> tuple[str, bytes | None]:
    """(Bildunterschrift, JPEG-Bytes oder None)."""
    script = load_script(source)
    if script is None:
        return f"**{source}**: Skript nicht gefunden", None
    meta = next((x for x in (script["content"] or []) if isinstance(x, dict) and x.get("id") == "_meta"), None)
    start = time.perf_counter()
    buf = await generate_script_sheet(script["name"], script["author"], script["characters"], meta=meta,
                                      content=script["content"], theme=theme)
    seconds = time.perf_counter() - start
    name = discord.utils.escape_markdown(script["name"])
    info = f"{len(script['characters'])} Charaktere · Theme {THEME_NAMES[theme]} · {seconds:.1f} s"
    if buf is None:
        return f"**{name}**\n-# {info} · zu groß, kein Bild", None
    image = buf.getvalue()
    return f"**{name}**\n-# {info} · {len(image) / 1_000_000:.1f} MB", image


def pack_note() -> str:
    has_pack = os.path.exists(os.path.join(assets.PACK_DIR, "manifest.json"))
    return ("Mit Asset-Paket gerendert." if has_pack
            else "Ohne Asset-Paket gerendert (Rand einfarbig). Paket per `/skriptblatt_paket` hochladen.")


async def post_gallery(channel, old_ids: list[int]) -> list[int]:
    """Alte Bilder löschen, alle neu rendern und posten. Gibt die neuen Nachrichten-IDs zurück."""
    for mid in old_ids:
        try:
            await (await channel.fetch_message(mid)).delete()
        except discord.HTTPException:
            pass
    no_pings = discord.AllowedMentions.none()
    ids = [(await channel.send(f"**Skript-Bilder zum Vergleichen**\n-# {pack_note()}",
                               allowed_mentions=no_pings)).id]
    for source, theme in GALLERY:
        try:
            caption, image = await render(source, theme)
        except Exception:
            logger.exception("Skript-Bild für %s fehlgeschlagen", source)
            caption, image = f"**{source}**: Rendern fehlgeschlagen (siehe Log)", None
        files = [discord.File(io.BytesIO(image), filename="skript.jpg")] if image else []
        ids.append((await channel.send(caption, files=files, allowed_mentions=no_pings)).id)
    return ids
