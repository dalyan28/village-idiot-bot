"""Charakter-Icons als kleine Emojis vor Charakternamen (Dalyan, 20.10.2026).

Die Icons werden als App-Emojis des Bots hochgeladen (nicht als Server-Emojis): Sie gehören der
Bot-Anwendung, belegen keine Emoji-Plätze auf dem Server und funktionieren überall, wo der Bot
schreibt. Discord erlaubt bis zu 2000 App-Emojis, die offizielle Liste hat rund 180 Charaktere.

Der Name des Emojis ist die Charakter-ID (z. B. `fortune_teller`). Beim Start lädt der Bot die
vorhandenen App-Emojis und lädt fehlende Icons nach (`sync`).
"""

from __future__ import annotations

import io
import logging
import re

import discord

from logic.script_cache import get_character_icon_path, load_characters

logger = logging.getLogger(__name__)

EMOJI_SIZE = 128  # Pixel; Discord zeigt es neben Text ohnehin klein
EVIL_TYPES = ("minion", "demon")

_emojis: dict[str, str] = {}  # Charakter-ID → "<:name:id>"


def emoji_name(char_id: str) -> str | None:
    """Gültiger Emoji-Name (2–32 Zeichen, Buchstaben/Ziffern/Unterstrich) oder None."""
    name = re.sub(r"[^a-z0-9_]", "", char_id.lower())
    return name if 2 <= len(name) <= 32 else None


def emoji_for(char_id: str) -> str:
    """Emoji für den Charakter als Text, leer wenn es (noch) keins gibt."""
    return _emojis.get(char_id, "")


def with_emoji(char_id: str, text: str) -> str:
    emoji = emoji_for(char_id)
    return f"{emoji} {text}" if emoji else text


def set_emojis(emojis) -> int:
    """Übernimmt die App-Emojis, deren Name eine bekannte Charakter-ID ist."""
    known = load_characters()
    _emojis.clear()
    for emoji in emojis:
        if emoji.name in known:
            _emojis[emoji.name] = str(emoji)
    return len(_emojis)


def _png(path: str) -> bytes:
    from PIL import Image

    with Image.open(path) as img:
        img = img.convert("RGBA")
        bbox = img.getbbox()  # durchsichtigen Rand abschneiden, damit das Icon die Fläche füllt
        if bbox:
            img = img.crop(bbox)
        img.thumbnail((EMOJI_SIZE, EMOJI_SIZE))
        canvas = Image.new("RGBA", (EMOJI_SIZE, EMOJI_SIZE), (0, 0, 0, 0))
        canvas.paste(img, ((EMOJI_SIZE - img.width) // 2, (EMOJI_SIZE - img.height) // 2))
        out = io.BytesIO()
        canvas.save(out, format="PNG")
        return out.getvalue()


async def sync(client: discord.Client) -> dict:
    """Lädt vorhandene App-Emojis und lädt Icons hoch, für die es noch keins gibt."""
    existing = await client.fetch_application_emojis()
    have = {e.name for e in existing}
    created, missing_icon, errors = [], [], []
    for char_id, info in load_characters().items():
        name = emoji_name(char_id)
        if name is None or name in have:
            continue
        evil = info.get("character_type", "").lower() in EVIL_TYPES
        path = get_character_icon_path(char_id, evil=evil)
        if path is None:
            missing_icon.append(char_id)
            continue
        try:
            existing.append(await client.create_application_emoji(name=name, image=_png(path)))
            created.append(char_id)
        except (discord.HTTPException, OSError) as e:
            errors.append(f"{char_id}: {e}")
    count = set_emojis(existing)
    if errors:
        logger.warning("Charakter-Emojis: %d Fehler, z. B. %s", len(errors), errors[:3])
    return {"emojis": count, "created": len(created), "missing_icon": missing_icon, "errors": errors}
